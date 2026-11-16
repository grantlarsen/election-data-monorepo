"""Typed candidate profile contract. Monetary values serialize as exact decimals."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from app.api.election_schemas import Geography, ResultPage, Source


class PersonIdentity(BaseModel):
    id: UUID
    full_name: str


class IdentityEvidence(BaseModel):
    status: Literal["pending", "accepted", "rejected", "unmatched"]
    confidence: Decimal
    evidence: dict
    decision_evidence: str | None
    decided_at: datetime | None
    record_id: UUID | None
    fec_candidate_id: str | None
    source: Source


class Identifier(BaseModel):
    namespace: str
    identifier_type: str
    value: str
    evidence: str | None
    source: Source | None
    source_id: UUID


class Committee(BaseModel):
    id: UUID
    name: str
    role: str
    cycle: int
    fec_ids: list[str]
    evidence: str | None
    source_record_key: str | None
    source: Source | None
    source_id: UUID


class CandidateContest(BaseModel):
    id: UUID
    election_id: UUID
    election_date: date
    stage: str
    election_cycle: int
    office_name: str
    jurisdiction: Geography


class LatestElection(CandidateContest):
    candidacy_id: UUID


class CandidateFinance(BaseModel):
    status: Literal["available", "partial", "missing", "identity_unresolved", "ambiguous"]
    cycle: int
    currency: Literal["USD"] = "USD"
    total_raised: Decimal | None = None
    total_spent: Decimal | None = None
    reported_receipts: Decimal | None = None
    reported_disbursements: Decimal | None = None
    transfers_from_authorized: Decimal | None = None
    transfers_to_authorized: Decimal | None = None
    cash_on_hand: Decimal | None = None
    debts: Decimal | None = None
    coverage_end: date | None = None
    definition: str | None = None
    fec_candidate_id: str | None = None
    source: Source | None = None


class CandidateProfile(BaseModel):
    id: UUID
    label: str | None
    source_label: str | None
    candidate_kind: str
    person: PersonIdentity | None
    identity_status: Literal["resolved", "pending_review", "unresolved"]
    identity_evidence: list[IdentityEvidence]
    identifiers: list[Identifier]
    contest: CandidateContest
    latest_election: LatestElection | None = None
    committees: list[Committee]
    finance: CandidateFinance
    results: ResultPage
