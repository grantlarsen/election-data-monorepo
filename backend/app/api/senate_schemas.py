"""Source-scoped provisional Senate read models, separate from canonical results."""
from typing import Literal

from pydantic import BaseModel
from app.api.media_schemas import CandidatePortrait


class SenateCandidate(BaseModel):
    portrait: CandidatePortrait | None = None
    name: str
    party: str
    votes: int
    share_pct: float | None
    source_share_pct: str
    outcome: Literal["", "leads", "won"]
    source_row_number: int
    candidacy_id: str | None = None
    kind: Literal["candidate", "aggregate"] = "candidate"
    incumbent: bool | None = None
    incumbent_evidence: dict | None = None


class SenateRace(BaseModel):
    id: str
    state_code: str
    state_name: str
    seat_class: int
    special: bool
    status: Literal["counting", "called", "final"]
    total_votes: int
    candidates: list[SenateCandidate]
    count_updated_at: str | None
    source_read_at: str
    called_at: str | None
    source: str
    source_url: str
    page_url: str
    contest_id: str | None = None
    summary_status: str | None = None
    leader: str | None = None
    margin_votes: int | None = None
    margin_pct: float | None = None


class ProvisionalSenateElection(BaseModel):
    race: SenateRace
    checked_at: str
    stale: bool
    sha256: str
    retrieved_at: str


class SenateControl(BaseModel):
    total_seats: int
    majority_threshold: int
    seats_up: int
    retained: dict[str, int]
    called: dict[str, int]
    totals: dict[str, int]
    unresolved: int
    democratic_aligned: int
    retained_democratic_aligned: int
    independent_democratic_caucus: int
    other_unaligned: int
    certified_contests: int
    control: Literal['D', 'R'] | None
    gains: dict[str, int]
    net_change: dict[str, int]
    baseline_as_of: str
    baseline_reviewed_at: str
    sources: list[str]


class SenateResults(BaseModel):
    control: SenateControl | None = None
    year: int
    election_date: str
    races: list[SenateRace]
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
