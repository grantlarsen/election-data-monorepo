"""Read-only routes over canonical entities and explicitly published returns."""
from collections.abc import Generator
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.api.election_schemas import (
    ContestItem, ElectionFilters, ElectionItem, Page, ResultFilters, ResultPage,
    StateResultPage,
)
from app.services import election_queries
from app.services.canonical_results import MaterializationError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["elections"], responses={
    503: {"description": "Database unavailable or published results failed integrity validation"},
})


def get_read_session() -> Generator[Session, None, None]:
    """Keep counts, pages and publication pointers in one PostgreSQL snapshot."""
    try:
        with SessionLocal() as session, session.begin():
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            yield session
    except SQLAlchemyError as exc:
        logger.error("Election API database operation failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "Database unavailable") from exc


ReadSession = Annotated[Session, Depends(get_read_session)]


@router.get("/elections", response_model=Page[ElectionItem])
def elections(filters: Annotated[ElectionFilters, Query()], session: ReadSession) -> dict:
    return election_queries.list_elections(session, filters)


@router.get("/contests", response_model=Page[ContestItem])
def contests(filters: Annotated[ElectionFilters, Query()], session: ReadSession) -> dict:
    return election_queries.list_contests(session, filters)


@router.get("/results", response_model=ResultPage)
def results(filters: Annotated[ResultFilters, Query()], session: ReadSession) -> dict:
    try:
        return election_queries.list_results(session, filters)
    except MaterializationError as exc:
        logger.error("Published election result integrity check failed")
        raise HTTPException(503, "Published results failed integrity validation") from exc


@router.get("/state-results", response_model=StateResultPage)
def state_results(filters: Annotated[ElectionFilters, Query()], session: ReadSession) -> dict:
    if filters.party_id is not None:
        raise HTTPException(422, "State authority uses source candidate buckets without canonical party links")
    try:
        return election_queries.list_state_results(session, filters)
    except ValueError as exc:
        logger.error("Published state authority integrity check failed")
        raise HTTPException(503, "Published state results failed integrity validation") from exc
