"""Materialize a *conservative subset* of MEDSL presidential returns.

Run in a single PostgreSQL REPEATABLE READ transaction; source observations and
published geographic resolution decisions are never updated. This adapter
publishes county-level TOTAL-mode returns with exact per-observation lineage.
Non-TOTAL modes remain excluded (with issue codes) until a vetted cross-mode
reconciliation policy exists. Do not interpret PARTIAL batches as national totals.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.core import DataSource, Jurisdiction
from app.models.election import (CanonicalResultBatch, CanonicalPublication,
                                 CanonicalVoteReturn, CanonicalMaterializationIssue)
from app.models.geography import GeographicReference, GeographicResolution
from app.models.ingestion import ElectionResultObservation, SourceActiveYear, SourceRelease
from app.services import elections
from ingestion.canonical_medsl import DATES, RULESET, SUPPORTED_YEARS, eligibility, vote_kind, unit_reconciliation_issue


class MaterializationError(ValueError):
    pass


def _hash_projection(year: int, release: SourceRelease, reference_id: UUID,
                     observations: list, geography: dict, state_groups: dict) -> str:
    sha = sha256()
    header = [RULESET, year, str(release.id), release.sha256, str(reference_id)]
    sha.update(json.dumps(header, separators=(",", ":")).encode())
    # Changes to the canonical state scope are material changes to the
    # projection even if all source/geographic observation rows are unchanged.
    state_selection = sorted(((code, tuple(sorted(str(j.id) for j in items)))
                              for code, items in state_groups.items()), key=lambda item: item[0] or "")
    sha.update(json.dumps(state_selection, separators=(",", ":")).encode())
    for row in observations:
        geo = geography.get(row.id)
        vals = (str(row.id), row.row_sha256, row.logical_key, row.candidate_kind,
                row.candidate_normalized, row.party_normalized, row.mode_normalized,
                row.candidate_votes, row.total_votes,
                str(geo[0].id) if geo else None,
                geo[0].decision_sha256 if geo else None,
                geo[0].ruleset_version if geo else None,
                geo[0].status if geo else None,
                str(geo[0].jurisdiction_id) if geo else None,
                str(geo[1].id) if geo and geo[1] else None,
                geo[1].kind if geo and geo[1] else None,
                str(geo[1].jurisdiction_id) if geo and geo[1] else None,
                geo[1].vintage_start if geo and geo[1] else None,
                geo[1].vintage_end if geo and geo[1] else None)
        sha.update(json.dumps(vals, default=str, ensure_ascii=False, separators=(",", ":")).encode())
        sha.update(b"\n")
    return sha.hexdigest()


def _load_projection(session: Session, year: int, reference_release_id: UUID | None):
    source = session.scalar(select(DataSource).where(DataSource.name == "medsl_presidential_county"))
    if source is None:
        raise MaterializationError("No MEDSL source registered")
    active = session.get(SourceActiveYear, (source.id, year))
    if active is None:
        raise MaterializationError(f"No active source release for MEDSL {year}")
    release = session.get(SourceRelease, active.release_id)
    if release is None or release.source_id != source.id:
        raise MaterializationError("Active source release does not belong to MEDSL")
    observations = list(session.scalars(select(ElectionResultObservation)
        .where(ElectionResultObservation.release_id == release.id,
               ElectionResultObservation.year == year)
        .order_by(ElectionResultObservation.source_row_number)))
    if not observations:
        raise MaterializationError(f"No active observations for {year}")
    obs_ids = [o.id for o in observations]
    # These are published decisions, with one historic reference vintage per
    # election year. Select leaves of append-only supersession chains.
    release_ids = session.scalars(select(GeographicResolution.reference_release_id)
        .where(GeographicResolution.observation_id.in_(obs_ids)).distinct()).all()
    if reference_release_id is None:
        if len(release_ids) != 1:
            raise MaterializationError(f"{year}: select --reference-release-id explicitly; found {release_ids}")
        reference_release_id = release_ids[0]
    elif reference_release_id not in release_ids:
        raise MaterializationError("Selected geographic release has no decisions for this active MEDSL year")
    successor = select(GeographicResolution.supersedes_id).where(
        GeographicResolution.supersedes_id.is_not(None))
    geo_rows = session.execute(select(GeographicResolution, GeographicReference)
        .outerjoin(GeographicReference, GeographicResolution.reference_id == GeographicReference.id)
        .where(GeographicResolution.reference_release_id == reference_release_id,
               GeographicResolution.observation_id.in_(obs_ids),
               ~GeographicResolution.id.in_(successor))).all()
    geography = {}
    for geo, ref in geo_rows:
        if geo.observation_id in geography:
            raise MaterializationError("Multiple current geographic decisions for one observation")
        geography[geo.observation_id] = (geo, ref)
    return release, reference_release_id, observations, geography


def _plan(session: Session, year: int, reference_release_id: UUID | None):
    release, ref_release, observations, geography = _load_projection(session, year, reference_release_id)
    state_rows = session.scalars(select(Jurisdiction).where(Jurisdiction.level == "state")).all()
    state_groups = defaultdict(list)
    for st in state_rows:
        state_groups[st.state_code].append(st)
    duplicate_counts = Counter(o.logical_key for o in observations)
    # Interpret totalvotes only within the *same reporting mode and source
    # geographic label*, never sum the repeated value over candidate rows.
    totals = defaultdict(set)
    for o in observations:
        if o.total_votes is not None:
            totals[(o.state_code, o.county_fips, o.county_normalized,
                    o.mode_normalized)].add(o.total_votes)
    scope_counts = Counter()
    for o in observations:
        geo_ref = geography.get(o.id)
        if geo_ref and geo_ref[0].jurisdiction_id:
            scope_counts[(o.state_code, geo_ref[0].jurisdiction_id,
                          o.candidate_normalized, o.party_normalized,
                          o.candidate_kind, o.mode_normalized)] += 1
    accepted, rejected = [], []
    for o in observations:
        geo_ref = geography.get(o.id)
        geo, ref = geo_ref if geo_ref else (None, None)
        geo_status = geo.status if geo else None
        geo_level = ref.kind if ref else None
        scope = (o.state_code, geo.jurisdiction_id if geo else None,
                 o.candidate_normalized, o.party_normalized,
                 o.candidate_kind, o.mode_normalized)
        total_scope = (o.state_code, o.county_fips, o.county_normalized, o.mode_normalized)
        problem = eligibility(candidate_kind=o.candidate_kind,
            mode=o.mode_normalized, votes=o.candidate_votes,
            geo_status=geo_status, geo_level=geo_level,
            duplicate_key=duplicate_counts[o.logical_key] > 1,
            conflicting_scope=scope_counts[scope] > 1,
            conflicting_total=len(totals[total_scope]) > 1)
        if problem is None and (o.office_raw or "").strip().upper() != "US PRESIDENT":
            problem = "UNSUPPORTED_OFFICE"
        # All accepted observations must be backed by an exact matching
        # historic reference and jurisdiction, with one state scope.
        if problem is None and (geo is None or ref is None or
            geo.jurisdiction_id is None or ref.jurisdiction_id != geo.jurisdiction_id or
            ref.release_id != ref_release or ref.state_fips != o.state_fips or
            not ref.vintage_start <= year <= ref.vintage_end):
            problem = "GEOGRAPHY_REFERENCE_INCONSISTENT"
        if problem is None and len(state_groups.get(o.state_code, [])) != 1:
            problem = "STATE_CONTEST_UNRESOLVED"
        if problem is None and o.candidate_kind == "candidate" and not (o.candidate_normalized or "").strip():
            problem = "UNRESOLVED_CANDIDATE_LABEL"
        if problem:
            rejected.append((o, problem))
        else:
            accepted.append((o, geo, ref, state_groups[o.state_code][0]))
    # A county TOTAL is a meaningful unit only if the entire source reporting
    # unit is eligible and the sum of its vote categories reconciles with the
    # repeated reported total. Never publish a stranded single candidate after
    # other candidates were quarantined.
    raw_groups = defaultdict(list)
    for o in observations:
        if o.mode_normalized == "TOTAL":
            raw_groups[(o.state_code, o.county_fips, o.county_normalized,
                        o.mode_normalized)].append(o)
    problems_by_obs = {o.id: reason for o, reason in rejected}
    for group in raw_groups.values():
        group_problem = unit_reconciliation_issue(group, set(problems_by_obs))
        if group_problem:
            for o in group:
                problems_by_obs.setdefault(o.id, group_problem)
    if problems_by_obs:
        accepted = [item for item in accepted if item[0].id not in problems_by_obs]
        rejected = [(o, problems_by_obs[o.id]) for o in observations if o.id in problems_by_obs]
    fingerprint = _hash_projection(year, release, ref_release, observations, geography, state_groups)
    # The stored source sum is NOT an additive election total: it includes
    # aggregate categories and potentially overlapping voting modes.
    source_sum = sum(o.candidate_votes or 0 for o in observations)
    target_sum = sum(o.candidate_votes for o, _, _, _ in accepted)
    return dict(release=release, ref_release=ref_release, observations=observations,
        accepted=accepted, rejected=rejected, fingerprint=fingerprint,
        source_sum=source_sum, target_sum=target_sum)


def _chunks(items, n=500):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def materialize_medsl_year(session: Session, *, year: int, dry_run: bool = True,
                           allow_partial: bool = False,
                           reference_release_id: UUID | None = None) -> dict:
    """Caller owns transaction; mutations only if dry_run=False.

    Caller MUST run at REPEATABLE READ for source-selection consistency.
    Session is not committed here. A published pointer never references a
    partially inserted batch. Use a disposable DB for validation first.
    """
    if year not in SUPPORTED_YEARS:
        raise MaterializationError("Unsupported MEDSL presidential year")
    scope_key = f"medsl_presidential_county:{year}:county_total"
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), {"scope": scope_key})
    plan = _plan(session, year, reference_release_id)
    observed = len(plan["observations"])
    included = len(plan["accepted"])
    issues = Counter(code for _, code in plan["rejected"])
    if observed != included + sum(issues.values()):
        raise MaterializationError("Partition accounting does not reconcile")
    status = "PARTIAL" if issues else "COMPLETE"
    report = dict(year=year, scope=scope_key, dry_run=dry_run,
        release_id=str(plan["release"].id), reference_release_id=str(plan["ref_release"]),
        fingerprint=plan["fingerprint"], status=status,
        input_rows=observed, accepted_rows=included, excluded_rows=sum(issues.values()),
        issue_counts=dict(sorted(issues.items())),
        raw_votes_nonadditive=plan["source_sum"],
        eligible_canonical_votes=plan["target_sum"])
    if dry_run:
        report["action"] = "PREVIEW_ONLY"
        return report
    if status == "PARTIAL" and not allow_partial:
        raise MaterializationError("Incomplete county/mode coverage; pass --allow-partial explicitly to publish subset")
    if not included or not any(o.candidate_kind == "candidate" for o, _, _, _ in plan["accepted"]):
        raise MaterializationError("No eligible candidate observations; refusing empty publication")
    published = session.get(CanonicalPublication, scope_key)
    if published:
        prior = session.get(CanonicalResultBatch, published.batch_id)
        if prior and prior.fingerprint == plan["fingerprint"]:
            report.update(action="UNCHANGED", batch_id=str(prior.id))
            return report
    # A prior identical batch can be safely repointed (without changing rows).
    existing = session.scalar(select(CanonicalResultBatch).where(
        CanonicalResultBatch.scope_key == scope_key,
        CanonicalResultBatch.fingerprint == plan["fingerprint"]))
    if existing is not None:
        batch = existing
        action = "REACTIVATED"
    else:
        batch = CanonicalResultBatch(id=uuid4(), scope_key=scope_key,
            fingerprint=plan["fingerprint"], ruleset_version=RULESET,
            source_release_id=plan["release"].id, reference_release_id=plan["ref_release"],
            election_year=year, status=status, input_rows=observed,
            accepted_rows=included, excluded_rows=sum(issues.values()),
            raw_votes_nonadditive=plan["source_sum"], canonical_votes=plan["target_sum"],
            supersedes_id=published.batch_id if published else None)
        session.add(batch)
        session.flush()
        federal_office = elections.office(session, creation_key="us:federal:president",
            name="President of the United States", office_kind="executive")
        term = elections.office_term(session,
            creation_key=f"us:federal:president:term:{year + 1}",
            office_id=federal_office.id, start_date=date(year + 1, 1, 20),
            end_date=date(year + 5, 1, 20))
        contests = {}
        candidates = {}
        rows = []
        for obs, geo, ref, state in plan["accepted"]:
            if state.id not in contests:
                e = elections.election(session,
                    creation_key=f"medsl:president:general:{year}:{obs.state_code}",
                    election_date=date(year, *DATES[year]), election_type="general",
                    jurisdiction_id=state.id, election_cycle=year)
                c = elections.contest(session,
                    creation_key=f"medsl:president:contest:{year}:{obs.state_code}",
                    office_name="U.S. President", election_id=e.id,
                    jurisdiction_id=state.id, office_id=federal_office.id,
                    office_term_id=term.id)
                contests[state.id] = c
            c = contests[state.id]
            kind = vote_kind(obs.candidate_kind)
            candidate_id = None
            # MEDSL party labels and names are source-local tokens, not
            # authority for attaching a person or allocating ballot-line votes.
            if kind == "candidate_total":
                name = (obs.candidate_normalized or obs.candidate_raw or "").strip()
                key = elections.scoped_key("medsl-candidacy", year, obs.state_code,
                    str(plan["release"].id), name, obs.party_normalized)
                if key not in candidates:
                    candidate = elections.candidacy(session, creation_key=key,
                        contest_id=c.id, source_label=name, candidate_kind="candidate")
                    candidates[key] = candidate.id
                candidate_id = candidates[key]
            rows.append(dict(id=uuid4(), batch_id=batch.id, observation_id=obs.id,
                contest_id=c.id, jurisdiction_id=geo.jurisdiction_id,
                geographic_resolution_id=geo.id, candidacy_id=candidate_id,
                ballot_line_id=None, source_label=obs.candidate_raw or obs.candidate_normalized or "UNSPECIFIED",
                reporting_level=ref.kind, reporting_mode="TOTAL", vote_kind=kind,
                votes=obs.candidate_votes))
        for chunk in _chunks(rows):
            session.execute(pg_insert(CanonicalVoteReturn).values(chunk))
        issue_rows = [dict(id=uuid4(), batch_id=batch.id, observation_id=obs.id,
            code=code, detail=(f"Source row {obs.source_row_number}: {code}; "
                f"reported_mode={obs.mode_normalized!r}; "
                f"candidate_votes={obs.candidate_votes!r}; "
                f"candidate_kind={obs.candidate_kind!r}"))
            for obs, code in plan["rejected"]]
        for chunk in _chunks(issue_rows):
            session.execute(pg_insert(CanonicalMaterializationIssue).values(chunk))
        verified = session.execute(select(func.count(), func.coalesce(func.sum(CanonicalVoteReturn.votes),0))
            .where(CanonicalVoteReturn.batch_id == batch.id)).one()
        if verified != (included, plan["target_sum"]):
            raise MaterializationError("Persisted canonical totals differ from planned totals")
        action = "CREATED"
    values = dict(scope_key=scope_key, batch_id=batch.id, published_at=datetime.now(timezone.utc))
    session.execute(pg_insert(CanonicalPublication).values(**values)
        .on_conflict_do_update(index_elements=["scope_key"], set_={
            "batch_id": batch.id, "published_at": values["published_at"]}))
    report.update(action=action, batch_id=str(batch.id))
    return report


def candidate_totals(session: Session, *, batch_id: UUID, contest_id: UUID,
                     reporting_level: str, reporting_mode: str = "TOTAL") -> list[dict]:
    """Derive additive candidate votes; fail closed on overlapping representations.

    Only a single batch, contest, reporting level and mode is accepted. Aggregate
    categories and write-in buckets are intentionally not candidate totals.
    """
    rows = session.scalars(select(CanonicalVoteReturn).where(
        CanonicalVoteReturn.batch_id == batch_id,
        CanonicalVoteReturn.contest_id == contest_id,
        CanonicalVoteReturn.reporting_level == reporting_level,
        CanonicalVoteReturn.reporting_mode == reporting_mode)).all()
    from app.models.election import BallotLine
    from app.models.core import Candidacy
    keyed = defaultdict(list)
    for row in rows:
        if row.vote_kind not in {"ballot_line", "candidate_total"}:
            continue
        if row.candidacy_id is None:
            raise MaterializationError("Candidate vote has no candidacy")
        entity = session.get(Candidacy, row.candidacy_id)
        if entity is None or entity.contest_id != contest_id:
            raise MaterializationError("Vote candidacy belongs to a different contest")
        keyed[(row.jurisdiction_id, row.reporting_level, row.candidacy_id)].append(row)
    result = []
    for (jurisdiction_id, level, candidacy_id), group in keyed.items():
        kinds = {r.vote_kind for r in group}
        if len(kinds) > 1:
            raise MaterializationError("Candidate-total and ballot-line votes overlap")
        if kinds == {"candidate_total"} and len(group) != 1:
            raise MaterializationError("Duplicate candidate-total reporting grain")
        if kinds == {"ballot_line"}:
            ids = [r.ballot_line_id for r in group]
            if len(set(ids)) != len(ids):
                raise MaterializationError("Duplicate line votes in reporting grain")
            for row in group:
                line = session.get(BallotLine, row.ballot_line_id)
                if line is None or line.candidacy_id != candidacy_id:
                    raise MaterializationError("Ballot-line candidacy mismatch")
        result.append(dict(jurisdiction_id=str(jurisdiction_id),
            reporting_level=level, candidacy_id=str(candidacy_id),
            votes=sum(row.votes for row in group), basis=next(iter(kinds))))
    return sorted(result, key=lambda x: (x["jurisdiction_id"], x["candidacy_id"]))
