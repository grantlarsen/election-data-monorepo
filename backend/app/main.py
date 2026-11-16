"""Electoral discovery and published results API."""

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.database import engine
from app.api.elections import router as election_router

app = FastAPI(title="Electoral Research API", version="0.1.0")

app.include_router(election_router)


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
