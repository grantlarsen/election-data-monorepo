"""Paginated discovery and results; no raw observations or unpublished snapshots.

SQL pages candidate/reporting-unit keys before loading returns. Vote arithmetic
and overlap checks remain in canonical_results.candidate_totals. Publication
coverage describes the whole batch and never asserts a selected county is verified.
"""
from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import Select, case, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.api.election_schemas import ElectionFilters, ResultFilters
from app.models.core import Candidacy, Contest, DataSource, Election, Jurisdiction
from app.models.county_corrections import CountyCorrectionBatch
from app.models.election import (
    BallotLine, CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn, Office,
)
from app.models.geography import GeographicReference, GeographicResolution
from app.models.ingestion import SourceRelease
from app.models.state_results import StateResultBatch, StateResultPublication, StateVoteReturn
from app.models.senate_returns import SenateSeat
from app.services.canonical_results import MaterializationError, candidate_totals, state_totals


def _geography(item: Jurisdiction) -> dict:
    return dict(id=item.id, name=item.name, level=item.level, state_code=item.state_code)


def _source(session: Session, release_id: UUID) -> dict:
    release = session.get(SourceRelease, release_id)
    source = session.get(DataSource, release.source_id)
    return dict(release_id=release.id, name=source.name, version=release.version,
                sha256=release.sha256, url=release.download_url, retrieved_at=release.retrieved_at)


def _publication(session: Session, batch: CanonicalResultBatch | StateResultBatch,
                 pointer: CanonicalPublication | StateResultPublication) -> dict:
    result = dict(batch_id=batch.id, scope_key=batch.scope_key, published_at=pointer.published_at,
                  source=_source(session, batch.source_release_id),
                  status=batch.status if isinstance(batch, CanonicalResultBatch) else "COMPLETE")
    if isinstance(batch, CanonicalResultBatch):
        grains = session.execute(select(CanonicalVoteReturn.reporting_level, CanonicalVoteReturn.reporting_mode)
            .where(CanonicalVoteReturn.batch_id == batch.id).distinct()).all()
        result.update(reference_release_id=batch.reference_release_id,
                      reporting_levels=sorted({level for level, _ in grains}),
                      reporting_modes=sorted({mode for _, mode in grains}),
                      correction_batch_id=batch.correction_batch_id,
                      input_rows=batch.input_rows, accepted_rows=batch.accepted_rows,
                      excluded_rows=batch.excluded_rows)
        if batch.correction_batch_id:
            correction = session.get(CountyCorrectionBatch, batch.correction_batch_id)
            result["correction_source"] = _source(session, correction.source_release_id)
    else:
        result.update(reporting_levels=["state"], reporting_modes=["TOTAL"])
    return result


def _page(items: list, total: int, filters: ElectionFilters, *, results: bool = False, **extra) -> dict:
    return dict(items=items, total=total, limit=filters.limit, offset=filters.offset,
                has_more=filters.offset + len(items) < total,
                availability="available" if total else (
                    "no_matching_published_results" if results else "no_matching_data"), **extra)


def _party_candidates(party_id: UUID) -> Select:
    return select(Candidacy.id).where(or_(
        Candidacy.party_id == party_id,
        Candidacy.id.in_(select(BallotLine.candidacy_id).where(BallotLine.party_id == party_id)),
    ))


def _event_conditions(filters: ElectionFilters) -> list:
    conditions = []
    if filters.year is not None:
        conditions.extend([Election.election_date >= date(filters.year, 1, 1),
                           Election.election_date < date(filters.year + 1, 1, 1)])
    if filters.stage is not None:
        conditions.append(Election.election_type == filters.stage)
    if filters.election_id is not None:
        conditions.append(Election.id == filters.election_id)
    return conditions


def _contest_query(filters: ElectionFilters, *, result_geography: bool = False) -> Select:
    query = (select(Contest, Election, Jurisdiction).join(Election, Contest.election_id == Election.id)
             .join(Jurisdiction, Contest.jurisdiction_id == Jurisdiction.id)
             .outerjoin(Office, Contest.office_id == Office.id).where(*_event_conditions(filters)))
    if filters.office_id is not None:
        query = query.where(Contest.office_id == filters.office_id)
    if filters.seat_class is not None:
        query = query.where(Contest.office_id.in_(select(SenateSeat.office_id).where(
            SenateSeat.seat_class == filters.seat_class)))
    if filters.office is not None:
        query = query.where(or_(func.lower(Contest.office_name) == filters.office.lower(),
                                func.lower(Office.name) == filters.office.lower()))
    if filters.contest_id is not None:
        query = query.where(Contest.id == filters.contest_id)
    if filters.state_code is not None:
        query = query.where(Jurisdiction.state_code == filters.state_code)
    if filters.party_id is not None and not result_geography:
        query = query.where(Contest.id.in_(select(Candidacy.contest_id).where(
            Candidacy.id.in_(_party_candidates(filters.party_id)))))
    if filters.jurisdiction_id is not None and not result_geography:
        county = (select(CanonicalVoteReturn.contest_id)
                  .join(CanonicalPublication, CanonicalPublication.batch_id == CanonicalVoteReturn.batch_id)
                  .where(CanonicalVoteReturn.jurisdiction_id == filters.jurisdiction_id))
        state = (select(StateVoteReturn.contest_id)
                 .join(StateResultPublication, StateResultPublication.batch_id == StateVoteReturn.batch_id)
                 .where(StateVoteReturn.jurisdiction_id == filters.jurisdiction_id))
        query = query.where(or_(Contest.jurisdiction_id == filters.jurisdiction_id,
                                Contest.id.in_(county), Contest.id.in_(state)))
    return query


def _publications_for_contests(session: Session, contest_ids: list[UUID]) -> dict:
    found = defaultdict(list)
    for vote, batch_type, pointer_type in (
        (CanonicalVoteReturn, CanonicalResultBatch, CanonicalPublication),
        (StateVoteReturn, StateResultBatch, StateResultPublication),
    ):
        pairs = session.execute(select(vote.contest_id, vote.batch_id).join(
            pointer_type, pointer_type.batch_id == vote.batch_id).where(
                vote.contest_id.in_(contest_ids)).distinct()).all()
        summaries = {}
        for contest_id, batch_id in pairs:
            if batch_id not in summaries:
                batch = session.get(batch_type, batch_id)
                pointer = session.get(pointer_type, batch.scope_key)
                summaries[batch_id] = _publication(session, batch, pointer)
            found[contest_id].append(summaries[batch_id])
    for publications in found.values():
        publications.sort(key=lambda p: (p["scope_key"], str(p["batch_id"])))
    return found


def list_contests(session: Session, filters: ElectionFilters) -> dict:
    query = _contest_query(filters)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.execute(query.order_by(Election.election_date.desc(), Contest.id)
                           .limit(filters.limit).offset(filters.offset)).all()
    publications = _publications_for_contests(session, [c.id for c, _, _ in rows])
    seats = {s.office_id:s.seat_class for s in session.scalars(select(SenateSeat).where(
        SenateSeat.office_id.in_([c.office_id for c, _, _ in rows if c.office_id])))}
    return _page([dict(id=c.id, election_id=e.id, election_date=e.election_date, stage=e.election_type,
                       office_id=c.office_id, office_name=c.office_name, office_term_id=c.office_term_id,
                       seat_class=seats.get(c.office_id),
                       nomination_party_id=c.nomination_party_id, preceding_contest_id=c.preceding_contest_id,
                       jurisdiction=_geography(j), publications=publications[c.id]) for c, e, j in rows], total, filters)


def list_elections(session: Session, filters: ElectionFilters) -> dict:
    query = select(Election, Jurisdiction).join(Jurisdiction).where(*_event_conditions(filters))
    matching = _contest_query(filters).with_only_columns(Contest.election_id)
    if any(v is not None for v in (filters.office, filters.office_id, filters.party_id, filters.contest_id, filters.seat_class)):
        query = query.where(Election.id.in_(matching))
    else:
        if filters.state_code is not None:
            query = query.where(Jurisdiction.state_code == filters.state_code)
        if filters.jurisdiction_id is not None:
            query = query.where(or_(Election.jurisdiction_id == filters.jurisdiction_id,
                                    Election.id.in_(matching)))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.execute(query.order_by(Election.election_date.desc(), Election.id)
                           .limit(filters.limit).offset(filters.offset)).all()
    contests = session.execute(select(Contest.id, Contest.election_id).where(
        Contest.election_id.in_([e.id for e, _ in rows]))).all()
    publications = _publications_for_contests(session, [c for c, _ in contests])
    by_election = defaultdict(dict)
    for contest_id, election_id in contests:
        for publication in publications[contest_id]:
            by_election[election_id][publication["batch_id"]] = publication
    return _page([dict(id=e.id, election_date=e.election_date, stage=e.election_type,
                       election_cycle=e.election_cycle, parent_election_id=e.parent_election_id,
                       jurisdiction=_geography(j), publications=sorted(by_election[e.id].values(),
                           key=lambda p: (p["scope_key"], str(p["batch_id"])))) for e, j in rows], total, filters)


def list_results(session: Session, filters: ResultFilters, *, candidacy_id: UUID | None = None) -> dict:
    vote = CanonicalVoteReturn
    # Candidate groups use their canonical candidacy. Anonymous buckets retain
    # the individual return UUID, avoiding identity inference from source labels.
    group_key = case((vote.vote_kind.in_(["candidate_total", "ballot_line"]), vote.candidacy_id), else_=vote.id)
    contests = _contest_query(filters, result_geography=True).with_only_columns(Contest.id)
    keys = (select(vote.batch_id, vote.contest_id, vote.jurisdiction_id, group_key.label("result_key"))
            .join(CanonicalPublication, CanonicalPublication.batch_id == vote.batch_id)
            .where(vote.contest_id.in_(contests), vote.reporting_level == filters.reporting_level,
                   vote.reporting_mode == filters.reporting_mode))
    if filters.jurisdiction_id is not None:
        keys = keys.where(vote.jurisdiction_id == filters.jurisdiction_id)
    if candidacy_id is not None:
        keys = keys.where(vote.candidacy_id == candidacy_id)
    if filters.party_id is not None:
        keys = keys.where(vote.candidacy_id.in_(_party_candidates(filters.party_id)))
    grouped = keys.distinct().subquery()
    total = session.scalar(select(func.count()).select_from(grouped))
    page_keys = session.execute(select(grouped).join(Contest, Contest.id == grouped.c.contest_id)
        .join(Election, Election.id == Contest.election_id)
        .order_by(Election.election_date.desc(), grouped.c.contest_id, grouped.c.jurisdiction_id,
                  grouped.c.batch_id, grouped.c.result_key).limit(filters.limit).offset(filters.offset)).all()
    items = []
    if page_keys:
        raw = session.scalars(select(vote).where(
            tuple_(vote.batch_id, vote.contest_id, vote.jurisdiction_id, group_key).in_([tuple(k) for k in page_keys]),
            vote.reporting_level == filters.reporting_level, vote.reporting_mode == filters.reporting_mode)).all()
        groups = defaultdict(list)
        for row in raw:
            key = row.candidacy_id if row.vote_kind in {"candidate_total", "ballot_line"} else row.id
            groups[(row.batch_id, row.contest_id, row.jurisdiction_id, key)].append(row)
        totals, publications = {}, {}
        candidate_parties = defaultdict(set)
        for candidacy_id, party_id in session.execute(select(BallotLine.candidacy_id, BallotLine.party_id)
            .where(BallotLine.candidacy_id.in_({r.candidacy_id for r in raw if r.candidacy_id}),
                   BallotLine.party_id.is_not(None))):
            candidate_parties[candidacy_id].add(party_id)
        page_units = defaultdict(set)
        for batch_id, contest_id, jurisdiction_id, _ in page_keys:
            page_units[(batch_id, contest_id)].add(jurisdiction_id)
        for key in page_keys:
            batch_id, contest_id, jurisdiction_id, _ = key
            pair = (batch_id, contest_id)
            if pair not in totals:
                totals[pair] = {(r["jurisdiction_id"], r["candidacy_id"]): r for r in candidate_totals(
                    session, batch_id=batch_id, contest_id=contest_id,
                    reporting_level=filters.reporting_level, reporting_mode=filters.reporting_mode,
                    jurisdiction_ids=page_units[pair])}
            if batch_id not in publications:
                batch = session.get(CanonicalResultBatch, batch_id)
                publications[batch_id] = _publication(session, batch, session.get(CanonicalPublication, batch.scope_key))
            rows = groups[tuple(key)]
            row = rows[0]
            references = {session.get(GeographicResolution, r.geographic_resolution_id).reference_id for r in rows}
            if len(references) != 1 or None in references:
                raise MaterializationError("Incompatible geographic references within candidate result")
            reference = session.get(GeographicReference, references.pop())
            if reference.release_id != publications[batch_id]["reference_release_id"] or reference.jurisdiction_id != jurisdiction_id:
                raise MaterializationError("Result geography differs from publication reference")
            candidate = session.get(Candidacy, row.candidacy_id) if row.candidacy_id else None
            party_ids = set(candidate_parties[row.candidacy_id])
            if candidate and candidate.party_id:
                party_ids.add(candidate.party_id)
            count = row.votes
            basis = row.vote_kind
            if basis in {"candidate_total", "ballot_line"}:
                aggregated = totals[pair][(str(jurisdiction_id), str(row.candidacy_id))]
                count, basis = aggregated["votes"], aggregated["basis"]
            contest = session.get(Contest, contest_id)
            election = session.get(Election, contest.election_id)
            seat = session.get(SenateSeat, contest.office_id) if contest.office_id else None
            if reference.kind != filters.reporting_level or not reference.vintage_start <= election.election_date.year <= reference.vintage_end:
                raise MaterializationError("Result reference has an incompatible grain or vintage")
            items.append(dict(contest_id=contest_id, election_id=election.id,
                election_date=election.election_date, stage=election.election_type,
                office_id=contest.office_id, office_name=contest.office_name,
                seat_class=seat.seat_class if seat else None,
                jurisdiction=_geography(session.get(Jurisdiction, jurisdiction_id)),
                reporting_level=filters.reporting_level, reporting_mode=filters.reporting_mode,
                candidacy_id=row.candidacy_id, person_id=candidate.person_id if candidate else None,
                candidate_kind=candidate.candidate_kind if candidate else row.vote_kind,
                label=(candidate.source_label if candidate else None) or row.source_label,
                party_ids=sorted(party_ids, key=str), basis=basis, votes=count,
                geographic_reference_id=reference.id, reference_vintage_start=reference.vintage_start,
                reference_vintage_end=reference.vintage_end,
                observation_ids=sorted([r.observation_id for r in rows], key=str),
                correction_ids=sorted([r.correction_id for r in rows if r.correction_id], key=str),
                publication=publications[batch_id]))
    return _page(items, total, filters, results=True,
                 reporting_level=filters.reporting_level, reporting_mode=filters.reporting_mode)


def list_state_results(session: Session, filters: ElectionFilters) -> dict:
    contests = _contest_query(filters, result_geography=True).with_only_columns(Contest.id)
    query = (select(StateVoteReturn, StateResultBatch, StateResultPublication)
             .join(StateResultPublication, StateResultPublication.batch_id == StateVoteReturn.batch_id)
             .join(StateResultBatch, StateResultBatch.id == StateVoteReturn.batch_id)
             .where(StateVoteReturn.contest_id.in_(contests)))
    if filters.jurisdiction_id is not None:
        query = query.where(StateVoteReturn.jurisdiction_id == filters.jurisdiction_id)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.execute(query.order_by(StateResultBatch.election_year.desc(), StateVoteReturn.state_code, StateVoteReturn.candidate_bucket,
                                         StateVoteReturn.batch_id).limit(filters.limit).offset(filters.offset)).all()
    publications = {}
    # Validate even an offset beyond the last page against the authority manifest.
    for year in session.scalars(query.with_only_columns(StateResultBatch.election_year).distinct()):
        state_totals(session, year=year)
    items = []
    for row, batch, pointer in rows:
        if batch.id not in publications:
            publications[batch.id] = _publication(session, batch, pointer)
        contest = session.get(Contest, row.contest_id)
        election = session.get(Election, contest.election_id)
        items.append(dict(contest_id=row.contest_id, election_id=election.id, election_date=election.election_date,
            jurisdiction=_geography(session.get(Jurisdiction, row.jurisdiction_id)),
            candidate_bucket=row.candidate_bucket,
            bucket_kind="aggregate" if row.candidate_bucket == "OTHER" else "source_candidate",
            votes=row.votes, source_locator=row.source_locator, source_adjustment=row.source_adjustment,
            publication=publications[batch.id]))
    return _page(items, total, filters, results=True)
