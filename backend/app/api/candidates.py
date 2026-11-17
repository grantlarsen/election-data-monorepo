"""Public read-only profiles; identity decisions are an operator CLI workflow."""
import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from app.api.candidate_schemas import CandidateProfile
from app.api.elections import ReadSession
from app.services.candidate_profiles import candidate_profile
from app.services.canonical_results import MaterializationError

router = APIRouter(prefix="/api/v1", tags=["candidates"])
logger = logging.getLogger(__name__)


@router.get("/candidates/{candidacy_id}", response_model=CandidateProfile)
def profile(candidacy_id: UUID, session: ReadSession,
            reporting_level: Literal["state", "county", "congressional_district", "legislative_district", "precinct", "place"] | None = None,
            limit: Annotated[int, Query(ge=1, le=200)] = 50,
            offset: Annotated[int, Query(ge=0)] = 0) -> dict:
    try:
        result = candidate_profile(session, candidacy_id, reporting_level=reporting_level, limit=limit, offset=offset)
    except MaterializationError as exc:
        logger.error("Candidate profile published result integrity check failed")
        raise HTTPException(503, "Published results failed integrity validation") from exc
    if result is None:
        raise HTTPException(404, "Candidacy not found")
    return result
