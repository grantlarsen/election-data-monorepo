"""Release-scoped FEC observations; canonical committees remain Organizations.

Candidate election years, two-year financial cycles and reporting periods are
different dimensions. Historical observations must not be summed across releases.
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, Numeric, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FecCommitteeRecord(Base):
    __tablename__ = "fec_committee_record"
    __table_args__ = (
        UniqueConstraint("release_id", "identifier_id", "cycle", name="uq_fec_committee_release_cycle"),
        CheckConstraint("cycle BETWEEN 1788 AND 9998 AND cycle % 2 = 0", name="ck_fec_committee_cycle"),
        CheckConstraint("length(trim(name)) > 0", name="ck_fec_committee_name"),
        Index("ix_fec_committee_identifier_cycle", "identifier_id", "cycle"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    identifier_id: Mapped[UUID] = mapped_column(ForeignKey("external_identifier.id"), nullable=False)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    committee_type: Mapped[str | None] = mapped_column(String(1))
    designation: Mapped[str | None] = mapped_column(String(1))
    filing_frequency: Mapped[str | None] = mapped_column(String(1))
    organization_type: Mapped[str | None] = mapped_column(String(1))
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class FecCandidateCommitteeLink(Base):
    """Source linkage, including unresolved candidates and missing committees.

    Reviewed canonical candidacy links use the existing CommitteeRelationship.
    A leadership PAC or joint fundraiser link does not imply authorization.
    """
    __tablename__ = "fec_candidate_committee_link"
    __table_args__ = (
        UniqueConstraint("release_id", "linkage_id", name="uq_fec_committee_link_release"),
        CheckConstraint("cycle BETWEEN 1788 AND 9998 AND cycle % 2 = 0", name="ck_fec_committee_link_cycle"),
        CheckConstraint("election_year BETWEEN 1788 AND 9999", name="ck_fec_committee_link_election_year"),
        CheckConstraint("linkage_id > 0", name="ck_fec_committee_link_number"),
        Index("ix_fec_committee_link_candidate_cycle", "candidate_identifier_id", "cycle"),
        Index("ix_fec_committee_link_committee_cycle", "committee_identifier_id", "cycle"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    linkage_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_identifier_id: Mapped[UUID] = mapped_column(ForeignKey("external_identifier.id"), nullable=False)
    committee_identifier_id: Mapped[UUID | None] = mapped_column(ForeignKey("external_identifier.id"))
    cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    election_year: Mapped[int] = mapped_column(Integer, nullable=False)
    committee_type: Mapped[str | None] = mapped_column(String(1))
    designation: Mapped[str | None] = mapped_column(String(1))
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CommitteeFiling(Base):
    __tablename__ = "committee_filing"
    __table_args__ = (
        UniqueConstraint("release_id", "source_record_key", name="uq_committee_filing_source_record"),
        UniqueConstraint("release_id", "file_number", name="uq_committee_filing_release_number"),
        UniqueConstraint("id", "committee_identifier_id", "cycle", "release_id", "coverage_start", "coverage_end", name="uq_committee_filing_scope"),
        UniqueConstraint("id", "committee_identifier_id", "cycle", name="uq_committee_filing_lineage_scope"),
        ForeignKeyConstraint(
            ["supersedes_id", "committee_identifier_id", "cycle"],
            ["committee_filing.id", "committee_filing.committee_identifier_id", "committee_filing.cycle"],
            name="fk_committee_filing_predecessor"),
        CheckConstraint("cycle BETWEEN 1788 AND 9998 AND cycle % 2 = 0", name="ck_committee_filing_cycle"),
        CheckConstraint("length(trim(source_record_key)) > 0", name="ck_committee_filing_source_key"),
        CheckConstraint("coverage_start IS NULL OR coverage_end IS NULL OR coverage_start <= coverage_end", name="ck_committee_filing_dates"),
        CheckConstraint("file_number IS NULL OR file_number > 0", name="ck_committee_filing_number"),
        CheckConstraint("previous_file_number IS NULL OR previous_file_number > 0", name="ck_committee_filing_previous_number"),
        CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id", name="ck_committee_filing_not_self"),
        Index("ix_committee_filing_committee_cycle", "committee_identifier_id", "cycle"),
        Index("ix_committee_filing_file_number", "file_number"),
        Index("ix_committee_filing_supersedes", "supersedes_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(200), nullable=False)
    committee_identifier_id: Mapped[UUID] = mapped_column(ForeignKey("external_identifier.id"), nullable=False)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    file_number: Mapped[int | None] = mapped_column(BigInteger)
    previous_file_number: Mapped[int | None] = mapped_column(BigInteger)
    supersedes_id: Mapped[UUID | None] = mapped_column()
    form_type: Mapped[str] = mapped_column(String(10), nullable=False)
    report_type: Mapped[str | None] = mapped_column(String(10))
    amendment_indicator: Mapped[str | None] = mapped_column(String(1))
    # Source assertion at retrieval time; NULL never means final/current.
    is_amended: Mapped[bool | None] = mapped_column(Boolean)
    receipt_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_start: Mapped[date | None] = mapped_column(Date)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CommitteeFinanceSnapshot(Base):
    """Reported USD amounts, with missing values and signed corrections intact."""
    __tablename__ = "committee_finance_snapshot"
    __table_args__ = (
        UniqueConstraint("release_id", "source_record_key", name="uq_committee_finance_source_record"),
        UniqueConstraint("filing_id", name="uq_committee_finance_filing"),
        UniqueConstraint("id", "committee_identifier_id", "cycle", "period_kind", "coverage_start", "coverage_end", name="uq_committee_finance_lineage_scope"),
        ForeignKeyConstraint(
            ["filing_id", "committee_identifier_id", "cycle", "release_id", "coverage_start", "coverage_end"],
            ["committee_filing.id", "committee_filing.committee_identifier_id", "committee_filing.cycle", "committee_filing.release_id", "committee_filing.coverage_start", "committee_filing.coverage_end"],
            name="fk_committee_finance_filing_scope"),
        ForeignKeyConstraint(
            ["supersedes_id", "committee_identifier_id", "cycle", "period_kind", "coverage_start", "coverage_end"],
            ["committee_finance_snapshot.id", "committee_finance_snapshot.committee_identifier_id", "committee_finance_snapshot.cycle", "committee_finance_snapshot.period_kind", "committee_finance_snapshot.coverage_start", "committee_finance_snapshot.coverage_end"],
            name="fk_committee_finance_predecessor"),
        CheckConstraint("cycle BETWEEN 1788 AND 9998 AND cycle % 2 = 0", name="ck_committee_finance_cycle"),
        CheckConstraint("length(trim(source_record_key)) > 0", name="ck_committee_finance_source_key"),
        CheckConstraint("period_kind IN ('report', 'cycle')", name="ck_committee_finance_period_kind"),
        CheckConstraint("(period_kind = 'report') = (filing_id IS NOT NULL)", name="ck_committee_finance_filing_kind"),
        CheckConstraint("coverage_start <= coverage_end", name="ck_committee_finance_dates"),
        CheckConstraint("period_kind <> 'cycle' OR (coverage_start >= make_date(cycle - 1, 1, 1) AND coverage_end <= make_date(cycle, 12, 31))", name="ck_committee_finance_cycle_dates"),
        CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id", name="ck_committee_finance_not_self"),
        Index("ix_committee_finance_scope", "committee_identifier_id", "cycle", "release_id", "period_kind"),
        Index("ix_committee_finance_supersedes", "supersedes_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(200), nullable=False)
    committee_identifier_id: Mapped[UUID] = mapped_column(ForeignKey("external_identifier.id"), nullable=False)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    period_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    coverage_start: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_end: Mapped[date] = mapped_column(Date, nullable=False)
    filing_id: Mapped[UUID | None] = mapped_column()
    supersedes_id: Mapped[UUID | None] = mapped_column()
    receipts: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    disbursements: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cash_on_hand_begin: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cash_on_hand_end: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    debts_owed_by: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    debts_owed_to: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    transfers_from_authorized: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    transfers_to_authorized: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    independent_expenditures: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
