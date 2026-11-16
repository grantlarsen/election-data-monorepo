"""Reviewed append-only amendments to immutable source observation values."""
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CountyCorrectionBatch(Base):
    __tablename__='county_correction_batch'
    __table_args__=(UniqueConstraint('fingerprint',name='uq_county_correction_fingerprint'),
        CheckConstraint('election_year=2008',name='ck_county_correction_year'),
        CheckConstraint('correction_count>0',name='ck_county_correction_count'),
        CheckConstraint('length(trim(published_by))>0 AND length(trim(authorization_note))>0',name='ck_county_correction_actor'))
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    election_year: Mapped[int]=mapped_column(Integer,nullable=False)
    source_release_id: Mapped[UUID]=mapped_column(ForeignKey('source_release.id'),nullable=False)
    compared_source_release_id: Mapped[UUID]=mapped_column(ForeignKey('source_release.id'),nullable=False)
    compared_canonical_batch_id: Mapped[UUID]=mapped_column(ForeignKey('canonical_result_batch.id'),nullable=False)
    fingerprint: Mapped[str]=mapped_column(String(64),nullable=False)
    review_sha256: Mapped[str]=mapped_column(String(64),nullable=False)
    correction_count: Mapped[int]=mapped_column(Integer,nullable=False)
    vote_adjustment: Mapped[int]=mapped_column(BigInteger,nullable=False)
    published_by: Mapped[str]=mapped_column(String(100),nullable=False)
    authorization_note: Mapped[str]=mapped_column(Text,nullable=False)
    manifest_json: Mapped[dict]=mapped_column(JSONB,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)


class CountyVoteCorrection(Base):
    __tablename__='county_vote_correction'
    __table_args__=(UniqueConstraint('batch_id','observation_id',name='uq_county_correction_observation'),
        CheckConstraint('original_votes>=0 AND votes>=0 AND original_votes<>votes',name='ck_county_correction_votes'))
    id: Mapped[UUID]=mapped_column(primary_key=True,default=uuid4)
    batch_id: Mapped[UUID]=mapped_column(ForeignKey('county_correction_batch.id'),nullable=False)
    observation_id: Mapped[UUID]=mapped_column(ForeignKey('election_result_observation.id'),nullable=False)
    geographic_resolution_id: Mapped[UUID]=mapped_column(ForeignKey('geographic_resolution.id'),nullable=False)
    row_sha256: Mapped[str]=mapped_column(String(64),nullable=False)
    original_votes: Mapped[int]=mapped_column(BigInteger,nullable=False)
    votes: Mapped[int]=mapped_column(BigInteger,nullable=False)
    state_code: Mapped[str]=mapped_column(String(2),nullable=False)
    candidate_bucket: Mapped[str]=mapped_column(String(30),nullable=False)
    evidence_json: Mapped[dict]=mapped_column(JSONB,nullable=False)
