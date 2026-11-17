"""Conservative Senate publication using existing immutable canonical returns."""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.core import DataSource, Jurisdiction, PoliticalParty
from app.models.election import CanonicalMaterializationIssue, CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn
from app.models.geography import GeographicReference, GeographicResolution
from app.models.ingestion import ElectionResultObservation as Observation, SourceActiveYear, SourceRelease
from app.models.senate_returns import SenateContest, SenateContestReconciliation, SenateReturnDetail, SenateSeat
from app.services import elections
from app.services.canonical_results import MaterializationError
from ingestion.loader import _chunks, _hash
from ingestion.senate_returns import CLASS_STATES, CLASS_URLS, NON_VOTES, RULESET, YEARS, candidate_kind, regular_class, scope_rule


def scope(year: int) -> str:
    return f"medsl_senate:{year}:state_total"


def _reference(session: Session, year: int, release_id: UUID | None) -> tuple[SourceRelease, dict]:
    query = select(SourceRelease).join(DataSource).join(GeographicReference).where(
        DataSource.name == "census_state_county_georef", GeographicReference.kind == "state",
        GeographicReference.vintage_start <= year, GeographicReference.vintage_end >= year).distinct()
    if release_id:
        query = query.where(SourceRelease.id == release_id)
    releases = list(session.scalars(query))
    if len(releases) != 1:
        raise MaterializationError("Load a year-compatible Census state reference; select --reference-release-id if ambiguous")
    release = releases[0]
    refs = {}
    for ref, jurisdiction in session.execute(select(GeographicReference, Jurisdiction).join(Jurisdiction).where(
            GeographicReference.release_id == release.id, GeographicReference.kind == "state")):
        if (jurisdiction.level != "state" or ref.geoid != ref.state_fips or
                not ref.vintage_start <= year <= ref.vintage_end):
            raise MaterializationError("Incompatible Senate state reference")
        if jurisdiction.state_code in refs:
            raise MaterializationError("Ambiguous Senate state reference")
        refs[jurisdiction.state_code] = ref
    return release, refs


def plan(session: Session, *, year: int, reference_release_id: UUID | None = None) -> dict:
    if year not in YEARS:
        raise MaterializationError(f"Unsupported Senate year: {year}")
    source = session.scalar(select(DataSource).where(DataSource.name == "medsl_senate"))
    active = session.get(SourceActiveYear, (source.id, year)) if source else None
    if active is None:
        raise MaterializationError(f"Load medsl_senate {year} before publication")
    release = session.get(SourceRelease, active.release_id)
    if release.source_id != source.id:
        raise MaterializationError("Senate active release has incorrect source")
    observations = list(session.scalars(select(Observation).where(Observation.release_id == release.id,
        Observation.year == year).order_by(Observation.source_row_number)))
    details = {d.observation_id: d for d in session.scalars(select(SenateReturnDetail).where(
        SenateReturnDetail.observation_id.in_([o.id for o in observations])))}
    if not observations or len(details) != len(observations):
        raise MaterializationError("Senate observations are empty or lack source details")
    reference_release, references = _reference(session, year, reference_release_id)
    # Reclassify through the pinned canonical rules. Older immutable ingestion
    # hints must not turn administrative labels or anonymous buckets into people.
    kinds = {o.id: candidate_kind(o.candidate_normalized or "", details[o.id].writein) for o in observations}
    groups = defaultdict(list)
    for obs in observations:
        d = details[obs.id]
        groups[(obs.state_code, d.stage, d.special)].append(obs)
    duplicates = Counter(o.logical_key for o in observations)
    problems, specs, checks = {}, {}, []
    for key, rows in sorted(groups.items()):
        state, stage, special = key
        spec = scope_rule(year, state, stage, special)
        specs[key] = spec
        ref = references.get(state)
        blockers = set()
        if spec["issue"]:
            blockers.add(spec["issue"])
        if not ref or any(o.state_fips != ref.geoid for o in rows):
            blockers.add("STATE_NOT_IN_REFERENCE")
        for obs in rows:
            d = details[obs.id]
            code = None
            if obs.candidate_normalized in NON_VOTES:
                code = "NON_VOTE_CATEGORY"
            elif duplicates[obs.logical_key] > 1:
                code = "DUPLICATE_LOGICAL_KEY"
            elif obs.mode_normalized != "TOTAL":
                code = "UNSUPPORTED_VOTING_MODE"
            elif d.unofficial:
                code = "UNOFFICIAL_RESULT"
            elif obs.candidate_votes is None or obs.total_votes is None:
                code = "MISSING_VOTES"
            elif kinds[obs.id] == "unresolved":
                code = "UNRESOLVED_CANDIDATE_LABEL"
            if code:
                problems[obs.id] = code
                if code != "NON_VOTE_CATEGORY":
                    blockers.add(code)
        # The codebook defines party lines as additive. Repeated labels on the
        # same party/write-in line are ambiguous, even if the vote values differ.
        lines = Counter((o.candidate_normalized, o.party_normalized, details[o.id].writein)
                        for o in rows if kinds[o.id] == "candidate")
        if any(n > 1 for n in lines.values()):
            blockers.add("DUPLICATE_CANDIDATE_LINE")
        totals = {o.total_votes for o in rows}
        reported = next(iter(totals)) if len(totals) == 1 and None not in totals else None
        raw_sum = sum(o.candidate_votes or 0 for o in rows)
        vote_sum = sum(o.candidate_votes or 0 for o in rows if o.candidate_normalized not in NON_VOTES)
        basis = "ALL_SOURCE_CATEGORIES" if raw_sum == reported else "VOTE_CATEGORIES_ONLY" if vote_sum == reported else None
        if reported is None:
            blockers.add("MISSING_OR_CONFLICTING_TOTAL")
        elif reported == 1:
            blockers.add("UNOPPOSED_VOTE_PLACEHOLDER")
        elif basis is None:
            blockers.add("REPORTED_TOTAL_MISMATCH")
        if blockers:
            for obs in rows:
                problems.setdefault(obs.id, sorted(blockers)[0])
        checks.append(dict(source_key=f"{state}:{stage}:{special}", checks_json=dict(
            state_code=state, source_stage=stage, special=special, scope=spec,
            status="EXCLUDED" if blockers else "RECONCILED", source_rows=len(rows),
            reported_total=reported, source_category_sum=raw_sum, vote_category_sum=vote_sum,
            canonical_votes=0 if blockers else vote_sum, basis=basis, issues=sorted(blockers),
            source_row_numbers=[o.source_row_number for o in rows],
            flags=["SOURCE_REPORTED_RCV_COUNTS"] if state == "AK" and year >= 2022 else [])))
    eligible = [o for o in observations if o.id not in problems]
    # Existing decisions, including supersession chains, must be checked before
    # reusing an unchanged batch. Publication cannot override geography review.
    by_id = {o.id: o for o in eligible}
    for geo in session.scalars(select(GeographicResolution).where(
            GeographicResolution.observation_id.in_(by_id),
            GeographicResolution.reference_release_id == reference_release.id)):
        ref = references[by_id[geo.observation_id].state_code]
        if (geo.reference_id != ref.id or geo.jurisdiction_id != ref.jurisdiction_id or
                geo.status != "RESOLVED" or geo.supersedes_id):
            raise MaterializationError("Senate geography conflicts with existing decision")
    expected = CLASS_STATES[regular_class(year)] if year % 2 == 0 else frozenset()
    missing = sorted(expected - {st for st, _, special in groups if not special})
    fingerprint = _hash([RULESET, str(release.id), release.sha256, str(reference_release.id), reference_release.sha256,
        [(str(o.id), o.row_sha256, o.logical_key, o.candidate_votes, o.total_votes,
          o.candidate_normalized, kinds[o.id], o.party_normalized, o.mode_normalized,
          details[o.id].stage, details[o.id].special, details[o.id].writein, details[o.id].unofficial) for o in observations],
        [(str(r.id), str(r.jurisdiction_id), st, r.geoid) for st, r in sorted(references.items())], checks, missing])
    report = dict(scope=scope(year), year=year, ruleset=RULESET, fingerprint=fingerprint,
        source_release_id=str(release.id), reference_release_id=str(reference_release.id),
        status="PARTIAL" if problems or missing else "COMPLETE", input_rows=len(observations),
        accepted_rows=len(eligible), excluded_rows=len(problems), issue_counts=dict(sorted(Counter(problems.values()).items())),
        missing_regular_states=missing, source_contests=len(groups),
        modeled_contests=sum(not spec["issue"] and key[0] in references for key, spec in specs.items()),
        reconciled_contests=sum(c["checks_json"]["status"] == "RECONCILED" for c in checks),
        raw_votes_nonadditive=sum(o.candidate_votes or 0 for o in observations),
        canonical_votes=sum(o.candidate_votes for o in eligible), reconciliations=checks)
    return dict(report=report, release=release, reference_release=reference_release,
                references=references, groups=groups, details=details, kinds=kinds, specs=specs, problems=problems)


def publish(session: Session, *, year: int, dry_run: bool = True, allow_partial: bool = False,
            reference_release_id: UUID | None = None) -> dict:
    if session.scalar(text("SHOW transaction_isolation")) != "repeatable read":
        raise MaterializationError("Senate publication requires REPEATABLE READ")
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), dict(scope=scope(year)))
    selected = plan(session, year=year, reference_release_id=reference_release_id)
    report = selected["report"]
    if dry_run:
        return dict(report, action="PREVIEW_ONLY", dry_run=True)
    if report["status"] == "PARTIAL" and not allow_partial:
        raise MaterializationError("Senate coverage has exclusions; use --allow-partial after reviewing preview")
    if not report["modeled_contests"]:
        raise MaterializationError("No supported Senate contests; refusing empty publication")
    pointer = session.get(CanonicalPublication, scope(year))
    batch = session.scalar(select(CanonicalResultBatch).where(CanonicalResultBatch.scope_key == scope(year),
        CanonicalResultBatch.fingerprint == report["fingerprint"]))
    action = "UNCHANGED" if batch and pointer and pointer.batch_id == batch.id else "REACTIVATED" if batch else "CREATED"
    if batch is None:
        batch = CanonicalResultBatch(id=uuid4(), scope_key=scope(year), fingerprint=report["fingerprint"],
            ruleset_version=RULESET, source_release_id=selected["release"].id,
            reference_release_id=selected["reference_release"].id, election_year=year,
            status=report["status"], input_rows=report["input_rows"], accepted_rows=report["accepted_rows"],
            excluded_rows=report["excluded_rows"], raw_votes_nonadditive=report["raw_votes_nonadditive"],
            canonical_votes=report["canonical_votes"], supersedes_id=pointer.batch_id if pointer else None)
        session.add(batch)
        session.flush()
        returns, issues = [], []
        parties = dict(session.execute(select(PoliticalParty.name, PoliticalParty.id)).all())
        for key, rows in sorted(selected["groups"].items()):
            spec = selected["specs"][key]
            ref = selected["references"].get(key[0])
            contest = None
            if not spec["issue"] and ref:
                seat_class = spec["seat_class"]
                office = elections.office(session, creation_key=f"us:senate:{key[0]}:class:{seat_class}",
                    name="U.S. Senate", office_kind="legislative", jurisdiction_id=ref.jurisdiction_id)
                seat = session.get(SenateSeat, office.id)
                if seat is None:
                    session.add(SenateSeat(office_id=office.id, state_code=key[0], seat_class=seat_class,
                                          evidence_url=CLASS_URLS[seat_class]))
                    session.flush()
                elif (seat.state_code, seat.seat_class) != (key[0], seat_class):
                    raise MaterializationError("Existing Senate seat conflicts with source scope")
                event_key = f"medsl:senate:{key[0]}:{seat_class}:{spec['election_date']}:{spec['stage']}"
                event = elections.election(session, creation_key=event_key, election_date=date.fromisoformat(spec["election_date"]),
                    election_type=spec["stage"], election_cycle=spec["cycle"], jurisdiction_id=ref.jurisdiction_id)
                contest = elections.contest(session, creation_key=event_key + ":contest", office_name="U.S. Senate",
                    election_id=event.id, jurisdiction_id=ref.jurisdiction_id, office_id=office.id)
                evidence = dict(source_year=year, source_stage=key[1], special=key[2], rule=spec, ruleset=RULESET)
                existing = session.get(SenateContest, contest.id)
                if existing is None:
                    session.add(SenateContest(contest_id=contest.id, scope_evidence_json=evidence))
                elif _hash(existing.scope_evidence_json) != _hash(evidence):
                    raise MaterializationError("Existing Senate contest has conflicting scope evidence")
            candidates = {}
            for obs in rows:
                detail = selected["details"][obs.id]
                candidate, line = None, None
                if contest and selected["kinds"][obs.id] == "candidate":
                    candidate_key = elections.scoped_key("medsl-senate-candidacy", str(selected["release"].id),
                                                         str(contest.id), obs.candidate_normalized)
                    if candidate_key not in candidates:
                        candidates[candidate_key] = elections.candidacy(session, creation_key=candidate_key,
                            contest_id=contest.id, source_label=obs.candidate_normalized)
                    candidate = candidates[candidate_key]
                    label = obs.party_normalized
                    party_id = None
                    if label and label not in {"NA", "N/A", "NULL"}:
                        if label not in parties:
                            session.execute(pg_insert(PoliticalParty).values(id=uuid4(), name=label)
                                            .on_conflict_do_nothing(index_elements=["name"]))
                            parties[label] = session.scalar(select(PoliticalParty.id).where(PoliticalParty.name == label))
                        party_id = parties[label]
                    line = elections.ballot_line(session,
                        creation_key=elections.scoped_key("medsl-senate-line", candidate_key, label, detail.writein),
                        candidacy_id=candidate.id, line_label=obs.party_raw or "UNSPECIFIED",
                        line_kind="write_in" if detail.writein else "party" if party_id else "other", party_id=party_id)
                if obs.id in selected["problems"]:
                    issues.append(dict(id=uuid4(), batch_id=batch.id, observation_id=obs.id,
                        code=selected["problems"][obs.id], detail=f"Source row {obs.source_row_number}; scope {key}"))
                    continue
                geo = session.scalar(select(GeographicResolution).where(GeographicResolution.observation_id == obs.id,
                    GeographicResolution.reference_release_id == ref.release_id))
                if geo is None:
                    geo = GeographicResolution(id=uuid4(), observation_id=obs.id, reference_release_id=ref.release_id,
                        reference_id=ref.id, jurisdiction_id=ref.jurisdiction_id, status="RESOLVED",
                        method="EXACT_STATE_FIPS", reason="Source state abbreviation and FIPS match Census state reference",
                        evidence_json=dict(state_code=obs.state_code, state_fips=obs.state_fips),
                        ruleset_version=RULESET, decision_sha256=_hash([str(obs.id), obs.row_sha256, str(ref.id), RULESET]))
                    session.add(geo)
                    session.flush()
                returns.append(dict(id=uuid4(), batch_id=batch.id, observation_id=obs.id, contest_id=contest.id,
                    jurisdiction_id=ref.jurisdiction_id, geographic_resolution_id=geo.id,
                    candidacy_id=candidate.id if candidate else None, ballot_line_id=line.id if line else None,
                    source_label=obs.candidate_raw or "UNIDENTIFIED WRITE-IN", reporting_level="state", reporting_mode="TOTAL",
                    vote_kind="ballot_line" if line else selected["kinds"][obs.id], votes=obs.candidate_votes))
        for model, rows in ((CanonicalVoteReturn, returns), (CanonicalMaterializationIssue, issues),
                (SenateContestReconciliation, [dict(batch_id=batch.id, **c) for c in report["reconciliations"]])):
            for chunk in _chunks(rows):
                session.execute(pg_insert(model).values(chunk))
        count, votes = session.execute(select(func.count(), func.coalesce(func.sum(CanonicalVoteReturn.votes), 0))
            .where(CanonicalVoteReturn.batch_id == batch.id)).one()
        if (count, votes) != (report["accepted_rows"], report["canonical_votes"]):
            raise MaterializationError("Persisted Senate counts differ from reconciliation")
    if action != "UNCHANGED":
        now = datetime.now(timezone.utc)
        session.execute(pg_insert(CanonicalPublication).values(scope_key=scope(year), batch_id=batch.id, published_at=now)
            .on_conflict_do_update(index_elements=["scope_key"], set_={"batch_id":batch.id, "published_at":now}))
    return dict(report, action=action, batch_id=str(batch.id), dry_run=False)
