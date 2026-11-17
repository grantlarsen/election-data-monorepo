"""Senate migrations, publication replay, historical scope and public API checks."""
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
import polars as pl
import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.elections import get_read_session
from app.main import app
from app.models.core import Candidacy, Contest, Election, Person
from app.models.election import CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn
from app.models.geography import GeographicReference, GeographicResolution
from app.models.ingestion import ElectionResultObservation as Observation, SourceRelease
from app.models.senate_returns import SenateSeat, SenateReturnDetail
from app.services.canonical_results import MaterializationError
from app.services.senate_returns import publish, scope
from ingestion.adapters.medsl_senate import Job
from ingestion.geography.load import load_reference
from ingestion.loader import register_run
from ingestion.medsl import STATE_FIPS
from ingestion.senate_returns import YEARS
from ingestion.source import AcquiredFile, SourceInfo, sha256_file
from test_data004_postgres import pg, migration
from test_presidential_coverage import presidential_engine
from test_senate_returns import FIXTURE

pytestmark = pytest.mark.integration


def load_fixture(engine, *, path=FIXTURE, version="8.0", years=None, transform=None, fail_details=False):
    job = Job()
    years = years or {2008,2021}
    frame = job.select(job.normalize(job.parse(path)), years)
    if transform:
        frame = transform(frame)
    assert job.validate(frame, years, None).ok
    now, run = datetime.now(timezone.utc), uuid4()
    source = register_run(engine, run, job.key, job.source_url, now, {})
    asset = AcquiredFile(SourceInfo(job.key, job.DOI, version, 1, path.name,
        "https://example.invalid/synthetic-source", None, now, {}), path, sha256_file(path), now)
    if fail_details:
        from ingestion.loader import load
        from ingestion.senate_returns import records
        def fail(*args):
            raise RuntimeError("detail failure")
        return load(engine, source, run, asset, frame, years, [], now, now, 0,
                    record_builder=records, detail_loader=fail)
    return job.load(engine, source, run, asset, frame, years, [], now, now, 0, job.parse(path).height)


def load_states(engine):
    """Synthetic Census state reference for isolated tests; no network or live DB."""
    now, run = datetime.now(timezone.utc), uuid4()
    source = register_run(engine, run, "census_state_county_georef", "https://example.invalid/census", now, {})
    frame = pl.DataFrame([dict(state_fips=fips, county_code="000", geoid=fips+"000",
        county_name_raw="STATE", name_key="STATE", source_row_number=n) for n,fips in enumerate(STATE_FIPS.values(),2)])
    info = SourceInfo("census_state_county_georef", "synthetic", "fixture", 1, "fixture.txt",
                     "https://example.invalid/census", None, now, dict(vintage_start=2000,vintage_end=2024))
    return load_reference(engine, source, run, AcquiredFile(info, Path("fixture.txt"), "c"*64, now), frame, {})


def materialize(engine, *, year=2008, **kwargs):
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        return publish(session, year=year, **kwargs)


@pytest.fixture
def senate_engine(presidential_engine):
    load_states(presidential_engine)
    return presidential_engine


def test_publication_fusion_seat_history_special_runoff_and_profiles(senate_engine):
    assert load_fixture(senate_engine).inserted == 13
    assert load_fixture(senate_engine).existing == 13
    preview = materialize(senate_engine)
    assert preview["accepted_rows"] == 10 and preview["excluded_rows"] == 1
    assert preview["canonical_votes"] == 583
    with pytest.raises(MaterializationError, match="allow-partial"):
        materialize(senate_engine, dry_run=False)
    first = materialize(senate_engine, dry_run=False, allow_partial=True)
    assert materialize(senate_engine, dry_run=False, allow_partial=True)["action"] == "UNCHANGED"
    made2021 = materialize(senate_engine, year=2021, dry_run=False)
    assert made2021["canonical_votes"] == 110
    with Session(senate_engine) as session:
        assert session.scalar(select(func.count()).select_from(Person)) == 0
        assert session.scalar(select(func.count()).select_from(Contest)) == 7
        assert session.scalar(select(func.count()).select_from(SenateSeat)) == 5
        ga_events = session.scalars(select(Election).where(Election.election_cycle == 2020)).all()
        assert {str(e.election_date) for e in ga_events} == {"2021-01-05"}
        assert {e.election_type for e in ga_events} == {"runoff", "special_runoff"}
        alice = session.scalar(select(Candidacy).where(Candidacy.source_label == "ALICE"))
        candidate_id = alice.id
    def override():
        with Session(senate_engine) as session, session.begin():
            yield session
    app.dependency_overrides[get_read_session] = override
    try:
        with TestClient(app) as client:
            data = client.get("/api/v1/results", params=dict(year=2008, office="U.S. Senate",
                reporting_level="state", state_code="NJ")).json()
            assert data["total"] == 3 and sum(r["votes"] for r in data["items"]) == 183
            assert next(r for r in data["items"] if r["label"] == "ALICE")["votes"] == 100
            assert all(r["seat_class"] == 2 for r in data["items"])
            contests = client.get("/api/v1/contests?year=2008&state_code=MS&seat_class=1").json()
            assert contests["total"] == 1 and contests["items"][0]["stage"] == "special"
            assert client.get("/api/v1/elections?year=2008&seat_class=1").json()["total"] == 1
            assert client.get("/api/v1/results?office=U.S.+Senate&reporting_level=county").json()["total"] == 0
            assert client.get("/api/v1/results?office=U.S.+Senate&seat_class=3&reporting_level=state").json()["total"] == 1
            assert client.get("/api/v1/state-results?office=U.S.+Senate").json()["total"] == 0
            response = client.get(f"/api/v1/candidates/{candidate_id}")
            assert response.status_code == 200, response.text
            profile = response.json()
            assert profile["results"]["reporting_level"] == "state" and profile["results"]["items"][0]["votes"] == 100
            assert profile["identity_status"] == "unresolved"
            assert client.get("/api/v1/contests?seat_class=4").status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("transform,code", [
    (lambda f:f.with_columns(pl.when(pl.col("candidate") == "BOB").then(81).otherwise(pl.col("votes_int")).alias("votes_int")), "REPORTED_TOTAL_MISMATCH"),
    (lambda f:f.with_columns(pl.when(pl.col("candidate") == "BOB").then(pl.lit("ABSENTEE")).otherwise(pl.col("mode_normalized")).alias("mode_normalized")), "UNSUPPORTED_VOTING_MODE"),
    (lambda f:f.with_columns(pl.when(pl.col("candidate") == "BOB").then(pl.lit("TRUE")).otherwise(pl.col("unofficial_normalized")).alias("unofficial_normalized")), "UNOFFICIAL_RESULT"),
    (lambda f:pl.concat([f, f.head(1).with_columns(pl.lit(99, dtype=pl.UInt32).alias("source_row_number"))]), "DUPLICATE_LOGICAL_KEY"),
])
def test_entire_contest_withheld_when_one_row_fails(senate_engine, transform, code):
    load_fixture(senate_engine, transform=transform)
    report = materialize(senate_engine)
    assert code in report["issue_counts"].keys() or any(code in r["checks_json"]["issues"] for r in report["reconciliations"])
    assert report["canonical_votes"] == 400


def test_version_history_reactivation_rollback_and_geography_conflict(senate_engine):
    load_fixture(senate_engine)
    first = materialize(senate_engine, dry_run=False, allow_partial=True)
    load_fixture(senate_engine, version="9.0")
    second = materialize(senate_engine, dry_run=False, allow_partial=True)
    assert first["batch_id"] != second["batch_id"]
    load_fixture(senate_engine)
    assert materialize(senate_engine, dry_run=False, allow_partial=True)["action"] == "REACTIVATED"
    with pytest.raises(RuntimeError, match="detail failure"):
        load_fixture(senate_engine, version="10.0", fail_details=True)
    with Session(senate_engine) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(Observation)) == 26
        assert session.scalar(select(func.count()).select_from(SenateReturnDetail)) == 26
        assert session.scalar(select(SourceRelease).where(SourceRelease.version == "10.0")) is None
        geo = session.scalar(select(GeographicResolution))
        session.add(GeographicResolution(observation_id=geo.observation_id,
            reference_release_id=geo.reference_release_id, supersedes_id=geo.id,
            status="UNRESOLVED", method="TEST_REVIEW", reason="Synthetic superseding geography review",
            evidence_json={}, ruleset_version="test-review"))
    with pytest.raises(MaterializationError, match="geography conflicts"):
        materialize(senate_engine, dry_run=False, allow_partial=True)


def test_atomic_publication_and_migration_roundtrip(senate_engine):
    load_fixture(senate_engine)
    with pytest.raises(RuntimeError):
        with Session(senate_engine) as session, session.begin():
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            publish(session, year=2008, dry_run=False, allow_partial=True)
            raise RuntimeError("rollback")
    with Session(senate_engine) as session:
        assert session.scalar(select(func.count()).select_from(CanonicalPublication)) == 0
        assert session.scalar(select(func.count()).select_from(Contest)) == 0
    with senate_engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration("senate_return_evidence.py").downgrade()
        assert conn.scalar(text("SELECT count(*) FROM election_result_observation")) == 13
        migration("senate_return_evidence.py").upgrade()
        assert "senate_seat" in inspect(conn).get_table_names()


def test_seat_class_constraint_and_unofficial_metadata_only_publication(senate_engine):
    load_fixture(senate_engine, transform=lambda f:f.with_columns(pl.lit("TRUE").alias("unofficial_normalized")))
    report = materialize(senate_engine, year=2021, dry_run=False, allow_partial=True)
    assert report["accepted_rows"] == 0 and report["excluded_rows"] == 2
    with Session(senate_engine) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(Contest)) == 2
        seat = session.scalar(select(SenateSeat))
        with pytest.raises(IntegrityError), session.begin_nested():
            seat.seat_class = 4
            session.flush()


def test_canonical_categories_ignore_older_ingestion_hints(senate_engine):
    load_fixture(senate_engine, transform=lambda f:f.with_columns(pl.lit("candidate").alias("candidate_kind")))
    report = materialize(senate_engine, dry_run=False, allow_partial=True)
    assert report["canonical_votes"] == 583 and report["accepted_rows"] == 10
    with Session(senate_engine) as session:
        labels = set(session.scalars(select(Candidacy.source_label)))
        assert "BLANK" not in labels and "" not in labels
        assert session.scalar(select(func.count()).select_from(CanonicalVoteReturn).where(
            CanonicalVoteReturn.vote_kind == "write_in")) == 1


def test_pinned_official_source_all_years_replay(senate_engine):
    filename = os.getenv("MEDSL_SENATE_FILE")
    if not filename:
        pytest.skip("Set MEDSL_SENATE_FILE to the pinned official original; never downloads")
    path = Path(filename)
    assert sha256_file(path) == "6f745db1b4a0026ad837e74428f9ed6f3f77fa51eb6f858b58ebdbc186fdb3bd"
    assert load_fixture(senate_engine, path=path, years=YEARS).inserted == 2314
    assert load_fixture(senate_engine, path=path, years=YEARS).existing == 2314
    reports = []
    for year in sorted(YEARS):
        first = materialize(senate_engine, year=year, dry_run=False, allow_partial=True)
        second = materialize(senate_engine, year=year, dry_run=False, allow_partial=True)
        assert second["action"] == "UNCHANGED" and second["batch_id"] == first["batch_id"]
        assert first["input_rows"] == first["accepted_rows"] + first["excluded_rows"]
        reports.append(first)
    illinois = next(r for r in reports if r["year"] == 2010)
    assert illinois["issue_counts"]["CONFLICTING_ELECTION_TYPE"] == 13
    with Session(senate_engine) as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 2314
        assert session.scalar(select(func.count()).select_from(SenateReturnDetail)) == 2314
        assert session.scalar(select(func.count()).select_from(CanonicalResultBatch)) == 14
        assert session.scalar(select(func.count()).select_from(Person)) == 0
        assert session.scalar(select(func.count()).select_from(SenateSeat)) == 100
        # Independently sourced 2008 Georgia general/runoff totals from the Clerk.
        for stage, expected in (("general",3752485),("runoff",2137956)):
            total = session.scalar(select(func.sum(CanonicalVoteReturn.votes)).join(Contest,
                Contest.id == CanonicalVoteReturn.contest_id).join(Election, Contest.election_id == Election.id)
                .join(SenateSeat, SenateSeat.office_id == Contest.office_id).where(
                    SenateSeat.state_code == "GA", Election.election_cycle == 2008, Election.election_type == stage))
            assert total == expected
