"""Read verified Governor counts without upstream downloads or database writes."""
import logging

from fastapi import APIRouter, HTTPException, Response

from app.api.governor_schemas import GovernorResults
from app.services.governor_results import read_snapshot
from app.api.elections import ReadSession
from app.services.governor_entities import enrich_snapshot

LOG = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["governor"])


@router.get("/governor/2026/results", response_model=GovernorResults)
def governor_results(response: Response, session: ReadSession) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return enrich_snapshot(session, read_snapshot())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOG.error("Governor snapshot unavailable", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "Governor results are unavailable while the daily cache is prepared or repaired.") from exc
