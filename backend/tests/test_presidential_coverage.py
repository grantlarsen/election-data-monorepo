"""Seven-election source validation, migration, publication, replay and HTTP scope."""
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import Base
from app.main import app
from app.api.elections import get_read_session
from app.models.core import Contest, Election, Jurisdiction
from app.models.ingestion import SourceRelease
from app.models.election import CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn
from app.models.state_results import StateResultBatch, StateResultPublication, StateVoteReturn
from app.services.canonical_results import materialize_medsl_year, state_totals
from app.services.presidential_coverage import inventory
from app.services.presidential_state_returns import projection, publish
from ingestion.presidential_state_returns import BUCKETS, RULESET, digest, extract_summary, integer, verify_package
from ingestion.medsl import STATE_NAMES
from test_data003_postgres import _seed, _observe
from test_data004_postgres import pg, migration
from test_fec_state_authority import official_fixture, seed_comparison


def package_fixture(tmp_path, year):
    body = b'original workbook fixture'
    raw = tmp_path/'official.xlsx'
    raw.write_bytes(body)
    spec = dict(year=year, filename=raw.name, url='https://www.fec.gov/official.xlsx',
                sha256=sha256(body).hexdigest(), retrieved_at=datetime.now(timezone.utc).isoformat(),
                national_buckets=[5100,4080,255], national_votes=9435)
    states = [dict(state_code=st, votes=dict(zip(BUCKETS[year], (100,80,5))),
                   total_votes=185, source_locator=f'worksheet summary; row {n}')
              for n,st in enumerate(sorted(STATE_NAMES),2)]
    return dict(format=RULESET, year=year, source=spec, states=states)


@pytest.fixture
def presidential_engine(pg):
    config = Config(str(Path(__file__).parents[1]/'alembic.ini'))
    script = ScriptDirectory.from_config(config)
    revisions = list(reversed(list(script.walk_revisions())))
    with pg.begin() as c, Operations.context(MigrationContext.configure(c)):
        after_geography = False
        for revision in revisions:
            if after_geography:
                revision.module.upgrade()
            if revision.revision == 'd004a9c21e70':
                after_geography = True
        assert compare_metadata(MigrationContext.configure(c), Base.metadata) == []
    return pg


@pytest.mark.parametrize('value', ['', 'NA', -1, '2.5', 'NaN', 'Infinity'])
def test_invalid_votes_never_become_zero(value):
    with pytest.raises(ValueError):
        integer(value)


@pytest.mark.parametrize('problem', ['duplicate_state','missing_state','bad_sum','wrong_year','negative','bad_bucket'])
def test_invalid_packages_rejected(tmp_path,problem):
    package=package_fixture(tmp_path,2024)
    if problem=='duplicate_state': package['states'][-1]=deepcopy(package['states'][0])
    if problem=='missing_state': package['states'].pop()
    if problem=='bad_sum': package['states'][0]['total_votes']+=1
    if problem=='wrong_year': package['source']['year']=2020
    if problem=='negative': package['states'][0]['votes']['OTHER']=-1
    if problem=='bad_bucket': package['states'][0]['votes']['MADE UP']=package['states'][0]['votes'].pop('OTHER')
    with pytest.raises(ValueError): verify_package(package)


def test_xlsx_relationships_inline_strings_cached_formulas_and_header_checks(tmp_path):
    path=tmp_path/'source.xlsx'
    rows=['<row r="1"><c r="A1" t="inlineStr"><is><t>STATE</t></is></c></row>']
    for n,st in enumerate(STATE_NAMES,2):
        rows.append(f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>{st}</t></is></c>'
            f'<c r="D{n}"><v>100</v></c><c r="E{n}"><v>80</v></c><c r="F{n}"><v>5</v></c>'
            f'<c r="G{n}"><f>SUM(D{n}:F{n})</f><v>185</v></c></row>')
    with ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="summary" r:id="rId42"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId42" Target="worksheets/custom.xml"/></Relationships>')
        z.writestr('xl/worksheets/custom.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(rows)+'</sheetData></worksheet>')
    spec=dict(year=2000,sheet='summary',headers={'A1':'STATE'},columns=['D','E','F','G'],
              national_buckets=[5100,4080,255],national_votes=9435)
    assert len(extract_summary(path,spec)['states'])==51
    spec['headers']['A1']='WRONG'
    with pytest.raises(ValueError,match='header'): extract_summary(path,spec)


@pytest.mark.integration
@pytest.mark.parametrize('year',[2000,2004,2012,2016,2020,2024])
def test_each_year_publish_replay_api_and_scope(presidential_engine,tmp_path,year):
    engine=presidential_engine
    package=package_fixture(tmp_path,year)
    with Session(engine) as s,s.begin():
        s.add_all([Jurisdiction(name=name,level='state',state_code=st) for st,name in STATE_NAMES.items()])
    def transaction():
        s=Session(engine)
        s.begin()
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        return s
    with transaction() as s:
        plan=projection(s,package,tmp_path)
        with pytest.raises(ValueError,match='Stale'):
            publish(s,package,tmp_path,expected_fingerprint='0'*64,actor='test',authorization_note='test scope')
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==0
        made=publish(s,package,tmp_path,expected_fingerprint=plan['fingerprint'],actor='test',authorization_note='test scope')
        assert made['votes']==9435
        s.commit()
    with transaction() as s:
        replay=publish(s,package,tmp_path,expected_fingerprint=plan['fingerprint'],actor='test',authorization_note='test scope')
        assert replay['action']=='UNCHANGED' and replay['batch_id']==made['batch_id']
        assert s.scalar(select(func.count()).select_from(SourceRelease))==1
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==1
        assert len(state_totals(s,year=year)['results'])==153
        assert not state_totals(s,year=year)['additive_with_county_returns']
        assert len(inventory(s)['elections'])==7
        s.commit()
    def override():
        with Session(engine) as s,s.begin():
            yield s
    app.dependency_overrides[get_read_session]=override
    try:
        with TestClient(app) as client:
            result=client.get('/api/v1/state-results',params={'year':year,'state_code':'NY'})
            assert result.status_code==200,result.text
            assert result.json()['total']==3
            assert sum(r['votes'] for r in result.json()['items'])==185
            assert all(r['election_date'].startswith(str(year)) and r['source_adjustment'] is None for r in result.json()['items'])
            assert client.get('/api/v1/state-results',params={'year':year-4}).json()['total']==0
            assert client.get('/api/v1/state-results',params={'year':year,'offset':999}).json()['items']==[]
            assert client.get('/api/v1/elections',params={'year':year,'office':'U.S. President'}).json()['total']==51
            assert client.get('/api/v1/presidential-coverage').status_code==200
    finally:
        app.dependency_overrides.clear()
    with engine.begin() as c:
        with pytest.raises(DBAPIError),c.begin_nested():
            c.execute(text('UPDATE state_vote_return SET votes=votes+1'))
        with pytest.raises(DBAPIError),c.begin_nested(),Operations.context(MigrationContext.configure(c)):
            migration('presidential_state_coverage.py').downgrade()


@pytest.mark.integration
def test_county_publication_uses_same_event_and_excludes_overlapping_modes(presidential_engine,tmp_path):
    engine=presidential_engine
    package=package_fixture(tmp_path,2020)
    with Session(engine) as s,s.begin():
        seed=_seed(s,year=2020)
        s.add_all([Jurisdiction(name=name,level='state',state_code=st) for st,name in STATE_NAMES.items() if st!='NY'])
        for n,(label,votes,kind) in enumerate([('JOE BIDEN',100,'candidate'),('DONALD TRUMP',80,'candidate'),('OTHER',5,'aggregate')],2):
            o=_observe(s,seed,n,name=label,votes=votes,total=185,kind=kind)
            o.year=2020
        o=_observe(s,seed,5,name='JOE BIDEN',votes=70,total=185,mode='ELECTION DAY')
        o.year=2020
    with Session(engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        plan=projection(s,package,tmp_path)
        publish(s,package,tmp_path,expected_fingerprint=plan['fingerprint'],actor='test',authorization_note='test')
        report=materialize_medsl_year(s,year=2020,dry_run=False,allow_partial=True)
        assert report['eligible_canonical_votes']==185
        assert report['issue_counts']=={'UNSUPPORTED_VOTING_MODE':1}
        assert s.scalar(select(func.count()).select_from(Election))==51
        assert s.scalar(select(func.count()).select_from(Contest))==51
        assert s.scalar(select(func.sum(CanonicalVoteReturn.votes)))==185
        again=materialize_medsl_year(s,year=2020,dry_run=False,allow_partial=True)
        assert again['action']=='UNCHANGED'
        coverage=next(r for r in inventory(s)['elections'] if r['year']==2020)
        ny=next(r for r in coverage['states'] if r['state_code']=='NY')
        assert ny['state_minus_published_county_votes']==0
        assert coverage['county']['excluded_rows']==1


@pytest.mark.integration
def test_multiple_years_have_stable_pages_and_distinct_elections(presidential_engine,tmp_path):
    engine=presidential_engine
    with Session(engine) as s,s.begin():
        s.add_all([Jurisdiction(name=name,level='state',state_code=st) for st,name in STATE_NAMES.items()])
    with Session(engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        for year in (2000,2004,2012,2016,2020,2024):
            package=package_fixture(tmp_path,year)
            publish(s,package,tmp_path,expected_fingerprint=projection(s,package,tmp_path)['fingerprint'],
                    actor='test',authorization_note='test')
        from app.api.election_schemas import ElectionFilters
        from app.services.election_queries import list_state_results
        first=list_state_results(s,ElectionFilters(limit=200))
        second=list_state_results(s,ElectionFilters(limit=200,offset=200))
        assert first['total']==918
        assert all(r['election_date'].year==2024 for r in first['items'][:153])
        keys=lambda page:{(r['contest_id'],r['candidate_bucket']) for r in page['items']}
        assert not keys(first)&keys(second)


@pytest.mark.integration
def test_migration_preserves_original_2008_rows_and_rejects_invalid_buckets(presidential_engine,tmp_path):
    engine=presidential_engine
    seed_comparison(engine,tmp_path)
    evidence=official_fixture(tmp_path/'old-official')
    from app.services import fec_state_results
    with Session(engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        old_plan=fec_state_results.plan(s,evidence)
        fec_state_results.publish(s,evidence,expected_fingerprint=old_plan['fingerprint'],actor='original',archive_dir=tmp_path/'old-archive')
    with engine.begin() as c:
        tables=('state_result_batch','state_vote_return','state_result_publication','canonical_result_batch','canonical_vote_return','canonical_publication')
        def hashes():
            return {t:list(c.execute(text(f'SELECT md5(row_to_json(r)::text) FROM {t} r ORDER BY 1')).scalars()) for t in tables}
        before=hashes()
        with Operations.context(MigrationContext.configure(c)):
            migration('presidential_state_coverage.py').downgrade()
            migration('presidential_state_coverage.py').upgrade()
        assert hashes()==before
        row=dict(c.execute(text('SELECT * FROM state_vote_return LIMIT 1')).mappings().one())
        row['candidate_bucket']='UNREVIEWED'
        with pytest.raises(DBAPIError),c.begin_nested():
            c.execute(StateVoteReturn.__table__.insert().values(**row))
        assert compare_metadata(MigrationContext.configure(c),Base.metadata)==[]


@pytest.mark.integration
def test_corrupt_archive_and_late_failure_leave_no_publication(presidential_engine,tmp_path,monkeypatch):
    engine=presidential_engine
    package=package_fixture(tmp_path,2024)
    with Session(engine) as s,s.begin():
        s.add_all([Jurisdiction(name=name,level='state',state_code=st) for st,name in STATE_NAMES.items()])
    with Session(engine) as s:
        plan=projection(s,package,tmp_path)
        (tmp_path/'official.xlsx').write_bytes(b'changed')
        with pytest.raises(ValueError,match='checksum'): projection(s,package,tmp_path)
        (tmp_path/'official.xlsx').write_bytes(b'original workbook fixture')
    from app.services import presidential_state_returns as service
    def fail(*args,**kwargs):
        raise ValueError('late validation failure')
    monkeypatch.setattr(service,'read_totals',fail)
    with pytest.raises(ValueError,match='late'),Session(engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        publish(s,package,tmp_path,expected_fingerprint=plan['fingerprint'],actor='test',authorization_note='test')
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==0
        assert s.scalar(select(func.count()).select_from(StateResultPublication))==0
        assert s.scalar(select(func.count()).select_from(SourceRelease))==0
