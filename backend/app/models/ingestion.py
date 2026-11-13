"""Append-only source observations and audit metadata; existing core models remain intact."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SourceRelease(Base):
    __tablename__ = "source_release"
    __table_args__ = (UniqueConstraint("source_id", "version", "sha256", name="uq_source_release_version_hash"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class IngestionRun(Base):
    __tablename__ = "ingestion_run"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"), nullable=False)
    release_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_release.id"))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    records_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    errors_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    options_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    raw_sha256: Mapped[str | None] = mapped_column(String(64))


class IngestionRejection(Base):
    __tablename__ = "ingestion_rejection"
    __table_args__ = (UniqueConstraint("run_id", "source_row_number", name="uq_ingestion_rejection_row"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("ingestion_run.id", ondelete="CASCADE"), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reasons_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ElectionResultObservation(Base):
    __tablename__ = "election_result_observation"
    __table_args__ = (
        UniqueConstraint("release_id", "source_row_number", name="uq_result_observation_source_row"),
        CheckConstraint("year >= 2000 AND year <= 2024", name="ck_observation_year"),
        CheckConstraint("candidate_votes IS NULL OR candidate_votes >= 0", name="ck_observation_votes"),
        CheckConstraint("total_votes IS NULL OR total_votes >= 0", name="ck_observation_total"),
        Index("ix_result_observation_year_state", "year", "state_code"),
        Index("ix_result_observation_release_year", "release_id", "year"),
        Index("ix_result_observation_county", "county_fips"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    row_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    logical_key: Mapped[str] = mapped_column(String(64), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    state_raw: Mapped[str | None] = mapped_column(Text)
    state_code_raw: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    state_fips: Mapped[str] = mapped_column(String(2), nullable=False)
    county_raw: Mapped[str | None] = mapped_column(Text)
    county_normalized: Mapped[str | None] = mapped_column(Text)
    county_fips_raw: Mapped[str | None] = mapped_column(Text)
    county_fips: Mapped[str | None] = mapped_column(String(5))
    office_raw: Mapped[str | None] = mapped_column(Text)
    candidate_raw: Mapped[str | None] = mapped_column(Text)
    candidate_normalized: Mapped[str | None] = mapped_column(Text)
    candidate_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    party_raw: Mapped[str | None] = mapped_column(Text)
    party_normalized: Mapped[str | None] = mapped_column(String(200))
    mode_raw: Mapped[str | None] = mapped_column(Text)
    mode_normalized: Mapped[str | None] = mapped_column(String(100))
    version_raw: Mapped[str | None] = mapped_column(Text)
    candidate_votes: Mapped[int | None] = mapped_column(BigInteger)
    total_votes: Mapped[int | None] = mapped_column(BigInteger)
    jurisdiction_id: Mapped[UUID | None] = mapped_column(ForeignKey("jurisdiction.id"))
    candidacy_id: Mapped[UUID | None] = mapped_column(ForeignKey("candidacy.id"))
    party_id: Mapped[UUID | None] = mapped_column(ForeignKey("political_party.id"))
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class SourceActiveYear(Base):
    """The active immutable release is independently selectable per election year."""
    __tablename__ = "source_active_year"
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("ingestion_run.id"), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
