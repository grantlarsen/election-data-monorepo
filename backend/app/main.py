"""Electoral discovery and published results API."""

import asyncio
from contextlib import asynccontextmanager, suppress
import os

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.database import engine
from app.api.elections import router as election_router
from app.api.maps import router as map_router
from app.api.candidates import router as candidate_router
from app.api.senate import router as senate_router
from app.services.senate_results import daily_refresh
from app.api.house import router as house_router
from app.services.house_results import daily_refresh as daily_house_refresh


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(daily_refresh()) if os.getenv("SENATE_RESULTS_AUTO_REFRESH", "1") == "1" else None
    house_task = asyncio.create_task(daily_house_refresh()) if os.getenv("HOUSE_RESULTS_AUTO_REFRESH", "1") == "1" else None
    try:
        yield
    finally:
        for background_task in (task, house_task):
            if background_task:
                background_task.cancel()
        for background_task in (task, house_task):
            if background_task:
                with suppress(asyncio.CancelledError):
                    await background_task


app = FastAPI(title="Electoral Research API", version="0.1.0", lifespan=lifespan)

app.include_router(election_router)
app.include_router(map_router)
app.include_router(candidate_router)
app.include_router(senate_router)
app.include_router(house_router)


@app.get("/health")
def health():
    """Check whether FastAPI itself is running."""
    return {"status": "ok", "service": "electoral-api"}


@app.get("/health/db")
def database_health():
    """Check a real connection to PostgreSQL and the PostGIS extension."""
    try:
        with engine.connect() as conn:
            database = conn.execute(text("SELECT current_database()")).scalar_one()
            postgis = conn.execute(text("SELECT PostGIS_Version()")).scalar_one()
        return {"status": "ok", "database": database, "postgis_version": postgis}
    except Exception as exc:
        # Do not expose connection strings or internal database details to clients.
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
