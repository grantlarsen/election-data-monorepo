"""Versioned geography and reference evidence; original election rows are immutable."""
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index,
                        Integer, String, Text, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeographicReference(Base):
    __tablename__ = "geographic_reference"
    __table_args__ = (
        UniqueConstraint("release_id", "kind", "geoid", name="uq_geo_reference_release_kind_geoid"),
        UniqueConstraint("id", "jurisdiction_id", name="uq_geo_reference_identity"),
        CheckConstraint("vintage_start <= vintage_end", name="ck_geo_reference_vintage"),
        CheckConstraint("kind IN ('state', 'county', 'place', 'congressional_district')", name="ck_geo_reference_kind"),
        Index("ix_geo_reference_vintage_code", "vintage_start", "vintage_end", "geoid"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False, index=True)
    jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
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
        CheckConstraint("(valid_from IS NULL AND valid_until IS NULL) OR "
                        "length(trim(validity_evidence_url)) > 0 AND validity_evidence_url IS NOT NULL",
                        name="ck_jurisdiction_identifier_date_evidence"),
        ForeignKeyConstraint(["reference_id", "jurisdiction_id"],
                             ["geographic_reference.id", "geographic_reference.jurisdiction_id"],
                             name="fk_geo_identifier_identity"),
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
    validity_evidence_url: Mapped[str | None] = mapped_column(Text)


class JurisdictionRelationship(Base):
    __tablename__ = "jurisdiction_relationship"
    __table_args__ = (
        UniqueConstraint("reference_id", name="uq_jurisdiction_relationship_reference"),
        CheckConstraint("parent_id <> child_id", name="ck_geo_relationship_distinct"),
        CheckConstraint("valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
                        name="ck_geo_relationship_dates"),
        CheckConstraint("(valid_from IS NULL AND valid_until IS NULL) OR "
                        "length(trim(validity_evidence_url)) > 0 AND validity_evidence_url IS NOT NULL",
                        name="ck_geo_relationship_date_evidence"),
        ForeignKeyConstraint(["reference_id", "child_id"],
                             ["geographic_reference.id", "geographic_reference.jurisdiction_id"],
                             name="fk_geo_relationship_identity"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    parent_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    child_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(ForeignKey("geographic_reference.id"), nullable=False)
    relationship: Mapped[str] = mapped_column(String(30), nullable=False, default="contains")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    validity_evidence_url: Mapped[str | None] = mapped_column(Text)


class JurisdictionBoundaryVintage(Base):
    """Verified [from, until) boundary applicability; geometry belongs to DATA-007.

    A release's statistical coverage is never sufficient to create these rows.
    The exclusion is global per identity, including concurrent transactions.
    """
    __tablename__ = "jurisdiction_boundary_vintage"
    __table_args__ = (
        UniqueConstraint("jurisdiction_id", "version_label", name="uq_geo_boundary_label"),
        ForeignKeyConstraint(["reference_id", "jurisdiction_id"],
                             ["geographic_reference.id", "geographic_reference.jurisdiction_id"],
                             name="fk_geo_boundary_identity"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="ck_geo_boundary_dates"),
        CheckConstraint("length(trim(evidence_url)) > 0 AND length(trim(evidence_note)) > 0",
                        name="ck_geo_boundary_evidence"),
        ExcludeConstraint(("jurisdiction_id", "="),
                          (func.daterange(text("valid_from"), text("valid_until"), '[)'), "&&"),
                          name="ex_geo_boundary_overlap", using="gist",
                          ops={"jurisdiction_id": "public.gist_uuid_ops"}),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(ForeignKey("geographic_reference.id"), nullable=False)
    version_label: Mapped[str] = mapped_column(String(100), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    evidence_url: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_note: Mapped[str] = mapped_column(Text, nullable=False)


class GeographicResolutionContext(Base):
    """One immutable input manifest per digest, shared by many decisions."""
    __tablename__ = "geographic_resolution_context"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)


class GeographicResolution(Base):
    __tablename__ = "geographic_resolution"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_geo_resolution_supersedes"),
        UniqueConstraint("id", "observation_id", "reference_release_id", name="uq_geo_resolution_scope"),
        ForeignKeyConstraint(["supersedes_id", "observation_id", "reference_release_id"],
                             ["geographic_resolution.id", "geographic_resolution.observation_id",
                              "geographic_resolution.reference_release_id"], name="fk_geo_resolution_chain_scope"),
        ForeignKeyConstraint(["reference_id", "jurisdiction_id"],
                             ["geographic_reference.id", "geographic_reference.jurisdiction_id"],
                             name="fk_geo_resolution_identity"),
        CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id", name="ck_geo_resolution_not_self"),
        CheckConstraint("status IN ('RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS',"
                        "'UNRESOLVED','AMBIGUOUS','INVALID','OUT_OF_VINTAGE','PENDING_REVIEW',"
                        "'NON_COUNTY_CLASSIFIED')", name="ck_geo_resolution_status"),
        CheckConstraint("(status IN ('RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS') "
                        "AND jurisdiction_id IS NOT NULL AND reference_id IS NOT NULL) OR "
                        "(status NOT IN ('RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS') "
                        "AND jurisdiction_id IS NULL)", name="ck_geo_resolution_target"),
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
    context_sha256: Mapped[str | None] = mapped_column(ForeignKey("geographic_resolution_context.sha256"))


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
