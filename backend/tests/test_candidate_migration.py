"""Additive migration SQL and real PostgreSQL upgrade/downgrade checks."""
import io

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import inspect, text

from app.models.candidate_identity import CandidateFinanceSummary, CandidateIdentityReview, FecCandidateRecord
from test_identity import identity_engine
from test_identity_migration import migration


def test_offline_candidate_migration():
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration("candidate_identity_review.py").upgrade()
    sql = output.getvalue().lower()
    for table in ("fec_candidate_record", "candidate_identity_review", "candidate_finance_summary"):
        assert f"create table {table}" in sql
    assert "where status = 'accepted'" in sql
    assert "drop table" not in sql and "alter table" not in sql


@pytest.mark.integration
def test_candidate_migration_roundtrip_preserves_existing_person(identity_engine):
    with identity_engine.begin() as connection:
        for model in (CandidateFinanceSummary, CandidateIdentityReview, FecCandidateRecord):
            model.__table__.drop(connection)
        connection.execute(text("INSERT INTO person (id,full_name) VALUES (gen_random_uuid(),'Existing person')"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration("candidate_identity_review.py").upgrade()
        assert "candidate_identity_review" in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT count(*) FROM person")) == 1
        with Operations.context(context):
            migration("candidate_identity_review.py").downgrade()
        assert "candidate_identity_review" not in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT count(*) FROM person")) == 1
