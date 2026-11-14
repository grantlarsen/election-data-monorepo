"""DATA-003 canonical election architecture; never replaces immutable observations."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey,
                        Index, Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Office(Base):
    __tablename__ = "office"
    __table_args__ = (
        UniqueConstraint("creation_key", name="uq_office_creation_key"),
        CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until", name="ck_office_dates"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    creation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    jurisdiction_id: Mapped[UUID | None] = mapped_column(ForeignKey("jurisdiction.id"), index=True)
    office_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)


class OfficeTerm(Base):
    __tablename__ = "office_term"
    __table_args__ = (
        UniqueConstraint("creation_key", name="uq_office_term_creation_key"),
        CheckConstraint("start_date < end_date", name="ck_office_term_dates"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    creation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    office_id: Mapped[UUID] = mapped_column(ForeignKey("office.id"), index=True, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    seat_label: Mapped[str | None] = mapped_column(String(100))
    predecessor_id: Mapped[UUID | None] = mapped_column(ForeignKey("office_term.id"))


class BallotLine(Base):
    __tablename__ = "ballot_line"
    __table_args__ = (
        UniqueConstraint("creation_key", name="uq_ballot_line_creation_key"),
        CheckConstraint("line_kind IN ('party', 'independent', 'write_in', 'unaffiliated', 'other')", name="ck_ballot_line_kind"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    creation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    candidacy_id: Mapped[UUID] = mapped_column(ForeignKey("candidacy.id"), index=True, nullable=False)
    party_id: Mapped[UUID | None] = mapped_column(ForeignKey("political_party.id"), index=True)
    line_label: Mapped[str] = mapped_column(String(200), nullable=False)
    line_kind: Mapped[str] = mapped_column(String(30), nullable=False)


class CanonicalResultBatch(Base):
    """Immutable named attempt, source/release/geography selection fingerprint."""
    __tablename__ = "canonical_result_batch"
    __table_args__ = (
        UniqueConstraint("scope_key", "fingerprint", name="uq_canonical_batch_scope_fingerprint"),
        CheckConstraint("status IN ('COMPLETE', 'PARTIAL')", name="ck_canonical_batch_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    reference_release_id: Mapped[UUID] = mapped_column(ForeignKey("source_release.id"), nullable=False)
    election_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    input_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_votes_nonadditive: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_votes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_result_batch.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CanonicalPublication(Base):
    """Mutable *pointer* only: old batches and returns remain immutable."""
    __tablename__ = "canonical_publication"

    scope_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_result_batch.id"), nullable=False, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CanonicalVoteReturn(Base):
    """An immutable additive source-backed observation at exactly one reporting mode/grain.

    Source observation is 1:1 per batch; no cross-mode aggregation is implicit.
    A ballot-line vote has a ballot_line_id. A candidate-total vote does not.
    """
    __tablename__ = "canonical_vote_return"
    __table_args__ = (
        UniqueConstraint("batch_id", "observation_id", name="uq_canonical_vote_observation"),
        CheckConstraint("votes >= 0", name="ck_canonical_vote_nonnegative"),
        CheckConstraint("vote_kind IN ('candidate_total', 'ballot_line', 'write_in', 'aggregate')", name="ck_canonical_vote_kind"),
        CheckConstraint("(vote_kind = 'ballot_line') = (ballot_line_id IS NOT NULL)", name="ck_canonical_vote_line_presence"),
        CheckConstraint("(vote_kind IN ('candidate_total', 'ballot_line') AND candidacy_id IS NOT NULL) OR (vote_kind = 'aggregate' AND candidacy_id IS NULL) OR vote_kind = 'write_in'", name="ck_canonical_vote_candidate_presence"),
        Index("ix_canonical_return_contest_geo", "contest_id", "jurisdiction_id", "reporting_mode"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_result_batch.id"), nullable=False, index=True)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("election_result_observation.id"), nullable=False)
    contest_id: Mapped[UUID] = mapped_column(ForeignKey("contest.id"), nullable=False)
    jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey("jurisdiction.id"), nullable=False)
    geographic_resolution_id: Mapped[UUID] = mapped_column(ForeignKey("geographic_resolution.id"), nullable=False)
    candidacy_id: Mapped[UUID | None] = mapped_column(ForeignKey("candidacy.id"))
    ballot_line_id: Mapped[UUID | None] = mapped_column(ForeignKey("ballot_line.id"))
    source_label: Mapped[str] = mapped_column(Text, nullable=False)
    reporting_level: Mapped[str] = mapped_column(String(40), nullable=False)
    reporting_mode: Mapped[str] = mapped_column(String(100), nullable=False)
    vote_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    votes: Mapped[int] = mapped_column(BigInteger, nullable=False)


class CanonicalMaterializationIssue(Base):
    __tablename__ = "canonical_materialization_issue"
    __table_args__ = (
        UniqueConstraint("batch_id", "observation_id", "code", name="uq_canonical_issue_row_code"),
        Index("ix_canonical_issue_batch_code", "batch_id", "code"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_result_batch.id"), nullable=False)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("election_result_observation.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
