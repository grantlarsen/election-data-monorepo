"""Step 6: reference evidence and resolutions; original election rows are immutable."""
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeographicReference(Base):
    __tablename__ = "geographic_reference"
    __table_args__ = (
        UniqueConstraint("release_id", "kind", "geoid", name="uq_geo_reference_release_kind_geoid"),
        CheckConstraint("vintage_start <= vintage_end", name="ck_geo_reference_vintage"),
        CheckConstraint("kind IN ('state', 'county', 'place')", name="ck_geo_reference_kind"),
        Index("ix_geo_reference_vintage_code", "vintage_start", "vintage_end", "geoid"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False, index=True)
    jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    geoid: Mapped[str] = mapped_column(String(10), nullable=False)
    state_fips: Mapped[str] = mapped_column(String(2), nullable=False)
    name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    name_key: Mapped[str] = mapped_column(Text, nullable=False)
    vintage_start: Mapped[int] = mapped_column(Integer, nullable=False)
    vintage_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)


class JurisdictionIdentifier(Base):
    __tablename__ = "jurisdiction_identifier"
    __table_args__ = (
        UniqueConstraint("reference_id", "scheme", name="uq_jurisdiction_identifier_reference_scheme"),
        CheckConstraint("valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
                        name="ck_jurisdiction_identifier_dates"),
        Index("ix_jurisdiction_identifier_scheme_value", "scheme", "value"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(ForeignKey("geographic_reference.id"), nullable=False)
    scheme: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[str] = mapped_column(String(10), nullable=False)
    # Legal effective dates are UNKNOWN for CBP multi-year snapshots. Never infer from file ranges.
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)


class JurisdictionRelationship(Base):
    __tablename__ = "jurisdiction_relationship"
    __table_args__ = (UniqueConstraint("reference_id", name="uq_jurisdiction_relationship_reference"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    parent_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    child_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(ForeignKey("geographic_reference.id"), nullable=False)
    relationship: Mapped[str] = mapped_column(String(30), nullable=False, default="contains")


class GeographicResolution(Base):
    __tablename__ = "geographic_resolution"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_geo_resolution_supersedes"),
        Index("ix_geo_resolution_release_status", "reference_release_id", "status"),
        Index("uq_geo_resolution_root", "observation_id", "reference_release_id",
              unique=True, postgresql_where=text("supersedes_id IS NULL")),
        Index("ix_geo_resolution_observation_release", "observation_id", "reference_release_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("election_result_observation.id"), nullable=False)
    reference_release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    reference_id: Mapped[UUID | None] = mapped_column(ForeignKey("geographic_reference.id"))
    jurisdiction_id: Mapped[UUID | None] = mapped_column(ForeignKey("jurisdiction.id"))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[str] = mapped_column(String(60), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False, server_default="step6-v1")
    decision_sha256: Mapped[str | None] = mapped_column(String(64))
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("geographic_resolution.id"))
    published_by: Mapped[str | None] = mapped_column(String(100))


class GeographicAlias(Base):
    """Source-scoped, time-bounded county alias; proposals cannot authorize matches."""
    __tablename__ = "geographic_alias"
    __table_args__ = (
        UniqueConstraint("source_name", "state_code", "source_label_key", "target_geoid",
                         "first_year", "last_year", name="uq_geographic_alias_scope"),
        CheckConstraint("first_year <= last_year", name="ck_geographic_alias_years"),
        CheckConstraint("status IN ('PROPOSED', 'APPROVED', 'REJECTED')", name="ck_geographic_alias_status"),
        Index("ix_geo_alias_lookup", "source_name", "state_code", "status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    source_label_raw: Mapped[str] = mapped_column(Text, nullable=False)
    source_label_key: Mapped[str] = mapped_column(Text, nullable=False)
    target_geoid: Mapped[str] = mapped_column(String(5), nullable=False)
    jurisdiction_id: Mapped[UUID | None] = mapped_column(ForeignKey("jurisdiction.id"))
    first_year: Mapped[int] = mapped_column(Integer, nullable=False)
    last_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PROPOSED")
    evidence_url: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_note: Mapped[str] = mapped_column(Text, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GeographicChange(Base):
    """Dated, separately reviewed change evidence; NOT automatic identity merging."""
    __tablename__ = "geographic_change"
    __table_args__ = (
        UniqueConstraint("old_geoid", "new_geoid", "effective_date", name="uq_geographic_change_event"),
        CheckConstraint("old_geoid <> new_geoid", name="ck_geographic_change_distinct"),
        CheckConstraint("status IN ('PROPOSED', 'VERIFIED', 'REJECTED')", name="ck_geographic_change_status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    old_geoid: Mapped[str] = mapped_column(String(5), nullable=False)
    new_geoid: Mapped[str] = mapped_column(String(5), nullable=False)
    old_name: Mapped[str] = mapped_column(Text, nullable=False)
    new_name: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_url: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_note: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PROPOSED")
    verified_by: Mapped[str | None] = mapped_column(String(100))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeographicIdentityLink(Base):
    """Explicitly reviewed identity continuity; never rewrites either jurisdiction UUID."""
    __tablename__ = "geographic_identity_link"
    __table_args__ = (
        UniqueConstraint("change_id", "old_jurisdiction_id", "new_jurisdiction_id",
                         name="uq_geo_identity_link"),
        CheckConstraint("old_jurisdiction_id <> new_jurisdiction_id",
                        name="ck_geo_identity_link_distinct"),
        CheckConstraint("relationship IN ('SAME_ENTITY_RECODED', 'SUCCESSOR')",
                        name="ck_geo_identity_link_relationship"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    change_id: Mapped[UUID] = mapped_column(ForeignKey("geographic_change.id"), nullable=False)
    old_jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    new_jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    relationship: Mapped[str] = mapped_column(String(40), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GeographicReportingUnit(Base):
    """Source-vintage scoped classification, intentionally not a Census county."""
    __tablename__ = "geographic_reporting_unit"
    __table_args__ = (
        UniqueConstraint("source_name", "state_code", "election_year", "identifier_scheme",
                         "identifier_value", name="uq_geo_reporting_unit_scope"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    election_year: Mapped[int] = mapped_column(Integer, nullable=False)
    source_label: Mapped[str] = mapped_column(Text, nullable=False)
    identifier_scheme: Mapped[str] = mapped_column(String(50), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    jurisdiction_id: Mapped[UUID | None] = mapped_column(ForeignKey("jurisdiction.id"))
    evidence_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
