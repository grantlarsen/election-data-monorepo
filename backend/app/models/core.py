
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Person(Base):
    __tablename__ = "person"
    __table_args__ = (UniqueConstraint("creation_key", name="uq_person_creation_key"),)

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    full_name: Mapped[str] = mapped_column(String(200))
    # Nullable for pre-DATA-002 people; required by idempotent identity service.
    creation_key: Mapped[str | None] = mapped_column(String(200))


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
    __table_args__ = (
        UniqueConstraint("creation_key", name="uq_election_creation_key"),
        CheckConstraint("election_type IN ('general', 'primary', 'runoff', 'special', 'special_primary', 'special_runoff', 'other')", name="ck_election_type"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    election_date: Mapped[date] = mapped_column(Date)
    election_type: Mapped[str] = mapped_column(String(50))
    creation_key: Mapped[str | None] = mapped_column(String(200))
    election_cycle: Mapped[int | None] = mapped_column()
    parent_election_id: Mapped[UUID | None] = mapped_column(ForeignKey("election.id"))

    jurisdiction_id: Mapped[UUID] = mapped_column(
        ForeignKey("jurisdiction.id"), index=True
    )


class Contest(Base):
    __tablename__ = "contest"
    __table_args__ = (UniqueConstraint("creation_key", name="uq_contest_creation_key"),)

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    office_name: Mapped[str] = mapped_column(String(200))
    creation_key: Mapped[str | None] = mapped_column(String(200))
    office_id: Mapped[UUID | None] = mapped_column(ForeignKey("office.id"), index=True)
    office_term_id: Mapped[UUID | None] = mapped_column(ForeignKey("office_term.id"))
    preceding_contest_id: Mapped[UUID | None] = mapped_column(ForeignKey("contest.id"))
    nomination_party_id: Mapped[UUID | None] = mapped_column(ForeignKey("political_party.id"))

    election_id: Mapped[UUID] = mapped_column(
        ForeignKey("election.id"), index=True
    )
    jurisdiction_id: Mapped[UUID] = mapped_column(
        ForeignKey("jurisdiction.id"), index=True
    )


class Candidacy(Base):
    __tablename__ = "candidacy"
    __table_args__ = (
        UniqueConstraint("creation_key", name="uq_candidacy_creation_key"),
        CheckConstraint("candidate_kind IN ('candidate', 'write_in', 'aggregate', 'unresolved')", name="ck_candidacy_kind"),
        CheckConstraint("person_id IS NOT NULL OR (source_label IS NOT NULL AND length(trim(source_label)) > 0)", name="ck_candidacy_evidence"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4
    )
    person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("person.id"), index=True
    )
    creation_key: Mapped[str | None] = mapped_column(String(200))
    source_label: Mapped[str | None] = mapped_column(Text)
    candidate_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="candidate", server_default="candidate")
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
