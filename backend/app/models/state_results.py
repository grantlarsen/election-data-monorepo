"""Source-authoritative state results, separate from county-grain returns."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey,
    ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from ingestion.medsl import STATE_NAMES


class StateResultBatch(Base):
    __tablename__ = 'state_result_batch'
    __table_args__ = (
        UniqueConstraint('scope_key','fingerprint',name='uq_state_batch_fingerprint'),
        UniqueConstraint('id','scope_key',name='uq_state_batch_scope'),
        ForeignKeyConstraint(['supersedes_id','scope_key'],
            ['state_result_batch.id','state_result_batch.scope_key'],name='fk_state_batch_predecessor_scope'),
        CheckConstraint('election_year = 2008',name='ck_state_batch_year'),
        CheckConstraint("scope_key = 'president:general:2008:state:TOTAL'",name='ck_state_batch_scope'),
        CheckConstraint('length(trim(published_by)) > 0 AND length(trim(authorization_note)) > 0',name='ck_state_batch_authorization'),
        CheckConstraint('supersedes_id IS NULL OR supersedes_id <> id',name='ck_state_batch_not_self'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True,default=uuid4)
    scope_key: Mapped[str] = mapped_column(String(200),nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64),nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(64),nullable=False)
    election_year: Mapped[int] = mapped_column(Integer,nullable=False)
    source_release_id: Mapped[UUID] = mapped_column(ForeignKey('source_release.id'),nullable=False)
    compared_source_release_id: Mapped[UUID] = mapped_column(ForeignKey('source_release.id'),nullable=False)
    compared_canonical_batch_id: Mapped[UUID] = mapped_column(ForeignKey('canonical_result_batch.id'),nullable=False)
    published_by: Mapped[str] = mapped_column(String(100),nullable=False)
    authorization_note: Mapped[str] = mapped_column(Text,nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSONB,nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)


class StateVoteReturn(Base):
    __tablename__ = 'state_vote_return'
    __table_args__ = (
        CheckConstraint('state_code IN ('+','.join(repr(s) for s in sorted(STATE_NAMES))+')',name='ck_state_return_state'),
        CheckConstraint("candidate_bucket IN ('BARACK OBAMA','JOHN MCCAIN','OTHER')",name='ck_state_return_bucket'),
        CheckConstraint('votes >= 0 AND medsl_source_votes >= 0 AND medsl_county_votes >= 0',name='ck_state_return_nonnegative'),
        CheckConstraint('votes = medsl_source_votes + source_adjustment',name='ck_state_return_adjustment'),
    )
    batch_id: Mapped[UUID] = mapped_column(ForeignKey('state_result_batch.id'),primary_key=True)
    state_code: Mapped[str] = mapped_column(String(2),primary_key=True)
    candidate_bucket: Mapped[str] = mapped_column(String(30),primary_key=True)
    jurisdiction_id: Mapped[UUID] = mapped_column(ForeignKey('jurisdiction.id'),nullable=False)
    contest_id: Mapped[UUID] = mapped_column(ForeignKey('contest.id'),nullable=False)
    votes: Mapped[int] = mapped_column(BigInteger,nullable=False)
    medsl_source_votes: Mapped[int] = mapped_column(BigInteger,nullable=False)
    medsl_county_votes: Mapped[int] = mapped_column(BigInteger,nullable=False)
    source_adjustment: Mapped[int] = mapped_column(BigInteger,nullable=False)
    source_locator: Mapped[str] = mapped_column(Text,nullable=False)
    components_json: Mapped[list] = mapped_column(JSONB,nullable=False)


class StateResultPublication(Base):
    __tablename__ = 'state_result_publication'
    __table_args__ = (
        ForeignKeyConstraint(['batch_id','scope_key'],
            ['state_result_batch.id','state_result_batch.scope_key'],name='fk_state_publication_scope'),
        UniqueConstraint('batch_id',name='uq_state_publication_batch'),
    )
    scope_key: Mapped[str] = mapped_column(String(200),primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
