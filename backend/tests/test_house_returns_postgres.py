"""House ingestion, migration, publication and HTTP checks on isolated PostgreSQL schemas."""
from datetime import datetime, timezone
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

from app.main import app
from app.api.elections import get_read_session
from app.models.core import Candidacy, Contest, Person
from app.models.election import BallotLine, CanonicalMaterializationIssue, CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn
from app.models.house_returns import HouseReturnDetail, HouseDistrictReconciliation
from app.models.ingestion import ElectionResultObservation as Observation, SourceRelease
from app.services.canonical_results import MaterializationError, candidate_totals
from app.services.house_returns import publish, SCOPE
from ingestion.adapters.census_congressional_districts import Job as Census
from ingestion.adapters.medsl_house import Job
from ingestion.loader import register_run
from ingestion.source import AcquiredFile, SourceInfo, sha256_file
from test_data004_postgres import pg, migration
from test_house_returns import FIXTURE

pytestmark = pytest.mark.integration


@pytest.fixture
def house_engine(pg):
    with pg.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        for filename in ("authoritative_state_results.py", "reviewed_county_corrections.py", "house_return_evidence.py", "senate_return_evidence.py"):
            migration(filename).upgrade()
    return pg


def load_fixture(engine, *, version="15.0", transform=None, detail_failure=False):
    job = Job()
    frame = job.select(job.normalize(job.parse(FIXTURE)), {2024})
    if transform:
        frame = transform(frame)
    now, run = datetime.now(timezone.utc), uuid4()
    source = register_run(engine, run, job.key, job.source_url, now, {})
    asset = AcquiredFile(SourceInfo(job.key, job.DOI, version, 1, FIXTURE.name, "https://example.invalid/source",
                                   None, now, {}), FIXTURE, sha256_file(FIXTURE), now)
    if detail_failure:
        from ingestion.loader import load
        from ingestion.house_returns import records
        def fail(*args):
            raise RuntimeError("detail failure")
        return load(engine, source, run, asset, frame, {2024}, [], now, now, 0,
                    record_builder=records, detail_loader=fail)
    return job.load(engine, source, run, asset, frame, {2024}, [], now, now, 0, 15)


def load_census(engine):
    job = Census(2024)
    now, run = datetime.now(timezone.utc), uuid4()
    source = register_run(engine, run, job.key, job.source_url, now, {})
    asset = AcquiredFile(job.describe(), Path("fixture.zip"), "c"*64, now)
    frame = pl.DataFrame(dict(state_code=["NY", "FL", "DC", "ME"],
        geoid=["3601", "1220", "1198", "2302"], source_row_number=[2,3,4,5]))
    return job.load(engine, source, run, asset, frame, dict(records_in_file=4))


def materialize(engine, **kwargs):
    with Session(engine) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        return publish(session, **kwargs)


def test_load_publication_fusion_writeins_missing_and_http(house_engine):
    assert load_fixture(house_engine).inserted == 13
    assert load_fixture(house_engine).existing == 13
    first_ref = load_census(house_engine)
    assert first_ref["records_inserted"] == 4
    assert load_census(house_engine)["records_already_present"] == 4
    preview = materialize(house_engine)
    assert preview["accepted_rows"] == 8 and preview["excluded_rows"] == 5
    assert preview["canonical_votes"] == 340 and preview["reconciled_districts"] == 3
    assert preview["issue_counts"] == {"MISSING_VOTES":1, "NON_VOTE_CATEGORY":4}
    with Session(house_engine) as session:
        assert session.scalar(select(func.count()).select_from(CanonicalResultBatch)) == 0
    with pytest.raises(MaterializationError, match="allow-partial"):
        materialize(house_engine, dry_run=False)
    made = materialize(house_engine, dry_run=False, allow_partial=True)
    repeated = materialize(house_engine, dry_run=False, allow_partial=True)
    assert repeated["action"] == "UNCHANGED" and made["batch_id"] == repeated["batch_id"]
    with Session(house_engine) as session:
        assert session.scalar(select(func.count()).select_from(Person)) == 0
        assert session.scalar(select(func.count()).select_from(Contest)) == 4
        assert session.scalar(select(func.count()).select_from(HouseDistrictReconciliation)) == 4
        assert session.scalar(select(func.count()).select_from(CanonicalMaterializationIssue)) == 5
        alice = session.scalar(select(Candidacy).where(Candidacy.source_label == "ALICE"))
        assert len(list(session.scalars(select(BallotLine).where(BallotLine.candidacy_id == alice.id)))) == 2
        totals = candidate_totals(session, batch_id=UUID(made["batch_id"]), contest_id=alice.contest_id,
                                  reporting_level="congressional_district")
        assert sorted(t["votes"] for t in totals) == [3,80,100]
        placeholder = session.scalar(select(Observation).where(Observation.candidate_raw == "UNOPPOSED"))
        assert placeholder.candidate_votes is None and placeholder.raw_json["candidatevotes"] == "1"
        assert session.scalar(select(Candidacy).where(Candidacy.source_label == "UNOPPOSED"))
    def override():
        with Session(house_engine) as session, session.begin():
            yield session
    app.dependency_overrides[get_read_session] = override
    try:
        with TestClient(app) as client:
            data = client.get("/api/v1/results", params=dict(year=2024, office="U.S. House",
                reporting_level="congressional_district", state_code="NY")).json()
            assert data["total"] == 4 and sum(r["votes"] for r in data["items"]) == 185
            assert next(r for r in data["items"] if r["label"] == "ALICE")["votes"] == 100
            assert all(r["publication"]["status"] == "PARTIAL" for r in data["items"])
            assert len({r["geographic_reference_id"] for r in data["items"]}) == 1
            assert client.get("/api/v1/contests", params=dict(year=2024, office="U.S. House")).json()["total"] == 4
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("change,code", [
    (lambda f:pl.concat([f, f.head(1).with_columns(pl.lit(99, dtype=pl.UInt32).alias("source_row_number"))]), "DUPLICATE_LOGICAL_KEY"),
    (lambda f:f.with_columns(pl.when(pl.col("candidate") == "BOB").then(81).otherwise(pl.col("votes_int")).alias("votes_int")), "REPORTED_TOTAL_MISMATCH"),
    (lambda f:f.with_columns(pl.when(pl.col("candidate") == "ALICE").then(pl.lit("ABSENTEE")).otherwise(pl.col("mode_normalized")).alias("mode_normalized")), "UNSUPPORTED_VOTING_MODE"),
    (lambda f:f.with_columns(pl.lit("FALSE").alias("fusion_ticket_normalized")), "UNVERIFIED_FUSION"),
    (lambda f:f.with_columns(pl.when(pl.col("state_code") == "NY").then(pl.lit("99")).otherwise(pl.col("district_code")).alias("district_code")), "DISTRICT_NOT_IN_REFERENCE"),
])
def test_bad_unit_is_withheld_in_full(house_engine, change, code):
    load_fixture(house_engine, transform=change)
    load_census(house_engine)
    report = materialize(house_engine)
    assert code in report["issue_counts"]
    assert report["canonical_votes"] == 155


def test_new_release_history_reactivation_and_detail_rollback(house_engine):
    load_census(house_engine)
    load_fixture(house_engine)
    first = materialize(house_engine, dry_run=False, allow_partial=True)
    load_fixture(house_engine, version="16.0")
    second = materialize(house_engine, dry_run=False, allow_partial=True)
    assert first["batch_id"] != second["batch_id"]
    load_fixture(house_engine)
    assert materialize(house_engine, dry_run=False, allow_partial=True)["action"] == "REACTIVATED"
    with pytest.raises(RuntimeError, match="detail failure"):
        load_fixture(house_engine, version="17.0", detail_failure=True)
    with Session(house_engine) as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 26
        assert session.scalar(select(func.count()).select_from(HouseReturnDetail)) == 26
        assert session.scalar(select(SourceRelease).where(SourceRelease.version == "17.0")) is None
        assert session.get(CanonicalPublication, SCOPE).batch_id == UUID(first["batch_id"])


def test_migration_constraints_and_downgrade_preserve_prior_tables(house_engine):
    load_fixture(house_engine)
    with Session(house_engine) as session, session.begin():
        detail = session.scalar(select(HouseReturnDetail))
        with pytest.raises(IntegrityError), session.begin_nested():
            detail.district_code = "x"
            session.flush()
    with house_engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration("house_return_evidence.py").downgrade()
        assert conn.scalar(text("SELECT count(*) FROM election_result_observation")) == 13
        migration("house_return_evidence.py").upgrade()
        assert "house_return_detail" in inspect(conn).get_table_names()


def test_publication_rolls_back_atomically(house_engine):
    load_fixture(house_engine)
    load_census(house_engine)
    with pytest.raises(RuntimeError):
        with Session(house_engine) as session, session.begin():
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            publish(session, dry_run=False, allow_partial=True)
            raise RuntimeError("rollback")
    with Session(house_engine) as session:
        assert session.scalar(select(func.count()).select_from(CanonicalPublication)) == 0
        assert session.scalar(select(func.count()).select_from(CanonicalVoteReturn)) == 0
        assert session.scalar(select(func.count()).select_from(Candidacy)) == 0
