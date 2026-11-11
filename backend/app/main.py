"""Minimal API for validating the electoral platform's local Docker stack."""

import os

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

app = FastAPI(title="Electoral Research API", version="0.1.0")

# Building the URL this way supports passwords containing special characters.
database_url = URL.create(
    drivername="postgresql+psycopg",
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.environ.get("DB_HOST", "db"),
    port=int(os.environ.get("DB_PORT", "5432")),
    database=os.environ["DB_NAME"],
)
engine = create_engine(database_url, pool_pre_ping=True)


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
