"""Read-only display contract. Votes are reported votes, never turnout."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.election_schemas import ElectionFilters, Publication, Stage


class MapFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(2008, ge=1, le=9998)
    office: str = Field("U.S. President", min_length=1, max_length=200)
    stage: Stage = "general"
    state_code: str | None = None
    jurisdiction_id: UUID | None = None
    reporting_level: Literal['state', 'county', 'congressional_district'] | None = None

    @field_validator("state_code")
    @classmethod
    def state(cls, value: str | None) -> str | None:
        return ElectionFilters(state_code=value).state_code


class MapCandidate(BaseModel):
    label: str
    kind: str
    votes: int
    share: float | None
    candidacy_id: UUID | None = None
    geographic_reference_id: UUID | None = None
    reference_vintage_start: int | None = None
    reference_vintage_end: int | None = None
    observation_ids: list[UUID] = Field(default_factory=list)
    correction_ids: list[UUID] = Field(default_factory=list)


class MapSummary(BaseModel):
    status: Literal["available", "tie", "zero_total", "indeterminate", "no_results"]
    total_votes: int | None
    leader: str | None
    margin_votes: int | None
    margin_pp: float | None
    candidates: list[MapCandidate]


class MapUnit(BaseModel):
    id: str
    geoid: str | None
    name: str
    state_code: str
    jurisdiction_id: UUID | None
    contest_id: UUID | None
    publication_batch_id: UUID | None
    has_geometry: bool
    geometry_match: Literal['matched', 'boundary_only', 'missing_reference', 'missing_geometry']
    summary: MapSummary


class MapResponse(BaseModel):
    year: int
    office: str
    stage: str
    reporting_level: Literal["state", "county", "congressional_district"]
    drill_down_level: Literal['county'] | None
    state_code: str | None
    selected_jurisdiction_id: UUID | None
    availability: Literal["available", "no_matching_published_results", "unsupported_selection", "boundaries_unavailable"]
    boundary: dict | None
    features: dict
    units: list[MapUnit]
    publications: list[Publication]
    coverage: dict[str, int]
    metric_note: str
    source_note: str
