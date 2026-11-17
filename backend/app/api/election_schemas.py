"""Public election contracts; source buckets never imply canonical identities."""
from datetime import date, datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ingestion.medsl import STATE_NAMES

Stage = Literal["general", "primary", "runoff", "special", "special_primary", "special_runoff", "other"]


class ElectionFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)
    year: int | None = Field(None, ge=1, le=9998, description="Calendar year of election_date, not election cycle")
    office: str | None = Field(None, min_length=1, max_length=200, description="Exact office name, case insensitive")
    office_id: UUID | None = None
    seat_class: int | None = Field(None, ge=1, le=3, description="U.S. Senate seat class")
    stage: Stage | None = None
    party_id: UUID | None = Field(None, description="Candidate affiliation or ballot-line party; retains the whole candidate total")
    state_code: str | None = None
    jurisdiction_id: UUID | None = None
    election_id: UUID | None = None
    contest_id: UUID | None = None

    @field_validator("state_code")
    @classmethod
    def valid_state(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.upper()
            if value not in STATE_NAMES:
                raise ValueError("Unknown US state or DC code")
        return value

    @field_validator("office")
    @classmethod
    def valid_office(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Office must not be blank")
        return value


class ResultFilters(ElectionFilters):
    reporting_level: Literal["state", "county", "congressional_district", "legislative_district", "precinct", "place"] = "county"
    reporting_mode: str = Field("TOTAL", min_length=1, max_length=100)


class Geography(BaseModel):
    id: UUID
    name: str
    level: str
    state_code: str | None


class Source(BaseModel):
    release_id: UUID
    name: str
    version: str
    sha256: str
    url: str
    retrieved_at: datetime


class Publication(BaseModel):
    batch_id: UUID
    scope_key: str
    status: Literal["COMPLETE", "PARTIAL"]
    published_at: datetime
    source: Source
    reporting_levels: list[str]
    reporting_modes: list[str]
    reference_release_id: UUID | None = None
    correction_batch_id: UUID | None = None
    correction_source: Source | None = None
    input_rows: int | None = None
    accepted_rows: int | None = None
    excluded_rows: int | None = None
    coverage_scope: Literal["publication"] = "publication"
    county_coverage_verified: bool = False


class ElectionItem(BaseModel):
    id: UUID
    election_date: date
    stage: Stage
    election_cycle: int | None
    parent_election_id: UUID | None
    jurisdiction: Geography
    publications: list[Publication]


class ContestItem(BaseModel):
    id: UUID
    election_id: UUID
    election_date: date
    stage: Stage
    office_id: UUID | None
    office_name: str
    office_term_id: UUID | None
    seat_class: int | None = None
    nomination_party_id: UUID | None
    preceding_contest_id: UUID | None
    jurisdiction: Geography
    publications: list[Publication]


class ResultItem(BaseModel):
    contest_id: UUID
    election_id: UUID
    election_date: date
    stage: Stage
    office_id: UUID | None
    office_name: str
    seat_class: int | None = None
    jurisdiction: Geography
    reporting_level: str
    reporting_mode: str
    candidacy_id: UUID | None
    person_id: UUID | None
    candidate_kind: str
    label: str
    party_ids: list[UUID]
    basis: Literal["candidate_total", "ballot_line", "write_in", "aggregate"]
    votes: int
    geographic_reference_id: UUID
    reference_vintage_start: int
    reference_vintage_end: int
    observation_ids: list[UUID]
    correction_ids: list[UUID]
    publication: Publication


class StateResultItem(BaseModel):
    contest_id: UUID
    election_id: UUID
    election_date: date
    jurisdiction: Geography
    candidate_bucket: str
    bucket_kind: Literal["source_candidate", "aggregate"]
    votes: int
    source_locator: str
    source_adjustment: int | None
    publication: Publication


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
    has_more: bool
    availability: Literal["available", "no_matching_data", "no_matching_published_results"]


class ResultPage(Page[ResultItem]):
    reporting_level: str
    reporting_mode: str
    additive_with_state_results: bool = False


class StateResultPage(Page[StateResultItem]):
    reporting_level: Literal["state"] = "state"
    reporting_mode: Literal["TOTAL"] = "TOTAL"
    additive_with_county_returns: bool = False
