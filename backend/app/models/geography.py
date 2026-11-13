"""Step 6: reference evidence and resolutions; original election rows are immutable."""
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeographicReference(Base):
    __tablename__ = "geographic_reference"
    __table_args__ = (
        UniqueConstraint("release_id", "kind", "geoid", name="uq_geo_reference_release_kind_geoid"),
        CheckConstraint("vintage_start <= vintage_end", name="ck_geo_reference_vintage"),
        CheckConstraint("kind IN ('state', 'county')", name="ck_geo_reference_kind"),
        Index("ix_geo_reference_vintage_code", "vintage_start", "vintage_end", "geoid"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False, index=True)
    jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    geoid: Mapped[str] = mapped_column(String(5), nullable=False)
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
    value: Mapped[str] = mapped_column(String(5), nullable=False)
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
        UniqueConstraint("observation_id", "reference_release_id", name="uq_geo_resolution_observation_release"),
        Index("ix_geo_resolution_release_status", "reference_release_id", "status"),
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
