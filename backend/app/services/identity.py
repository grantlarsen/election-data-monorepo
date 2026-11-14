"""DATA-002 persistence operations (PostgreSQL).

All calls participate in the caller's Session transaction. Recommended usage:
    with Session(engine) as session, session.begin():
        create_person(session, full_name="...", creation_key="curated:...")

Do not build creation keys from MEDSL name labels: names are not identities.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.core import Candidacy, DataSource, Person, PoliticalParty
from app.models.ingestion import SourceRelease
from app.models.identity import (
    CommitteeRelationship, ExternalIdentifier, IdentityAssignmentEvent,
    Organization, PersonName,
)

TargetType = Literal["person", "candidacy", "organization", "party"]
_TARGET_COLUMNS: dict[str, str] = {
    "person": "person_id", "candidacy": "candidacy_id",
    "organization": "organization_id", "party": "party_id",
}
_TARGET_MODELS = {
    "person": Person, "candidacy": Candidacy,
    "organization": Organization, "party": PoliticalParty,
}
_TOKEN = re.compile(r"^[a-z][a-z0-9_-]*(?::[a-z0-9_-]+)*$")


class IdentityConflictError(ValueError):
    """The requested relationship contradicts an existing identity assertion."""


def _nonblank(value: str, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} cannot be blank")
    return value


def _key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _source(session: Session, source_id: UUID | None, release_id: UUID | None) -> None:
    if release_id is not None:
        if source_id is None:
            raise ValueError("release_id requires source_id")
        release = session.get(SourceRelease, release_id)
        if release is None or release.source_id != source_id:
            raise IdentityConflictError("release does not belong to specified source")
    if source_id is not None and session.get(DataSource, source_id) is None:
        raise ValueError("source_id not found")


def _dates(valid_from: date | None, valid_until: date | None) -> None:
    if valid_from is not None and valid_until is not None and valid_from > valid_until:
        raise ValueError("valid_from is later than valid_until")


def _target(session: Session, target_type: TargetType | None, target_id: UUID | None) -> dict:
    if (target_type is None) != (target_id is None):
        raise ValueError("target_type and target_id must be supplied together, or both omitted")
    if target_type is None:
        return {}
    if target_type not in _TARGET_MODELS:
        raise ValueError(f"unknown target type: {target_type}")
    if session.get(_TARGET_MODELS[target_type], target_id) is None:
        raise ValueError(f"{target_type} target not found")
    return {_TARGET_COLUMNS[target_type]: target_id}


def _scope(namespace: str, identifier_type: str, target_type: TargetType | None) -> None:
    if not _TOKEN.fullmatch(namespace) or not _TOKEN.fullmatch(identifier_type):
        raise ValueError("namespace and identifier_type must be explicit lowercase tokens")
    if namespace == "fec":
        if identifier_type == "committee" and target_type not in (None, "organization"):
            raise ValueError("FEC committee identifiers target organizations")
        if identifier_type == "candidate" and target_type not in (None, "person", "candidacy"):
            raise ValueError("FEC candidate identifiers target people or candidacies")


def _upsert(session: Session, model: type, values: dict, unique: list[str]):
    stmt = (pg_insert(model.__table__).values(id=uuid4(), **values)
            .on_conflict_do_nothing(index_elements=unique)
            .returning(model.__table__.c.id))
    new_id = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        return session.get(model, new_id)
    row = session.execute(select(model).filter_by(**{name: values[name] for name in unique})).scalar_one()
    # Avoid hiding a SHA collision or a differing meaning for a stable creation key.
    if any(getattr(row, field) != value for field, value in values.items()):
        raise IdentityConflictError("idempotency key already belongs to a different record")
    return row


def create_person(session: Session, *, full_name: str, creation_key: str) -> Person:
    """Create explicitly curated canonical person. Name collisions are deliberately allowed."""
    return _upsert(session, Person,
                   {"full_name": _nonblank(full_name, "full_name"),
                    "creation_key": _nonblank(creation_key, "creation_key")},
                   ["creation_key"])


def register_organization(session: Session, *, name: str, kind: str,
                          creation_key: str, party_id: UUID | None = None) -> Organization:
    if kind not in {"committee", "political_organization", "other"}:
        raise ValueError("invalid organization kind")
    if party_id is not None and session.get(PoliticalParty, party_id) is None:
        raise ValueError("unknown political party")
    return _upsert(session, Organization,
                   {"name": _nonblank(name, "name"), "kind": kind,
                    "creation_key": _nonblank(creation_key, "creation_key"),
                    "party_id": party_id}, ["creation_key"])


def add_person_name(session: Session, *, person_id: UUID, name_raw: str, kind: str,
                    valid_from: date | None = None, valid_until: date | None = None,
                    source_id: UUID | None = None, release_id: UUID | None = None,
                    source_record_key: str | None = None, evidence: str | None = None) -> PersonName:
    if session.get(Person, person_id) is None:
        raise ValueError("person not found")
    if kind not in {"primary", "alias", "former", "source_reported"}:
        raise ValueError("invalid person-name kind")
    if kind == "source_reported" and source_id is None:
        raise ValueError("source_reported requires source provenance")
    _dates(valid_from, valid_until)
    _source(session, source_id, release_id)
    payload = dict(person_id=person_id, name_raw=_nonblank(name_raw, "name_raw"),
                   kind=kind, valid_from=valid_from, valid_until=valid_until,
                   source_id=source_id, release_id=release_id,
                   source_record_key=source_record_key, evidence=evidence)
    payload["dedupe_key"] = _key(payload)
    return _upsert(session, PersonName, payload, ["dedupe_key"])


def lookup_identifier(session: Session, *, namespace: str, identifier_type: str,
                      value: str) -> ExternalIdentifier | None:
    _scope(namespace, identifier_type, None)
    return session.execute(select(ExternalIdentifier).where(
        ExternalIdentifier.namespace == namespace,
        ExternalIdentifier.identifier_type == identifier_type,
        ExternalIdentifier.value == value)).scalar_one_or_none()


def lookup_canonical(session: Session, *, namespace: str, identifier_type: str, value: str):
    """Return canonical entity or None for unknown/unresolved identifiers; never name-match."""
    found = lookup_identifier(session, namespace=namespace, identifier_type=identifier_type, value=value)
    if found is None:
        return None
    for target_type, attr in _TARGET_COLUMNS.items():
        target_id = getattr(found, attr)
        if target_id is not None:
            return session.get(_TARGET_MODELS[target_type], target_id)
    return None


def attach_external_identifier(session: Session, *, namespace: str, identifier_type: str,
                               value: str, source_id: UUID,
                               target_type: TargetType | None = None, target_id: UUID | None = None,
                               release_id: UUID | None = None,
                               source_record_key: str | None = None,
                               label_raw: str | None = None,
                               actor: str | None = None, evidence: str | None = None) -> ExternalIdentifier:
    """Register an ID with zero or one verified target. Never overwrite a prior target.

    To link an *existing* unresolved ID, explicitly call resolve_external_identifier.
    """
    _scope(namespace, identifier_type, target_type)
    _nonblank(value, "value")
    _source(session, source_id, release_id)
    refs = _target(session, target_type, target_id)
    if refs and (not actor or not actor.strip() or not evidence or not evidence.strip()):
        raise ValueError("linked identifiers require actor and supporting evidence")
    values = dict(namespace=namespace, identifier_type=identifier_type, value=value,
                  source_id=source_id, release_id=release_id, source_record_key=source_record_key,
                  label_raw=label_raw, evidence=evidence, **refs)
    statement = (pg_insert(ExternalIdentifier.__table__).values(id=uuid4(), **values)
                 .on_conflict_do_nothing(index_elements=["namespace", "identifier_type", "value"])
                 .returning(ExternalIdentifier.__table__.c.id))
    new_id = session.execute(statement).scalar_one_or_none()
    if new_id is None:
        existing = lookup_identifier(session, namespace=namespace, identifier_type=identifier_type, value=value)
        assert existing is not None
        old_refs = {name: getattr(existing, name) for name in _TARGET_COLUMNS.values() if getattr(existing, name) is not None}
        if old_refs != refs:
            raise IdentityConflictError("identifier already registered with a different or unresolved target; explicit review required")
        return existing
    row = session.get(ExternalIdentifier, new_id)
    if refs:
        session.add(IdentityAssignmentEvent(identifier_id=new_id, target_type=target_type,
                                            actor=actor, evidence=evidence, **refs))
        session.flush()
    return row


def resolve_external_identifier(session: Session, *, identifier_id: UUID,
                                target_type: TargetType, target_id: UUID,
                                actor: str, evidence: str) -> ExternalIdentifier:
    """Explicitly link an unresolved authoritative identifier and append an audit event.

    Reassignment or unlinking requires a future reviewed workflow (DATA-010).
    """
    _nonblank(actor, "actor")
    _nonblank(evidence, "evidence")
    row = session.execute(select(ExternalIdentifier).where(
        ExternalIdentifier.id == identifier_id).with_for_update()).scalar_one_or_none()
    if row is None:
        raise ValueError("identifier not found")
    _scope(row.namespace, row.identifier_type, target_type)
    refs = _target(session, target_type, target_id)
    old_refs = {name: getattr(row, name) for name in _TARGET_COLUMNS.values() if getattr(row, name) is not None}
    if old_refs == refs:
        return row
    if old_refs:
        raise IdentityConflictError("existing identity assignment cannot be overwritten")
    setattr(row, _TARGET_COLUMNS[target_type], target_id)
    session.add(IdentityAssignmentEvent(identifier_id=identifier_id, target_type=target_type,
                                        actor=actor, evidence=evidence, **refs))
    session.flush()
    return row


def link_committee(session: Session, *, organization_id: UUID, source_id: UUID,
                   role: str, person_id: UUID | None = None, candidacy_id: UUID | None = None,
                   cycle: int | None = None, valid_from: date | None = None,
                   valid_until: date | None = None, release_id: UUID | None = None,
                   source_record_key: str | None = None, evidence: str | None = None) -> CommitteeRelationship:
    org = session.get(Organization, organization_id)
    if org is None or org.kind != "committee":
        raise ValueError("organization must be a registered committee")
    if person_id is None and candidacy_id is None:
        raise ValueError("person or candidacy required")
    if person_id is not None and session.get(Person, person_id) is None:
        raise ValueError("person not found")
    if candidacy_id is not None:
        candidacy = session.get(Candidacy, candidacy_id)
        if candidacy is None:
            raise ValueError("candidacy not found")
        if person_id is not None and candidacy.person_id != person_id:
            raise IdentityConflictError("candidacy is not associated with the supplied person")
    if cycle is not None and cycle < 1788:
        raise ValueError("cycle out of range")
    _dates(valid_from, valid_until)
    _source(session, source_id, release_id)
    payload = dict(organization_id=organization_id, person_id=person_id, candidacy_id=candidacy_id,
                   role=_nonblank(role, "role"), cycle=cycle,
                   valid_from=valid_from, valid_until=valid_until,
                   source_id=source_id, release_id=release_id,
                   source_record_key=source_record_key, evidence=evidence)
    payload["dedupe_key"] = _key(payload)
    return _upsert(session, CommitteeRelationship, payload, ["dedupe_key"])


def get_person_identity(session: Session, person_id: UUID) -> dict:
    person = session.get(Person, person_id)
    if person is None:
        raise ValueError("person not found")
    candidacy_ids = select(Candidacy.id).where(Candidacy.person_id == person_id)
    return {
        "person": person,
        "names": session.scalars(select(PersonName).where(PersonName.person_id == person_id)
                                 .order_by(PersonName.created_at, PersonName.id)).all(),
        "identifiers": session.scalars(select(ExternalIdentifier).where(or_(
            ExternalIdentifier.person_id == person_id,
            ExternalIdentifier.candidacy_id.in_(candidacy_ids))).order_by(
                ExternalIdentifier.namespace, ExternalIdentifier.identifier_type, ExternalIdentifier.value)).all(),
        "committees": session.scalars(select(CommitteeRelationship).where(or_(
            CommitteeRelationship.person_id == person_id,
            CommitteeRelationship.candidacy_id.in_(candidacy_ids))).order_by(
                CommitteeRelationship.cycle, CommitteeRelationship.id)).all(),
    }
