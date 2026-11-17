"""Read the last verified current Senate snapshot, without upstream requests."""
import logging

from fastapi import APIRouter, HTTPException, Response

from app.api.senate_schemas import SenateResults
from app.api.elections import ReadSession
from app.services.senate_entities import enrich_snapshot
from app.services.senate_results import read_snapshot

LOG = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["senate"])


@router.get("/senate/2026/results", response_model=SenateResults)
def senate_results(response: Response, session: ReadSession) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return enrich_snapshot(session, read_snapshot())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOG.error("Senate snapshot unavailable", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "Senate results are unavailable while the daily cache is prepared or repaired.") from exc
