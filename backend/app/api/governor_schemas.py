"""Source-scoped provisional Governor read models; no inferred person identities."""
from typing import Literal

from pydantic import BaseModel
from app.api.media_schemas import CandidatePortrait


class GovernorCandidate(BaseModel):
    portrait: CandidatePortrait | None = None
    candidacy_id: str | None = None
    kind: Literal["candidate", "aggregate"] = "candidate"
    incumbent: bool | None = None
    incumbent_evidence: dict | None = None
    name: str
    party: str
    votes: int | None
    share_pct: float | None
    source_share_pct: str
    outcome: Literal["", "leads", "won"]
    source_row_number: int


class PreviousGovernorElection(BaseModel):
    year: int
    winner_name: str
    party: str
    source_url: str
    reviewed_at: str
    source_sha256: str


class GovernorRace(BaseModel):
    contest_id: str | None = None
    previous_election: PreviousGovernorElection | None = None
    flipped: bool | None = None
    id: str
    state_code: str
    state_name: str
    status: Literal["counting", "called", "final"]
    total_votes: int | None
    candidates: list[GovernorCandidate]
    count_updated_at: str | None
    source_read_at: str
    called_at: str | None
    source: str
    source_url: str
    page_url: str


class GovernorResults(BaseModel):
    year: int
    election_date: str
    races: list[GovernorRace]
    expected_contests: int
    missing_states: list[str]
    input_rows: int
    accepted_rows: int
    excluded_rows: int
    rejected_rows: int
    checked_at: str
    retrieved_at: str
    published_at: str
    next_refresh_at: str
    stale: bool
    refresh_failed: bool
    sha256: str
    ruleset: str
    source_url: str
    manifest_url: str


class ProvisionalGovernorElection(BaseModel):
    race: GovernorRace
    checked_at: str
    retrieved_at: str
    stale: bool
    sha256: str
