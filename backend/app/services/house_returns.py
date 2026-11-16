"""Publish reconciled source-native House ballot lines through existing result APIs.

The caller owns a REPEATABLE READ transaction. No source rows are mutated.
Names are joined only within a source release and contest, never across people.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.core import DataSource, Jurisdiction, PoliticalParty
from app.models.election import CanonicalMaterializationIssue, CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn
from app.models.geography import GeographicReference, GeographicResolution
from app.models.house_returns import HouseDistrictReconciliation, HouseReturnDetail
from app.models.ingestion import ElectionResultObservation as Observation, SourceActiveYear, SourceRelease
from app.services import elections
from app.services.canonical_results import MaterializationError
from ingestion.house_returns import NON_VOTES, RULESET
from ingestion.loader import _chunks, _hash

SCOPE = "medsl_house:2024:district_total"


def plan(session: Session, *, reference_release_id: UUID | None = None) -> dict:
    source = session.scalar(select(DataSource).where(DataSource.name == "medsl_house"))
    active = session.get(SourceActiveYear, (source.id, 2024)) if source else None
    if active is None:
        raise MaterializationError("Load medsl_house 2024 before materialization")
    release = session.get(SourceRelease, active.release_id)
    if release.source_id != source.id:
        raise MaterializationError("House active release has incorrect source")
    observations = list(session.scalars(select(Observation).where(Observation.release_id == release.id,
        Observation.year == 2024).order_by(Observation.source_row_number)))
    observations_by_id = {o.id:o for o in observations}
    details = {d.observation_id:d for d in session.scalars(select(HouseReturnDetail).where(
        HouseReturnDetail.observation_id.in_([o.id for o in observations])))}
    if not observations or len(details) != len(observations):
        raise MaterializationError("House observations are empty or lack source details")
    candidates = list(session.scalars(select(SourceRelease).join(DataSource).where(
        DataSource.name == "census_congressional_districts", SourceRelease.version == "2024-119")))
    candidates = [r for r in candidates if reference_release_id is None or r.id == reference_release_id]
    if len(candidates) != 1:
        raise MaterializationError("Load Census 2024 districts; select --reference-release-id if multiple releases exist")
    reference_release = candidates[0]
    reference_rows = session.execute(select(GeographicReference, Jurisdiction).join(Jurisdiction,
        GeographicReference.jurisdiction_id == Jurisdiction.id).where(
        GeographicReference.release_id == reference_release.id)).all()
    references = {}
    for ref, jurisdiction in reference_rows:
        if (ref.kind != "congressional_district" or jurisdiction.level != ref.kind or
            ref.vintage_start != 2024 or ref.vintage_end != 2024 or
            jurisdiction.state_code is None or ref.geoid[:2] != ref.state_fips):
            raise MaterializationError("Incompatible congressional reference kind/vintage/identity")
        references[ref.geoid] = ref
    if not references:
        raise MaterializationError("Census release has no district references")
    groups = defaultdict(list)
    for obs in observations:
        detail = details[obs.id]
        # MEDSL uses 0 for DC; Census uses 98 for nonvoting delegates.
        code = "98" if obs.state_code == "DC" and detail.district_code == "00" else detail.district_code
        groups[obs.state_fips + code].append(obs)
    duplicate_keys = Counter(o.logical_key for o in observations)
    problems, reconciliations = {}, []
    for geoid, group in sorted(groups.items()):
        ref = references.get(geoid)
        name_groups = defaultdict(list)
        for obs in group:
            detail = details[obs.id]
            code = None
            if ref is None or ref.state_fips != obs.state_fips:
                code = "DISTRICT_NOT_IN_REFERENCE"
            elif session.get(Jurisdiction, ref.jurisdiction_id).state_code != obs.state_code:
                code = "DISTRICT_STATE_MISMATCH"
            elif detail.stage != "GEN" or detail.special or detail.runoff or obs.office_raw.strip().upper() != "US HOUSE":
                code = "UNSUPPORTED_ELECTION_SCOPE"
            elif duplicate_keys[obs.logical_key] > 1:
                code = "DUPLICATE_LOGICAL_KEY"
            elif obs.candidate_normalized in NON_VOTES:
                code = "NON_VOTE_CATEGORY"
            elif obs.mode_normalized != "TOTAL":
                code = "UNSUPPORTED_VOTING_MODE"
            elif detail.unofficial:
                code = "UNOFFICIAL_RESULT"
            elif obs.candidate_votes is None or obs.total_votes is None:
                code = "MISSING_VOTES"
            elif obs.candidate_kind == "unresolved":
                code = "UNRESOLVED_CANDIDATE_LABEL"
            if code:
                problems[obs.id] = code
            if obs.candidate_kind == "candidate":
                name_groups[obs.candidate_normalized].append(obs)
        for rows in name_groups.values():
            if len(rows) > 1 and not any(details[o.id].fusion_ticket for o in rows):
                for o in rows:
                    problems.setdefault(o.id, "UNVERIFIED_FUSION")
        non_votes = [o for o in group if o.candidate_normalized in NON_VOTES]
        vote_rows = [o for o in group if o not in non_votes]
        totals = {o.total_votes for o in group}
        reported = next(iter(totals)) if len(totals) == 1 and None not in totals else None
        raw_sum = sum(o.candidate_votes or 0 for o in group)
        valid_sum = sum(o.candidate_votes or 0 for o in vote_rows)
        # Some source totals include administrative ballot categories (e.g. DC),
        # others exclude them (e.g. NY). Record which equality held explicitly.
        basis = ("ALL_SOURCE_CATEGORIES" if reported == raw_sum else
                 "VOTE_CATEGORIES_ONLY" if reported == valid_sum else None)
        blockers = {problems[o.id] for o in group if o.id in problems} - {"NON_VOTE_CATEGORY"}
        if reported is None:
            blockers.add("MISSING_OR_CONFLICTING_TOTAL")
        elif basis is None:
            blockers.add("REPORTED_TOTAL_MISMATCH")
        if blockers:
            for o in vote_rows:
                problems.setdefault(o.id, sorted(blockers)[0] if basis is None else "REPORTING_UNIT_INCOMPLETE")
        eligible_sum = sum(o.candidate_votes for o in vote_rows if o.id not in problems)
        reconciliations.append(dict(geoid=geoid, source_rows=len(group), reported_total=reported,
            source_category_sum=raw_sum, canonical_votes=eligible_sum,
            status="EXCLUDED" if blockers else "RECONCILED",
            checks_json=dict(basis=basis, vote_category_sum=valid_sum,
                non_vote_category_sum=raw_sum-valid_sum, issues=sorted(blockers),
                source_row_numbers=[o.source_row_number for o in group],
                flags=sorted({flag for o in group for flag in details[o.id].flags_json}))))
    missing = sorted(set(references) - set(groups))
    # Validate prior decisions even on an UNCHANGED rerun. An external
    # geography review must never be bypassed by reusing a cached batch.
    prior_geography = session.scalars(select(GeographicResolution).where(
        GeographicResolution.observation_id.in_([o.id for o in observations if o.id not in problems]),
        GeographicResolution.reference_release_id == reference_release.id)).all()
    for geo in prior_geography:
        obs = observations_by_id[geo.observation_id]
        detail = details[obs.id]
        code = "98" if obs.state_code == "DC" and detail.district_code == "00" else detail.district_code
        ref = references[obs.state_fips + code]
        if geo.reference_id != ref.id or geo.jurisdiction_id != ref.jurisdiction_id or geo.status != "RESOLVED" or geo.supersedes_id:
            raise MaterializationError("House geography conflicts with existing published decision")
    fingerprint = _hash([RULESET, str(release.id), release.sha256, str(reference_release.id),
        reference_release.sha256,
        [(str(o.id), o.row_sha256, o.logical_key, o.candidate_votes, o.total_votes,
          o.candidate_normalized, o.party_normalized, o.candidate_kind, o.mode_normalized,
          details[o.id].district_code, details[o.id].stage,
          *[getattr(details[o.id], f) for f in ("special", "runoff", "writein", "unofficial", "fusion_ticket")],
          details[o.id].flags_json) for o in observations],
        [(r.geoid, str(r.id), str(r.jurisdiction_id)) for r in sorted(references.values(), key=lambda r:r.geoid)]])
    report = dict(scope=SCOPE, ruleset=RULESET, source_release_id=str(release.id),
        reference_release_id=str(reference_release.id), fingerprint=fingerprint,
        status="PARTIAL" if problems or missing else "COMPLETE", input_rows=len(observations),
        accepted_rows=len(observations)-len(problems), excluded_rows=len(problems),
        issue_counts=dict(sorted(Counter(problems.values()).items())), missing_district_geoids=missing,
        source_districts=len(groups), reconciled_districts=sum(r["status"] == "RECONCILED" for r in reconciliations),
        raw_votes_nonadditive=sum(o.candidate_votes or 0 for o in observations),
        canonical_votes=sum(r["canonical_votes"] for r in reconciliations), reconciliations=reconciliations)
    return dict(report=report, observations=observations, details=details, groups=groups,
                references=references, problems=problems, release=release, reference_release=reference_release)


def publish(session: Session, *, dry_run: bool = True, allow_partial: bool = False,
            reference_release_id: UUID | None = None) -> dict:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), dict(scope=SCOPE))
    selected = plan(session, reference_release_id=reference_release_id)
    report = selected["report"]
    if dry_run:
        return dict(report, action="PREVIEW_ONLY", dry_run=True)
    if report["status"] == "PARTIAL" and not allow_partial:
        raise MaterializationError("House coverage has exclusions; use --allow-partial after reviewing the preview")
    if not report["accepted_rows"]:
        raise MaterializationError("No eligible House returns; refusing empty publication")
    pointer = session.get(CanonicalPublication, SCOPE)
    batch = session.scalar(select(CanonicalResultBatch).where(CanonicalResultBatch.scope_key == SCOPE,
        CanonicalResultBatch.fingerprint == report["fingerprint"]))
    action = "UNCHANGED" if batch and pointer and pointer.batch_id == batch.id else "REACTIVATED" if batch else "CREATED"
    if batch is None:
        batch = CanonicalResultBatch(id=uuid4(), scope_key=SCOPE, fingerprint=report["fingerprint"],
            ruleset_version=RULESET, source_release_id=selected["release"].id,
            reference_release_id=selected["reference_release"].id, election_year=2024,
            status=report["status"], input_rows=report["input_rows"], accepted_rows=report["accepted_rows"],
            excluded_rows=report["excluded_rows"], raw_votes_nonadditive=report["raw_votes_nonadditive"],
            canonical_votes=report["canonical_votes"], supersedes_id=pointer.batch_id if pointer else None)
        session.add(batch)
        session.flush()
        returns, issues = [], []
        parties = dict(session.execute(select(PoliticalParty.name, PoliticalParty.id)).all())
        for geoid, observations in sorted(selected["groups"].items()):
            ref = selected["references"].get(geoid)
            contest = None
            candidates = {}
            if ref:
                office = elections.office(session, creation_key=f"us:house:119:{geoid}",
                    name="U.S. House", office_kind="legislative", jurisdiction_id=ref.jurisdiction_id)
                term = elections.office_term(session, creation_key=f"us:house:119:{geoid}:term",
                    office_id=office.id, start_date=date(2025, 1, 3), end_date=date(2027, 1, 3))
                event = elections.election(session, creation_key=f"medsl:house:general:2024:{geoid}",
                    election_date=date(2024, 11, 5), election_type="general", election_cycle=2024,
                    jurisdiction_id=ref.jurisdiction_id)
                contest = elections.contest(session, creation_key=f"medsl:house:contest:2024:{geoid}",
                    office_name="U.S. House", election_id=event.id, jurisdiction_id=ref.jurisdiction_id,
                    office_id=office.id, office_term_id=term.id)
            for obs in observations:
                detail = selected["details"][obs.id]
                line = None
                candidate = None
                if contest and obs.candidate_kind == "candidate":
                    key = elections.scoped_key("medsl-house-candidacy", str(selected["release"].id), geoid,
                                               obs.candidate_normalized)
                    if key not in candidates:
                        candidates[key] = elections.candidacy(session, creation_key=key, contest_id=contest.id,
                            source_label=obs.candidate_normalized)
                    candidate = candidates[key]
                    label = obs.party_normalized
                    party_id = None
                    if label and label not in {"NA", "N/A", "NULL"}:
                        if label not in parties:
                            session.execute(pg_insert(PoliticalParty).values(id=uuid4(), name=label)
                                .on_conflict_do_nothing(index_elements=["name"]))
                            parties[label] = session.scalar(select(PoliticalParty.id).where(PoliticalParty.name == label))
                        party_id = parties[label]
                    line = elections.ballot_line(session,
                        creation_key=elections.scoped_key("medsl-house-line", key, label, detail.writein),
                        candidacy_id=candidate.id, line_label=obs.party_raw or "UNSPECIFIED",
                        line_kind="write_in" if detail.writein else "party" if party_id else "other", party_id=party_id)
                if obs.id in selected["problems"]:
                    issues.append(dict(id=uuid4(), batch_id=batch.id, observation_id=obs.id,
                        code=selected["problems"][obs.id], detail=f"Source row {obs.source_row_number}; district {geoid}; flags={detail.flags_json}"))
                    continue
                # New House decisions are exact Census identifier matches. Never
                # revise an existing published decision or supersession chain here.
                geo = session.scalar(select(GeographicResolution).where(
                    GeographicResolution.observation_id == obs.id,
                    GeographicResolution.reference_release_id == ref.release_id,
                    GeographicResolution.supersedes_id.is_(None)))
                if geo is None:
                    geo = GeographicResolution(id=uuid4(), observation_id=obs.id,
                        reference_release_id=ref.release_id, reference_id=ref.id, jurisdiction_id=ref.jurisdiction_id,
                        status="RESOLVED", method="EXACT_CENSUS_CONGRESSIONAL_GEOID",
                        reason="2024 election matched to Census 119th Congress district identifier",
                        evidence_json=dict(source_district=detail.district_code, census_geoid=geoid,
                            dc_delegate_mapping=obs.state_code == "DC"), ruleset_version=RULESET,
                        decision_sha256=_hash([str(obs.id), obs.row_sha256, str(ref.id), RULESET]))
                    session.add(geo)
                    session.flush()
                elif (geo.reference_id != ref.id or geo.jurisdiction_id != ref.jurisdiction_id or geo.status != "RESOLVED" or
                      session.scalar(select(GeographicResolution.id).where(GeographicResolution.supersedes_id == geo.id))):
                    raise MaterializationError("House geography conflicts with existing published decision")
                returns.append(dict(id=uuid4(), batch_id=batch.id, observation_id=obs.id, contest_id=contest.id,
                    jurisdiction_id=ref.jurisdiction_id, geographic_resolution_id=geo.id,
                    candidacy_id=candidate.id if candidate else None, ballot_line_id=line.id if line else None,
                    source_label=obs.candidate_raw, reporting_level="congressional_district", reporting_mode="TOTAL",
                    vote_kind="ballot_line" if line else obs.candidate_kind, votes=obs.candidate_votes))
        for model, rows in ((CanonicalVoteReturn, returns), (CanonicalMaterializationIssue, issues),
                             (HouseDistrictReconciliation, [dict(batch_id=batch.id, **r) for r in report["reconciliations"]])):
            for chunk in _chunks(rows):
                session.execute(pg_insert(model).values(chunk))
        count, votes = session.execute(select(func.count(), func.coalesce(func.sum(CanonicalVoteReturn.votes), 0))
            .where(CanonicalVoteReturn.batch_id == batch.id)).one()
        if (count, votes) != (report["accepted_rows"], report["canonical_votes"]):
            raise MaterializationError("Persisted House counts differ from reconciliation")
    if action != "UNCHANGED":
        values = dict(scope_key=SCOPE, batch_id=batch.id, published_at=datetime.now(timezone.utc))
        session.execute(pg_insert(CanonicalPublication).values(**values).on_conflict_do_update(
            index_elements=["scope_key"], set_={"batch_id":batch.id, "published_at":values["published_at"]}))
    return dict(report, action=action, batch_id=str(batch.id), dry_run=False)
