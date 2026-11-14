"""Idempotent, evidence-scoped canonical election entity creation (DATA-003).

A source label is *not* evidence that two persons are the same person. Callers
supply distinct creation keys for source-scoped candidacies and may attach a
verified person explicitly. All functions participate in the caller's transaction.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.core import Election, Contest, Candidacy
from app.models.election import Office, OfficeTerm, BallotLine
from ingestion.canonical_medsl import scoped_key


def _get_or_create(session: Session, model, creation_key: str, **values):
    if not creation_key or len(creation_key) > 200:
        raise ValueError("A nonblank, <=200-character creation key is required")
    values["creation_key"] = creation_key
    session.execute(pg_insert(model).values(**values).on_conflict_do_nothing(index_elements=["creation_key"]))
    item = session.scalar(select(model).where(model.creation_key == creation_key))
    if item is None:
        raise RuntimeError(f"Could not retrieve {model.__name__} after insert")
    for name, supplied in values.items():
        if model is Candidacy and name in {"person_id", "party_id"} and supplied is None:
            # An authoritative identity linked after initial materialization is retained.
            continue
        if getattr(item, name) != supplied:
            raise ValueError(f"{model.__name__} creation key {creation_key} conflicts on {name}")
    return item


def office(session: Session, *, creation_key: str, name: str, office_kind: str,
           jurisdiction_id: UUID | None = None, valid_from: date | None = None,
           valid_until: date | None = None) -> Office:
    if valid_from and valid_until and valid_from > valid_until:
        raise ValueError("Invalid office effective date range")
    return _get_or_create(session, Office, creation_key, name=name, office_kind=office_kind,
                          jurisdiction_id=jurisdiction_id, valid_from=valid_from, valid_until=valid_until)


def office_term(session: Session, *, creation_key: str, office_id: UUID,
                start_date: date, end_date: date, seat_label: str | None = None,
                predecessor_id: UUID | None = None) -> OfficeTerm:
    if start_date >= end_date:
        raise ValueError("Invalid office term")
    return _get_or_create(session, OfficeTerm, creation_key, office_id=office_id,
                          start_date=start_date, end_date=end_date, seat_label=seat_label,
                          predecessor_id=predecessor_id)


def election(session: Session, *, creation_key: str, election_date: date,
             election_type: str, jurisdiction_id: UUID, election_cycle: int | None = None,
             parent_election_id: UUID | None = None) -> Election:
    if election_type not in {"general", "primary", "runoff", "special", "special_primary", "special_runoff", "other"}:
        raise ValueError("Invalid election type")
    return _get_or_create(session, Election, creation_key, election_date=election_date,
                          election_type=election_type, jurisdiction_id=jurisdiction_id,
                          election_cycle=election_cycle, parent_election_id=parent_election_id)


def contest(session: Session, *, creation_key: str, office_name: str,
            election_id: UUID, jurisdiction_id: UUID, office_id: UUID | None = None,
            office_term_id: UUID | None = None, preceding_contest_id: UUID | None = None,
            nomination_party_id: UUID | None = None) -> Contest:
    return _get_or_create(session, Contest, creation_key, office_name=office_name,
                          election_id=election_id, jurisdiction_id=jurisdiction_id,
                          office_id=office_id, office_term_id=office_term_id,
                          preceding_contest_id=preceding_contest_id,
                          nomination_party_id=nomination_party_id)


def candidacy(session: Session, *, creation_key: str, contest_id: UUID,
              source_label: str, candidate_kind: str = "candidate",
              person_id: UUID | None = None, party_id: UUID | None = None) -> Candidacy:
    if candidate_kind not in {"candidate", "write_in", "aggregate", "unresolved"}:
        raise ValueError("Invalid candidate kind")
    if not source_label.strip():
        raise ValueError("Unresolved candidacy needs a nonblank source label")
    return _get_or_create(session, Candidacy, creation_key, contest_id=contest_id,
                          source_label=source_label, candidate_kind=candidate_kind,
                          person_id=person_id, party_id=party_id)


def ballot_line(session: Session, *, creation_key: str, candidacy_id: UUID,
                line_label: str, line_kind: str, party_id: UUID | None = None) -> BallotLine:
    if line_kind not in {"party", "independent", "write_in", "unaffiliated", "other"}:
        raise ValueError("Invalid ballot line kind")
    if not line_label.strip():
        raise ValueError("Blank ballot line")
    return _get_or_create(session, BallotLine, creation_key, candidacy_id=candidacy_id,
                          line_label=line_label, line_kind=line_kind, party_id=party_id)
