"""Read verified local House counts; requests never refresh upstream data."""
import logging

from fastapi import APIRouter, HTTPException, Response

from app.api.house_schemas import HouseBoundaries, HouseResults
from app.services.house_results import house_control, read_snapshot
from app.services.election_map import load_boundaries
from app.services.canonical_results import MaterializationError
from ingestion.current_house import BOUNDARY_RACES
from app.api.elections import ReadSession
from app.services.house_entities import enrich_snapshot

LOG = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["house"])


@router.get("/house/2026/boundaries", response_model=HouseBoundaries)
def house_boundaries() -> dict:
    """Verified local display geometry with election-scoped source joins; no downloads."""
    try:
        metadata, features = load_boundaries(None, 2026, "congressional_district")
        if metadata is None or {feature["id"] for feature in features} != set(BOUNDARY_RACES) | {"1198"}:
            raise ValueError("2026 House boundaries have not been prepared")
        return {"type": "FeatureCollection", "source": metadata, "features": [
            {**feature, "properties": {**feature["properties"], "race_id": BOUNDARY_RACES.get(feature["id"])}}
            for feature in features]}
    except (MaterializationError, OSError, ValueError, KeyError, TypeError) as exc:
        LOG.error("House boundaries unavailable", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "House map boundaries are unavailable. District tables and the grid remain available.") from exc


@router.get("/house/2026/results", response_model=HouseResults)
def house_results(response: Response, session: ReadSession) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        snapshot = read_snapshot()
        return enrich_snapshot(session, snapshot)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOG.error("House snapshot unavailable", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "House results are unavailable while the daily cache is prepared or repaired.") from exc
