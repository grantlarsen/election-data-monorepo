"""Offline DDL contract test, plus an optional PostgreSQL upgrade/downgrade test."""
import importlib.util
import io
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

VERSIONS = Path(__file__).parents[1] / "migrations" / "versions"
HISTORY = (
    "2c9541d24f1e_initial_election_schema.py",
    "75c2f4a1d9be_ingestion.py",
    "c1f7a2b98d40_geographic_reference.py",
    "b3d62a17f8ac_geographic_remediation.py",
    "d002a150fd10_identity_foundation.py",
)


def migration(filename):
    spec = importlib.util.spec_from_file_location("migration_" + filename.split("_")[0], VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_identity_migration_is_additive_and_reversible():
    upgrade_sql = io.StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": upgrade_sql})
    with Operations.context(ctx):
        migration(HISTORY[-1]).upgrade()
    sql = upgrade_sql.getvalue().lower()
    for table in ("person_name", "organization", "external_identifier", "identity_assignment_event", "committee_relationship"):
        assert f"create table {table}" in sql
    assert "alter table person add column creation_key" in sql
    assert "drop table" not in sql
    assert "truncate" not in sql
    downgrade_sql = io.StringIO()
    ctx = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": downgrade_sql})
    with Operations.context(ctx):
        migration(HISTORY[-1]).downgrade()
    reverse = downgrade_sql.getvalue().lower()
    assert "drop table committee_relationship" in reverse
    assert "drop column creation_key" in reverse


@pytest.mark.integration
def test_real_migration_upgrade_and_downgrade_preserves_legacy_rows():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable TEST_DATABASE_URL ending _test")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("refusing to touch non-test database")
    schema = "identity_migrate_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            context = MigrationContext.configure(conn)
            with Operations.context(context):
                for filename in HISTORY[:-1]:
                    migration(filename).upgrade()
            # Persist a pre-migration person and party, to verify existing IDs/rows survive.
            person_id, party_id = uuid4(), uuid4()
            conn.execute(text("INSERT INTO person (id, full_name) VALUES (:id, :name)"),
                         {"id": person_id, "name": "Before Migration"})
            conn.execute(text("INSERT INTO political_party (id, name) VALUES (:id, :name)"),
                         {"id": party_id, "name": "Before Party"})
            # Existing MEDSL-style observations and geographic references must survive.
            source_id, release_id, observation_id, jurisdiction_id, reference_id = (uuid4() for _ in range(5))
            conn.execute(text("INSERT INTO data_source (id,name) VALUES (:id,'legacy_source')"), {"id": source_id})
            conn.execute(text("""INSERT INTO source_release
                (id,source_id,version,sha256,filename,file_id,download_url,raw_path,retrieved_at,metadata_json)
                VALUES (:rid,:sid,'legacy','a','raw.csv',1,'fixture','fixture',now(),CAST('{}' AS jsonb))"""),
                {"rid": release_id, "sid": source_id})
            conn.execute(text("""INSERT INTO election_result_observation
                (id,release_id,source_row_number,row_sha256,logical_key,year,state_code,state_fips,
                 candidate_raw,candidate_kind,raw_json,warnings_json)
                VALUES (:oid,:rid,2,'b','c',2024,'NY','36','SOURCE LABEL','candidate',
                        CAST('{}' AS jsonb),CAST('[]' AS jsonb))"""),
                {"oid": observation_id, "rid": release_id})
            conn.execute(text("INSERT INTO jurisdiction (id,name,level) VALUES (:id,'Albany','county')"),
                         {"id": jurisdiction_id})
            conn.execute(text("""INSERT INTO geographic_reference
                (id,release_id,jurisdiction_id,kind,geoid,state_fips,name_raw,name_key,vintage_start,vintage_end)
                VALUES (:gid,:rid,:jid,'county','36001','36','ALBANY','albany',2024,2024)"""),
                {"gid": reference_id, "rid": release_id, "jid": jurisdiction_id})
            with Operations.context(context):
                migration(HISTORY[-1]).upgrade()
            assert conn.scalar(text("SELECT count(*) FROM person WHERE id=:id"), {"id": person_id}) == 1
            assert conn.scalar(text("SELECT count(*) FROM political_party WHERE id=:id"), {"id": party_id}) == 1
            assert conn.scalar(text("SELECT count(*) FROM person_name")) == 0
            assert conn.scalar(text("SELECT count(*) FROM election_result_observation WHERE id=:id"),
                               {"id": observation_id}) == 1
            assert conn.scalar(text("SELECT count(*) FROM geographic_reference WHERE id=:id"),
                               {"id": reference_id}) == 1
            with Operations.context(context):
                migration(HISTORY[-1]).downgrade()
            assert conn.scalar(text("SELECT count(*) FROM person WHERE id=:id"), {"id": person_id}) == 1
            assert conn.scalar(text("SELECT count(*) FROM political_party WHERE id=:id"), {"id": party_id}) == 1
            assert conn.scalar(text("SELECT count(*) FROM election_result_observation WHERE id=:id"),
                               {"id": observation_id}) == 1
            assert conn.scalar(text("SELECT count(*) FROM geographic_reference WHERE id=:id"),
                               {"id": reference_id}) == 1
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
