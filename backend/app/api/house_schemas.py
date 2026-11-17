"""Provisional district results, separate from canonical vote publications."""
from typing import Literal

from pydantic import BaseModel
from app.api.media_schemas import CandidatePortrait


class HouseCandidate(BaseModel):
    portrait: CandidatePortrait | None = None
    candidacy_id: str | None = None
    kind: Literal['candidate', 'aggregate'] = 'candidate'
    incumbent: bool | None = None
    incumbent_evidence: dict | None = None
    name: str
    party: str
    votes: int | None
    share_pct: float | None
    source_share_pct: str
    outcome: Literal["", "leads", "won"]
    source_row_number: int


class HouseBoundaries(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[dict]
    source: dict


class HouseRace(BaseModel):
    contest_id: str | None = None
    id: str
    state_code: str
    state_name: str
    district_code: str
    status: Literal["counting", "called", "final"]
    total_votes: int | None
    candidates: list[HouseCandidate]
    count_updated_at: str | None
    source_read_at: str
    called_at: str | None
    source: str
    source_url: str
    page_url: str


class HouseControl(BaseModel):
    total_seats: int
    majority_threshold: int
    called: dict[str, int]
    unresolved: int
    control: Literal["D", "R"] | None


class HouseResults(BaseModel):
    year: int
    election_date: str
    races: list[HouseRace]
    expected_contests: int
    missing_districts: list[str]
    control: HouseControl
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


class ProvisionalHouseElection(BaseModel):
    race: HouseRace
    checked_at: str
    retrieved_at: str
    stale: bool
    sha256: str
