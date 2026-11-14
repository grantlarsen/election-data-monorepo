"""Fast ORM validation regression tests; no Census download or PostgreSQL needed.

SQLite tables mirror the handful of geographic columns to exercise SQLAlchemy's
ORM model loading without creating the full PostgreSQL-specific metadata schema.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("polars")
from sqlalchemy import create_engine, insert

from app.models.geography import (
    GeographicReference,
    JurisdictionIdentifier,
    JurisdictionRelationship,
)
from ingestion.geography.quality import validate_loaded_reference


@pytest.fixture
def reference_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        # Only the three mapped tables queried by validate_loaded_reference().
        # Generic CHAR(32) columns store SQLAlchemy's UUID values in SQLite.
        conn.exec_driver_sql("""
            CREATE TABLE geographic_reference (
                id CHAR(32) PRIMARY KEY,
                release_id CHAR(32) NOT NULL,
                jurisdiction_id CHAR(32) NOT NULL,
                kind VARCHAR(20) NOT NULL,
                geoid VARCHAR(5) NOT NULL,
                state_fips VARCHAR(2) NOT NULL,
                name_raw TEXT NOT NULL,
                name_key TEXT NOT NULL,
                vintage_start INTEGER NOT NULL,
                vintage_end INTEGER NOT NULL,
                source_row_number INTEGER,
                note TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE jurisdiction_identifier (
                id CHAR(32) PRIMARY KEY,
                jurisdiction_id CHAR(32) NOT NULL,
                reference_id CHAR(32) NOT NULL,
                scheme VARCHAR(30) NOT NULL,
                value VARCHAR(5) NOT NULL,
                valid_from DATE,
                valid_until DATE,
                validity_evidence_url TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE jurisdiction_relationship (
                id CHAR(32) PRIMARY KEY,
                parent_id CHAR(32) NOT NULL,
                child_id CHAR(32) NOT NULL,
                reference_id CHAR(32) NOT NULL,
                relationship VARCHAR(30) NOT NULL,
                valid_from DATE,
                valid_until DATE,
                validity_evidence_url TEXT
            )
        """)
    try:
        yield engine
    finally:
        engine.dispose()


def insert_sample(engine, *, wrong_parent=False):
    release_id = uuid4()
    state_reference_id, county_reference_id = uuid4(), uuid4()
    state_jurisdiction_id, county_jurisdiction_id = uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(insert(GeographicReference), [
            dict(id=state_reference_id, release_id=release_id,
                 jurisdiction_id=state_jurisdiction_id, kind="state", geoid="01",
                 state_fips="01", name_raw="Alabama", name_key="ALABAMA",
                 vintage_start=2017, vintage_end=2021),
            dict(id=county_reference_id, release_id=release_id,
                 jurisdiction_id=county_jurisdiction_id, kind="county", geoid="01001",
                 state_fips="01", name_raw="Autauga County", name_key="AUTAUGA",
                 vintage_start=2017, vintage_end=2021),
        ])
        conn.execute(insert(JurisdictionIdentifier), [
            dict(id=uuid4(), jurisdiction_id=state_jurisdiction_id,
                 reference_id=state_reference_id, scheme="FIPS_STATE", value="01"),
            dict(id=uuid4(), jurisdiction_id=county_jurisdiction_id,
                 reference_id=county_reference_id, scheme="FIPS_COUNTY", value="01001"),
        ])
        conn.execute(insert(JurisdictionRelationship), [
            dict(id=uuid4(), parent_id=uuid4() if wrong_parent else state_jurisdiction_id,
                 child_id=county_jurisdiction_id, reference_id=county_reference_id,
                 relationship="contains"),
        ])
    return release_id


def test_validation_reads_mapped_objects_not_uuid_scalars(reference_engine):
    release_id = insert_sample(reference_engine)
    report = validate_loaded_reference(reference_engine, release_id)
    assert report["state_count"] == 1
    assert report["county_count"] == 1
    assert report["identifier_count"] == 2
    assert report["hierarchy_count"] == 1
    # Only intentional fixture incompleteness, not incorrect references or hierarchy.
    assert report["errors"] == [
        {"code": "INCOMPLETE_STATES", "actual": 1, "expected": 51}
    ]


def test_validation_detects_incorrect_hierarchy(reference_engine):
    release_id = insert_sample(reference_engine, wrong_parent=True)
    report = validate_loaded_reference(reference_engine, release_id)
    assert {error["code"] for error in report["errors"]} == {
        "INCOMPLETE_STATES", "INVALID_HIERARCHY"
    }
