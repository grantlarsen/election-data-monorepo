"""Senate seat identities, source scope evidence and contest reconciliation."""
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SenateSeat(Base):
    __tablename__ = "senate_seat"
    __table_args__ = (
        UniqueConstraint("state_code", "seat_class", name="uq_senate_seat_state_class"),
        CheckConstraint("seat_class IN (1,2,3)", name="ck_senate_seat_class"),
        CheckConstraint("state_code ~ '^[A-Z]{2}$' AND state_code <> 'DC'", name="ck_senate_seat_state"),
    )
    office_id: Mapped[UUID] = mapped_column(ForeignKey("office.id"), primary_key=True)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False)
    seat_class: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_url: Mapped[str] = mapped_column(String(1000), nullable=False)


class SenateContest(Base):
    __tablename__ = "senate_contest"
    contest_id: Mapped[UUID] = mapped_column(ForeignKey("contest.id"), primary_key=True)
    scope_evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class SenateReturnDetail(Base):
    __tablename__ = "senate_return_detail"
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("election_result_observation.id"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    special: Mapped[bool] = mapped_column(Boolean, nullable=False)
    writein: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unofficial: Mapped[bool] = mapped_column(Boolean, nullable=False)


class SenateContestReconciliation(Base):
    __tablename__ = "senate_contest_reconciliation"
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_result_batch.id"), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    checks_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
