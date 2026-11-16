"""Election display route over a single consistent publication snapshot."""
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.elections import ReadSession
from app.api.map_schemas import MapFilters, MapResponse
from app.services.canonical_results import MaterializationError
from app.services.election_map import build_map

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["maps"])


@router.get("/election-map", response_model=MapResponse)
def election_map(filters: Annotated[MapFilters, Query()], session: ReadSession) -> dict:
    try:
        return build_map(session, filters)
    except (MaterializationError, ValueError) as exc:
        logger.error("Election map integrity validation failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "Map data failed integrity validation") from exc
