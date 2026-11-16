"""FEC precedence replaces state totals without inventing county corrections."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models.core import DataSource, Jurisdiction
from app.models.election import CanonicalResultBatch, CanonicalPublication, CanonicalVoteReturn
from app.models.ingestion import ElectionResultObservation
from app.models.state_results import StateResultBatch, StateVoteReturn, StateResultPublication
from app.services.canonical_results import materialize_medsl_year, state_totals
from app.services.fec_state_results import plan, publish, read_state_totals
from ingestion.data005 import BUCKETS
from ingestion.fec_authority import AUTHORIZATION, SCOPE, authority_rows, load_authority
from ingestion.medsl import STATE_NAMES
from test_data003_postgres import pg_engine, _seed, _observe
from test_data004_postgres import pg, migration


MIGRATION='d005fec2008a_authoritative_state_results.py'


def official_fixture(path):
    path.mkdir()
    body=b'%PDF synthetic source for parser/publication tests'
    (path/'fec.pdf').write_bytes(body)
    pages=[dict(page=i,text=(f'{name}\nObama, Barack D 101 55.19%\n'
        'McCain, John R 82 44.81%\nTotal State Votes: 183'))
        for i,(st,name) in enumerate(STATE_NAMES.items(),1)]
    encoded=json.dumps(pages).encode()
    (path/'pages.json').write_bytes(encoded)
    (path/'retrievals.json').write_text(json.dumps([dict(id='fec-2008-president',
        url='https://www.fec.gov/documents/1660/2008pres.pdf',success=True,
        file='fec.pdf',sha256=sha256(body).hexdigest(),text_file='pages.json',
        text_sha256=sha256(encoded).hexdigest(),retrieved_at=datetime.now(timezone.utc).isoformat(),
        extraction='explicit synthetic fixture')]))
    return path


def seed_comparison(engine,tmp_path):
    source=tmp_path/'medsl.csv';source.write_bytes(b'synthetic MEDSL comparison archive')
    with Session(engine) as s,s.begin():
        seed=_seed(s)
        seed['release'].raw_path=str(source)
        seed['release'].sha256=sha256(source.read_bytes()).hexdigest()
        for st,name in STATE_NAMES.items():
            if st!='NY':
                s.add(Jurisdiction(name=name,level='state',state_code=st))
        n=2
        for st in STATE_NAMES:
            for label,votes,kind in [('BARACK OBAMA',100,'candidate'),('JOHN MCCAIN',80,'candidate'),('OTHER',5,'aggregate')]:
                o=_observe(s,seed,n,name=label,votes=votes,total=185,kind=kind,
                    status='RESOLVED' if st=='NY' else 'UNRESOLVED')
                o.state_code=st
                n+=1
    with Session(engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        prior=materialize_medsl_year(s,year=2008,dry_run=False,allow_partial=True)
    return prior


def exercise_publish(s,evidence,tmp_path,projection):
    return publish(s,evidence,expected_fingerprint=projection['fingerprint'],
                   actor='test-agent',archive_dir=tmp_path/'authority-raw')


def test_signed_adjustments_missing_evidence_and_county_allocation(tmp_path):
    directory=official_fixture(tmp_path/'official')
    _,states=load_authority(directory)
    rows=[dict(observation_id=f'{st}-{b}',state=st,candidate=b,votes=v,mode='TOTAL')
          for st in STATE_NAMES for b,v in zip(BUCKETS,(100,80,5))]
    result=authority_rows(rows,{r['observation_id']:r['votes'] for r in rows},states)
    ny={r['candidate_bucket']:r for r in result if r['state_code']=='NY'}
    assert ny['BARACK OBAMA']['source_adjustment']==1
    assert ny['OTHER']['votes']==0 and ny['OTHER']['source_adjustment']==-5
    assert all('county_id' not in r for r in result)
    with pytest.raises(ValueError,match='51 states'):
        authority_rows(rows[:-3],{},states)
    with pytest.raises(ValueError,match='outside the active source'):
        authority_rows(rows,{'unknown':1},states)
    (directory/'fec.pdf').write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='checksum'):
        load_authority(directory)


def test_real_postgres_publication_replay_preserves_counties(pg_engine,tmp_path):
    prior=seed_comparison(pg_engine,tmp_path)
    directory=official_fixture(tmp_path/'official')
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        projection=plan(s,directory)
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==0
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        made=exercise_publish(s,directory,tmp_path,projection)
        assert made['action']=='CREATED' and made['authoritative_votes']==51*183
        assert made['resolved_source_discrepancies']==153
        official=state_totals(s,year=2008,state_code='NY')
        assert official['source']=='FEC' and not official['additive_with_county_returns']
        assert {r['candidate_bucket']:r['votes'] for r in official['results']}==dict(zip(BUCKETS,(101,82,0)))
        assert s.scalar(select(CanonicalPublication.batch_id))==__import__('uuid').UUID(prior['batch_id'])
        assert s.scalar(select(func.sum(CanonicalVoteReturn.votes)))==185
        assert s.scalar(select(func.count()).select_from(ElectionResultObservation))==153
        assert s.scalar(select(StateResultBatch.authorization_note))==AUTHORIZATION
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        again=exercise_publish(s,directory,tmp_path,projection)
        assert again['action']=='UNCHANGED' and again['batch_id']==made['batch_id']
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==1
        assert s.scalar(select(func.count()).select_from(StateVoteReturn))==153
        assert s.scalar(select(func.count()).select_from(DataSource).where(DataSource.name=='fec_presidential_official'))==1


def test_stale_approval_is_rejected_before_writes(pg_engine,tmp_path):
    seed_comparison(pg_engine,tmp_path)
    directory=official_fixture(tmp_path/'official')
    with pytest.raises(ValueError,match='Stale or changed'),Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        publish(s,directory,expected_fingerprint='0'*64,actor='test',archive_dir=tmp_path/'raw')
    with Session(pg_engine) as s:
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==0
        assert s.scalar(select(func.count()).select_from(DataSource).where(DataSource.name=='fec_presidential_official'))==0


def test_new_authority_release_supersedes_cached_pointer_without_rewriting_history(pg_engine,tmp_path):
    seed_comparison(pg_engine,tmp_path)
    directory=official_fixture(tmp_path/'official')
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        first=exercise_publish(s,directory,tmp_path,plan(s,directory))
    pages=json.loads((directory/'pages.json').read_text())
    pages[0]['text']=pages[0]['text'].replace('D 101','D 102').replace('Votes: 183','Votes: 184')
    encoded=json.dumps(pages).encode()
    (directory/'pages.json').write_bytes(encoded)
    body=b'%PDF synthetic revised FEC fixture'
    (directory/'fec.pdf').write_bytes(body)
    records=json.loads((directory/'retrievals.json').read_text())
    records[0].update(sha256=sha256(body).hexdigest(),text_sha256=sha256(encoded).hexdigest())
    (directory/'retrievals.json').write_text(json.dumps(records))
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        cached=s.get(StateResultPublication,SCOPE)
        assert str(cached.batch_id)==first['batch_id']
        second=exercise_publish(s,directory,tmp_path,plan(s,directory))
        assert second['action']=='CREATED' and second['batch_id']!=first['batch_id']
        assert sum(r['votes'] for r in state_totals(s,year=2008)['results'])==51*183+1
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==2
        assert s.scalar(select(func.count()).select_from(StateVoteReturn))==306
        old=s.get(StateResultBatch,__import__('uuid').UUID(first['batch_id']))
        new=s.get(StateResultBatch,__import__('uuid').UUID(second['batch_id']))
        assert str(new.supersedes_id)==first['batch_id']
        assert old.manifest_json['fec_source']['sha256']!=new.manifest_json['fec_source']['sha256']


def test_late_failure_rolls_back_authority_source_and_pointer(pg_engine,tmp_path):
    seed_comparison(pg_engine,tmp_path)
    directory=official_fixture(tmp_path/'official')
    with Session(pg_engine) as s:
        projection=plan(s,directory)
    def fail(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO state_result_publication'):
            raise RuntimeError('injected late publication failure')
    event.listen(pg_engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='injected'),Session(pg_engine) as s,s.begin():
            s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
            exercise_publish(s,directory,tmp_path,projection)
    finally:
        event.remove(pg_engine,'before_cursor_execute',fail)
    with Session(pg_engine) as s:
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==0
        assert s.scalar(select(func.count()).select_from(StateVoteReturn))==0
        assert s.scalar(select(func.count()).select_from(StateResultPublication))==0
        assert s.scalar(select(func.count()).select_from(DataSource).where(DataSource.name=='fec_presidential_official'))==0


def test_migration_roundtrip_append_only_targets_and_publication_completeness(pg,tmp_path):
    with pg.begin() as c,Operations.context(MigrationContext.configure(c)):
        migration(MIGRATION).upgrade()
        migration(MIGRATION).downgrade()
        migration(MIGRATION).upgrade()
    before=set(inspect(pg).get_table_names())
    assert {'state_result_batch','state_vote_return','state_result_publication'}<=before
    with pg.begin() as c,Operations.context(MigrationContext.configure(c)):
        migration('d005county01_reviewed_county_corrections.py').upgrade()
    seed_comparison(pg,tmp_path)
    directory=official_fixture(tmp_path/'official')
    with Session(pg) as s:
        projection=plan(s,directory)
    with Session(pg) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        made=exercise_publish(s,directory,tmp_path,projection)
    for statement in ["UPDATE state_vote_return SET votes=votes+1",
                      'DELETE FROM state_vote_return','UPDATE state_result_batch SET authorization_note=authorization_note']:
        with pytest.raises(DBAPIError,match='append-only'),pg.begin() as c:
            c.execute(text(statement))
    with pg.connect() as c:
        original=dict(c.execute(select(StateResultBatch.__table__)).mappings().one())
        row=dict(c.execute(select(StateVoteReturn.__table__)).mappings().first())
    from uuid import uuid4
    batch_id=uuid4()
    with pg.begin() as c:
        c.execute(StateResultBatch.__table__.insert().values({**original,'id':batch_id,'fingerprint':'f'*64}))
    with pytest.raises(DBAPIError,match='51 states'),pg.begin() as c:
        c.execute(text('UPDATE state_result_publication SET batch_id=:id'),{'id':batch_id})
    with pytest.raises(DBAPIError,match='scope mismatch'),pg.begin() as c:
        wrong=c.scalar(select(Jurisdiction.id).where(Jurisdiction.state_code!=row['state_code'],Jurisdiction.level=='state').limit(1))
        c.execute(StateVoteReturn.__table__.insert().values({**row,'batch_id':batch_id,'jurisdiction_id':wrong}))
    with pytest.raises(DBAPIError,match='discard authoritative'),pg.begin() as c,Operations.context(MigrationContext.configure(c)):
        migration(MIGRATION).downgrade()
