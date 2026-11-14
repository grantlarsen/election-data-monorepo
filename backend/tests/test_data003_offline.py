"""Offline DATA-003 eligibility/migration contracts; no PostgreSQL required."""
import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from ingestion.canonical_medsl import eligibility, vote_kind

MIGRATION = Path(__file__).parents[1] / 'migrations' / 'versions' / 'd003f93a1700_election_canonical.py'


def test_medsl_conservative_vote_semantics():
    base = dict(candidate_kind='candidate', mode='TOTAL', votes=100,
                geo_status='RESOLVED', geo_level='county',
                duplicate_key=False, conflicting_scope=False)
    assert eligibility(**base) is None
    assert eligibility(**{**base, 'mode':'ABSENTEE'}) == 'UNSUPPORTED_VOTING_MODE'
    assert eligibility(**{**base, 'mode':None}) == 'UNSUPPORTED_VOTING_MODE'
    assert eligibility(**{**base, 'geo_status':'AMBIGUOUS'}) == 'GEOGRAPHY_NOT_RESOLVED'
    assert eligibility(**{**base, 'geo_level':'state'}) == 'UNSUPPORTED_REPORTING_LEVEL'
    assert eligibility(**{**base, 'votes':None}) == 'MISSING_VOTES'
    assert eligibility(**{**base, 'duplicate_key':True}) == 'DUPLICATE_LOGICAL_KEY'
    assert eligibility(**{**base, 'conflicting_scope':True}) == 'DUPLICATE_CANONICAL_SCOPE'
    assert eligibility(**{**base, 'conflicting_total':True}) == 'CONFLICTING_REPORTED_TOTAL'
    assert vote_kind('candidate') == 'candidate_total'
    assert vote_kind('aggregate') == 'aggregate'
    assert vote_kind('write_in') == 'write_in'


def test_offline_data003_migration_is_additive_and_named():
    spec = importlib.util.spec_from_file_location('data003_migration', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == 'd002a150fd10'
    stream = io.StringIO()
    ctx = MigrationContext.configure(dialect_name='postgresql', opts={'as_sql':True, 'output_buffer':stream})
    with Operations.context(ctx):
        module.upgrade()
    sql = stream.getvalue().lower()
    for table in ('office', 'office_term', 'ballot_line', 'canonical_result_batch',
                  'canonical_vote_return', 'canonical_materialization_issue', 'canonical_publication'):
        assert f'create table {table}' in sql
    assert 'alter table candidacy alter column person_id drop not null' in sql
    assert 'drop table' not in sql
    assert 'delete from' not in sql
    assert 'update election_result_observation' not in sql


def test_creation_key_stable_across_runs():
    from ingestion.canonical_medsl import scoped_key
    assert scoped_key('candidate', 'NY', 2008, 'A') == scoped_key('candidate', 'NY', 2008, 'A')
    assert scoped_key('candidate', 'NY', 2008, 'A') != scoped_key('candidate', 'NY', 2008, 'B')


def test_reporting_unit_reconciliation_fails_closed():
    from types import SimpleNamespace
    from ingestion.canonical_medsl import unit_reconciliation_issue
    a = SimpleNamespace(id=1,candidate_votes=80,total_votes=100)
    b = SimpleNamespace(id=2,candidate_votes=20,total_votes=100)
    assert unit_reconciliation_issue([a,b],set()) is None
    assert unit_reconciliation_issue([a,b],{1})=='REPORTING_UNIT_INCOMPLETE'
    b.total_votes=101
    assert unit_reconciliation_issue([a,b],set())=='MISSING_OR_CONFLICTING_TOTAL'
    b.total_votes=100
    b.candidate_votes=21
    assert unit_reconciliation_issue([a,b],set())=='REPORTED_TOTAL_MISMATCH'
    b.candidate_votes=20
    b.total_votes=None
    assert unit_reconciliation_issue([a,b],set())=='MISSING_OR_CONFLICTING_TOTAL'
    a.total_votes=None
    assert unit_reconciliation_issue([a,b],set())=='MISSING_OR_CONFLICTING_TOTAL'
