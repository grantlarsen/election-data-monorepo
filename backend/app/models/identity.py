"""Source-attributed identity records. Labels never imply canonical equality.

DATA-002 is intentionally independent of finance totals and matching algorithms.
All entity IDs are UUIDs and source observations are never rewritten here.
"""
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PersonName(Base):
    __tablename__ = "person_name"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_person_name_dedupe"),
        CheckConstraint("kind IN ('primary', 'alias', 'former', 'source_reported')", name="ck_person_name_kind"),
        CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until", name="ck_person_name_dates"),
        Index("ix_person_name_person", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(ForeignKey("person.id"), nullable=False)
    name_raw: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("data_source.id"))
    release_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_release.id"))
    source_record_key: Mapped[str | None] = mapped_column(String(200))
    evidence: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Organization(Base):
    __tablename__ = "organization"
    __table_args__ = (
        CheckConstraint("kind IN ('committee', 'political_organization', 'other')", name="ck_organization_kind"),
        UniqueConstraint("creation_key", name="uq_organization_creation_key"),
        Index("ix_organization_party", "party_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    creation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    party_id: Mapped[UUID | None] = mapped_column(ForeignKey("political_party.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ExternalIdentifier(Base):
    __tablename__ = "external_identifier"
    __table_args__ = (
        UniqueConstraint("namespace", "identifier_type", "value", name="uq_external_identifier_namespace_type_value"),
        CheckConstraint("length(trim(value)) > 0", name="ck_external_identifier_value"),
        CheckConstraint(
            "(CASE WHEN person_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN candidacy_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN organization_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN party_id IS NULL THEN 0 ELSE 1 END) <= 1",
            name="ck_external_identifier_single_target",
        ),
        CheckConstraint("namespace <> 'fec' OR identifier_type <> 'committee' OR (person_id IS NULL AND candidacy_id IS NULL AND party_id IS NULL)", name="ck_external_identifier_fec_committee"),
        CheckConstraint("namespace <> 'fec' OR identifier_type <> 'candidate' OR (organization_id IS NULL AND party_id IS NULL)", name="ck_external_identifier_fec_candidate"),
        Index("ix_external_identifier_person", "person_id"),
        Index("ix_external_identifier_candidacy", "candidacy_id"),
        Index("ix_external_identifier_organization", "organization_id"),
        Index("ix_external_identifier_party", "party_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    identifier_type: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    person_id: Mapped[UUID | None] = mapped_column(ForeignKey("person.id"))
    candidacy_id: Mapped[UUID | None] = mapped_column(ForeignKey("candidacy.id"))
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organization.id"))
    party_id: Mapped[UUID | None] = mapped_column(ForeignKey("political_party.id"))
    label_raw: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"), nullable=False)
    release_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_release.id"))
    source_record_key: Mapped[str | None] = mapped_column(String(200))
    evidence: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IdentityAssignmentEvent(Base):
    """Append-only assignment evidence; an assignment is never a name match."""
    __tablename__ = "identity_assignment_event"
    __table_args__ = (
        CheckConstraint("target_type IN ('person', 'candidacy', 'organization', 'party')", name="ck_identity_event_target_type"),
        CheckConstraint(
            "(CASE WHEN person_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN candidacy_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN organization_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN party_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_identity_event_single_target",
        ),
        CheckConstraint(
            "(target_type = 'person' AND person_id IS NOT NULL) OR "
            "(target_type = 'candidacy' AND candidacy_id IS NOT NULL) OR "
            "(target_type = 'organization' AND organization_id IS NOT NULL) OR "
            "(target_type = 'party' AND party_id IS NOT NULL)",
            name="ck_identity_event_target_matches_type",
        ),
        Index("ix_identity_event_identifier", "identifier_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identifier_id: Mapped[UUID] = mapped_column(ForeignKey("external_identifier.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    person_id: Mapped[UUID | None] = mapped_column(ForeignKey("person.id"))
    candidacy_id: Mapped[UUID | None] = mapped_column(ForeignKey("candidacy.id"))
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organization.id"))
    party_id: Mapped[UUID | None] = mapped_column(ForeignKey("political_party.id"))
    actor: Mapped[str] = mapped_column(String(150), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CommitteeRelationship(Base):
    __tablename__ = "committee_relationship"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_committee_relationship_dedupe"),
        CheckConstraint("person_id IS NOT NULL OR candidacy_id IS NOT NULL", name="ck_committee_relationship_subject"),
        CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until", name="ck_committee_relationship_dates"),
        CheckConstraint("cycle IS NULL OR cycle >= 1788", name="ck_committee_relationship_cycle"),
        Index("ix_committee_relationship_person", "person_id"),
        Index("ix_committee_relationship_candidacy", "candidacy_id"),
        Index("ix_committee_relationship_org", "organization_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organization.id"), nullable=False)
    person_id: Mapped[UUID | None] = mapped_column(ForeignKey("person.id"))
    candidacy_id: Mapped[UUID | None] = mapped_column(ForeignKey("candidacy.id"))
    role: Mapped[str] = mapped_column(String(60), nullable=False)
    cycle: Mapped[int | None] = mapped_column(Integer)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"), nullable=False)
    release_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_release.id"))
    source_record_key: Mapped[str | None] = mapped_column(String(200))
    evidence: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
