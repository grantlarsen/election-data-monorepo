
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Person(Base):
    __tablename__ = "person"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    full_name: Mapped[str] = mapped_column(String(200))


class PoliticalParty(Base):
    __tablename__ = "political_party"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(
        String(200), unique=True
    )


class Jurisdiction(Base):
    __tablename__ = "jurisdiction"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(50))
    state_code: Mapped[str | None] = mapped_column(
        String(2)
    )


class Election(Base):
    __tablename__ = "election"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    election_date: Mapped[date] = mapped_column(Date)
    election_type: Mapped[str] = mapped_column(String(50))

    jurisdiction_id: Mapped[UUID] = mapped_column(
        ForeignKey("jurisdiction.id"), index=True
    )


class Contest(Base):
    __tablename__ = "contest"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    office_name: Mapped[str] = mapped_column(String(200))

    election_id: Mapped[UUID] = mapped_column(
        ForeignKey("election.id"), index=True
    )
    jurisdiction_id: Mapped[UUID] = mapped_column(
        ForeignKey("jurisdiction.id"), index=True
    )


class Candidacy(Base):
    __tablename__ = "candidacy"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    person_id: Mapped[UUID] = mapped_column(
        ForeignKey("person.id"), index=True
    )
    contest_id: Mapped[UUID] = mapped_column(
        ForeignKey("contest.id"), index=True
    )
    party_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("political_party.id"), index=True
    )


class DataSource(Base):
    __tablename__ = "data_source"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(
        String(200), unique=True
    )
    url: Mapped[str | None] = mapped_column(
        String(1000)
    )


class ElectionResultSnapshot(Base):
    __tablename__ = "election_result_snapshot"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    candidacy_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidacy.id"), index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_source.id"), index=True
    )
    votes: Mapped[int] = mapped_column(BigInteger)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
