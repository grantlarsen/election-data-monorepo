"""Source-specific House metadata and immutable district reconciliation evidence."""
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HouseReturnDetail(Base):
    __tablename__ = "house_return_detail"
    __table_args__ = (
        CheckConstraint("district_code ~ '^[0-9]{2}$'", name="ck_house_district_code"),
        CheckConstraint("stage IN ('GEN', 'PRI', 'RUNOFF')", name="ck_house_stage"),
    )
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("election_result_observation.id"), primary_key=True)
    district_code: Mapped[str] = mapped_column(String(2), nullable=False)
    stage: Mapped[str] = mapped_column(String(10), nullable=False)
    special: Mapped[bool] = mapped_column(Boolean, nullable=False)
    runoff: Mapped[bool] = mapped_column(Boolean, nullable=False)
    writein: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unofficial: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fusion_ticket: Mapped[bool] = mapped_column(Boolean, nullable=False)
    flags_json: Mapped[list] = mapped_column(JSONB, nullable=False)


class HouseDistrictReconciliation(Base):
    __tablename__ = "house_district_reconciliation"
    __table_args__ = (
        CheckConstraint("geoid ~ '^[0-9]{4}$'", name="ck_house_reconciliation_geoid"),
        CheckConstraint("source_rows > 0 AND canonical_votes >= 0", name="ck_house_reconciliation_counts"),
        CheckConstraint("status IN ('RECONCILED', 'EXCLUDED')", name="ck_house_reconciliation_status"),
    )
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_result_batch.id"), primary_key=True)
    geoid: Mapped[str] = mapped_column(String(4), primary_key=True)
    source_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    reported_total: Mapped[int | None] = mapped_column(BigInteger)
    source_category_sum: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_votes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    checks_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
