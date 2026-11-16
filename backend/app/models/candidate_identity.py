"""Pinned FEC records and durable, evidence-backed candidate matching decisions."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FecCandidateRecord(Base):
    __tablename__ = "fec_candidate_record"
    __table_args__ = (
        UniqueConstraint("release_id", "identifier_id", name="uq_fec_candidate_record"),
        CheckConstraint("office IN ('H', 'S', 'P')", name="ck_fec_candidate_office"),
        CheckConstraint("cycle >= 1788 AND cycle % 2 = 0", name="ck_fec_candidate_cycle"),
        Index("ix_fec_candidate_scope", "release_id", "election_year", "office", "state_code", "district"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    identifier_id: Mapped[UUID] = mapped_column(ForeignKey("external_identifier.id"), nullable=False)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    election_year: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    office: Mapped[str] = mapped_column(String(1), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    district: Mapped[str | None] = mapped_column(String(2))
    principal_committee: Mapped[str | None] = mapped_column(String(9))
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CandidateIdentityReview(Base):
    __tablename__ = "candidate_identity_review"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_candidate_review_key"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'unmatched')", name="ck_candidate_review_status"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_candidate_review_confidence"),
        CheckConstraint("(status = 'unmatched') = (record_id IS NULL)", name="ck_candidate_review_record"),
        CheckConstraint("status NOT IN ('accepted', 'rejected') OR (length(trim(actor)) > 0 AND actor IS NOT NULL AND length(trim(decision_evidence)) > 0 AND decision_evidence IS NOT NULL)", name="ck_candidate_review_decision"),
        Index("ix_candidate_review_queue", "status", "candidacy_id"),
        Index("uq_candidate_review_accepted", "candidacy_id", unique=True, postgresql_where=text("status = 'accepted'")),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidacy_id: Mapped[UUID] = mapped_column(ForeignKey("candidacy.id"), nullable=False)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    record_id: Mapped[UUID | None] = mapped_column(ForeignKey("fec_candidate_record.id"))
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actor: Mapped[str | None] = mapped_column(String(150))
    decision_evidence: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateFinanceSummary(Base):
    """One reported candidate summary, never summed across IDs or releases."""
    __tablename__ = "candidate_finance_summary"
    __table_args__ = (
        UniqueConstraint("release_id", "identifier_id", "cycle", name="uq_candidate_finance_release"),
        CheckConstraint("cycle >= 1788 AND cycle % 2 = 0", name="ck_candidate_finance_cycle"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    identifier_id: Mapped[UUID] = mapped_column(ForeignKey("external_identifier.id"), nullable=False)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    receipts: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    disbursements: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    transfers_from_authorized: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    transfers_to_authorized: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cash_on_hand: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    debts: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
