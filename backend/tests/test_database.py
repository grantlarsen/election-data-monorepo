"""PostgreSQL integration tests. Set TEST_DATABASE_URL to a disposable *test* database."""
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

import polars as pl
import pytest
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.engine import make_url

from app.database import Base
import app.models.core  # noqa: F401 - registers existing tables in Base.metadata
import app.models.ingestion  # noqa: F401 - registers ingest tables in Base.metadata
from app.models.ingestion import ElectionResultObservation, SourceActiveYear, SourceRelease
from ingestion.loader import DataQualityError, load, register_run
from ingestion.medsl import normalize, parse_csv
from ingestion.source import AcquiredFile, SourceInfo

FIXTURE = Path(__file__).parent / "fixtures" / "medsl_small.csv"


@pytest.fixture
def db_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for PostgreSQL integration tests")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end in _test to prevent accidental damage")
    name = "ingest_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={name}"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        admin.dispose()


def asset(version: str = "20.0") -> AcquiredFile:
    info = SourceInfo("medsl_presidential_county", "doi:10.7910/DVN/VOQCHQ", version, 13573089,
                      FIXTURE.name, "https://example.invalid/original.csv", None,
                      datetime.now(timezone.utc), {"fixture": True})
    return AcquiredFile(info, FIXTURE, "a" * 64 if version == "20.0" else "b" * 64,
                        datetime.now(timezone.utc))


def register(db_engine):
    run_id = uuid4()
    source_id = register_run(db_engine, run_id, "medsl_presidential_county",
                             "doi:10.7910/DVN/VOQCHQ", datetime.now(timezone.utc), {})
    return source_id, run_id


def imported(db_engine, source_id, run_id, df, version="20.0"):
    return load(db_engine, source_id, run_id, asset(version), df, set(df.get_column("year_int").to_list()),
                [], datetime.now(timezone.utc), datetime.now(timezone.utc), 5)


@pytest.mark.integration
def test_idempotence_and_linkage(db_engine):
    df = normalize(parse_csv(str(FIXTURE))).filter(pl.col("year_int") == 2000)
    source, run = register(db_engine)
    first = imported(db_engine, source, run, df)
    source2, run2 = register(db_engine)
    second = imported(db_engine, source2, run2, df)
    assert source == source2
    assert first.inserted == 6
    assert second.inserted == 0
    assert second.existing == 6
    with db_engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(ElectionResultObservation))
        active = conn.scalar(select(SourceActiveYear.release_id).where(SourceActiveYear.year == 2000))
        assert count == 6 and active is not None


@pytest.mark.integration
def test_version_changes_keep_history(db_engine, tmp_path):
    df = normalize(parse_csv(str(FIXTURE))).filter(pl.col("year_int") == 2000)
    source, run = register(db_engine)
    imported(db_engine, source, run, df)
    # Simulate an actual new upstream CSV, so raw content and normalized values agree.
    revised = tmp_path / "revision.csv"
    revised.write_text(FIXTURE.read_text().replace(",40,100,", ",42,100,", 1))
    new_df = normalize(parse_csv(str(revised))).filter(pl.col("year_int") == 2000)
    source2, run2 = register(db_engine)
    newer = imported(db_engine, source2, run2, new_df, version="21.0")
    assert newer.inserted == 6
    assert newer.updated == 6  # active rows replaced by new release, not SQL UPDATEs
    with db_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(SourceRelease)) == 2
        assert conn.scalar(select(func.count()).select_from(ElectionResultObservation)) == 12
        active = conn.scalar(select(SourceActiveYear.release_id).where(SourceActiveYear.year == 2000))
        votes = conn.scalar(select(ElectionResultObservation.candidate_votes).where(
            ElectionResultObservation.release_id == active,
            ElectionResultObservation.source_row_number == 2))
        assert votes == 42


@pytest.mark.integration
def test_transaction_rollback_on_major_drift(db_engine):
    df = normalize(parse_csv(str(FIXTURE))).filter(pl.col("year_int") == 2000)
    source, run = register(db_engine)
    imported(db_engine, source, run, df)
    with db_engine.connect() as conn:
        active_before = conn.scalar(select(SourceActiveYear.release_id).where(SourceActiveYear.year == 2000))
    source2, run2 = register(db_engine)
    with pytest.raises(DataQualityError, match="20%"):
        imported(db_engine, source2, run2, df.head(1), version="21.0")
    with db_engine.connect() as conn:
        assert conn.scalar(select(SourceActiveYear.release_id).where(SourceActiveYear.year == 2000)) == active_before
        assert conn.scalar(select(func.count()).select_from(ElectionResultObservation)) == 6
        assert conn.scalar(select(func.count()).select_from(SourceRelease)) == 1


@pytest.mark.integration
def test_rejection_audit_without_partial_import(db_engine):
    from app.models.ingestion import IngestionRejection, IngestionRun
    from ingestion.loader import finish_failed
    _, run = register(db_engine)
    finish_failed(db_engine, run, status="FAILED_VALIDATION",
                  completed_at=datetime.now(timezone.utc), duration_ms=20,
                  records_read=1, raw_sha256="f" * 64, warnings=[],
                  errors=[{"message": "negative vote count"}],
                  rejections=[{"source_row_number": 2,
                               "reasons_json": ["INVALID_CANDIDATE_VOTES"],
                               "raw_json": {"candidatevotes": "-1"}}])
    with db_engine.connect() as conn:
        audited = conn.execute(select(IngestionRun.status, IngestionRun.records_rejected)
                               .where(IngestionRun.id == run)).one()
        assert audited == ("FAILED_VALIDATION", 1)
        assert conn.scalar(select(func.count()).select_from(IngestionRejection)) == 1
        assert conn.scalar(select(func.count()).select_from(ElectionResultObservation)) == 0
