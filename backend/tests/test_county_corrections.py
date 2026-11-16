"""Apply reviewed votes without rewriting source/history or weakening eligibility."""
from copy import deepcopy
from hashlib import sha256
from uuid import UUID
import pytest
from sqlalchemy import event,func,select,text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from ingestion.data005 import digest
from ingestion.county_corrections import validate_changes,AUTHORIZATION
from app.models.core import DataSource
from app.models.ingestion import ElectionResultObservation
from app.models.election import CanonicalResultBatch,CanonicalVoteReturn,CanonicalPublication
from app.models.county_corrections import CountyCorrectionBatch,CountyVoteCorrection
from app.services.canonical_results import _plan,materialize_medsl_year
from app.services.county_corrections import prepare,publish,SCOPE
from test_data003_postgres import pg_engine,_seed,_observe
from test_data004_postgres import pg,migration


def fixture_review(engine,tmp_path):
    raw=tmp_path/'source.csv';raw.write_bytes(b'immutable source fixture')
    with Session(engine) as s,s.begin():
        seed=_seed(s);seed['release'].raw_path=str(raw);seed['release'].sha256=sha256(raw.read_bytes()).hexdigest()
        for n,(b,v,k) in enumerate([('BARACK OBAMA',100,'candidate'),('JOHN MCCAIN',80,'candidate'),('OTHER',5,'aggregate')],2):
            _observe(s,seed,n,name=b,votes=v,total=185,kind=k)
    with Session(engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        made=materialize_medsl_year(s,year=2008,dry_run=False)
        base=_plan(s,2008,None)
        o,g,_,_=base['accepted'][0]
        change=dict(observation_id=str(o.id),row_sha256=o.row_sha256,observed_votes=100,official_votes=101,
            proposed_votes=101,vote_adjustment=1,state='NY',source_fips='36001',candidate_bucket='BARACK OBAMA',
            disposition='AUTHORITY_CORRECTION_EVIDENCED',election_year=2008,reporting_level='county',
            election_stage='general',vote_mode='TOTAL',canonical_preview_accepted=True)
        return dict(changes=[change],review_sha256=digest([change]),evidence_files=[],
            proposal=dict(current_canonical_preview=dict(fingerprint=base['fingerprint']),
                source_release=dict(id=str(base['release'].id)),current_county_batch=dict(id=made['batch_id'],fingerprint=made['fingerprint'])))


def apply(s,review,tmp_path,fingerprint):
    return publish(s,review,expected_fingerprint=fingerprint,actor='test-agent',archive_dir=tmp_path/'archive',root=tmp_path)


def test_review_scope_rejects_withheld_duplicates_and_incompatible_groups():
    row=dict(observation_id='1',row_sha256='a'*64,observed_votes=10,proposed_votes=11,official_votes=11,
        vote_adjustment=1,disposition='AUTHORITY_CORRECTION_EVIDENCED',election_year=2008,
        reporting_level='county',election_stage='general',vote_mode='TOTAL',canonical_preview_accepted=True)
    validate_changes([row],digest([row]),1)
    for key,value in [('disposition','OFFICIAL_INTERNAL_CONFLICT'),('reporting_level','district'),
                      ('election_year',2012),('vote_mode','ABSENTEE'),('canonical_preview_accepted',False)]:
        wrong=[{**row,key:value}]
        with pytest.raises(ValueError,match='scope'):validate_changes(wrong,digest(wrong),1)
    with pytest.raises(ValueError,match='Duplicate'):validate_changes([row,row],digest([row,row]),2)
    with pytest.raises(ValueError,match='digest'):validate_changes([row],'0'*64,1)


def test_apply_replay_and_default_planner_preserve_raw_votes_and_old_batches(pg_engine,tmp_path):
    review=fixture_review(pg_engine,tmp_path)
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        preview=prepare(s,review)
        assert preview['votes']==186 and preview['status']=='PARTIAL'
        assert s.scalar(select(func.count()).select_from(CountyCorrectionBatch))==0
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        made=apply(s,review,tmp_path,preview['fingerprint'])
        assert made['action']=='CREATED'
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        replay=apply(s,review,tmp_path,preview['fingerprint'])
        assert replay['action']=='UNCHANGED' and replay['batch_id']==made['batch_id']
        assert _plan(s,2008,None)['target_sum']==186
        assert materialize_medsl_year(s,year=2008,dry_run=False,allow_partial=True)['action']=='UNCHANGED'
        assert sum(s.scalars(select(ElectionResultObservation.candidate_votes)))==185
        batches=list(s.scalars(select(CanonicalResultBatch).order_by(CanonicalResultBatch.created_at)))
        assert len(batches)==2 and sorted(b.canonical_votes for b in batches)==[185,186]
        new=s.get(CanonicalResultBatch,UUID(made['batch_id']))
        assert str(new.supersedes_id)==review['proposal']['current_county_batch']['id']
        assert s.scalar(select(func.count()).select_from(CountyVoteCorrection))==1
        assert s.scalar(select(CountyCorrectionBatch.authorization_note))==AUTHORIZATION
        assert s.scalar(select(func.count()).select_from(CanonicalVoteReturn).where(CanonicalVoteReturn.correction_id.is_not(None)))==1


def test_stale_digest_excluded_observation_and_corrupt_archive_fail_closed(pg_engine,tmp_path):
    review=fixture_review(pg_engine,tmp_path)
    with pytest.raises(ValueError,match='Stale publication'),Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        apply(s,review,tmp_path,'0'*64)
    with Session(pg_engine) as s:
        assert s.scalar(select(func.count()).select_from(CountyCorrectionBatch))==0
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        made=apply(s,review,tmp_path,prepare(s,review)['fingerprint'])
    with Session(pg_engine) as s:
        b=s.get(CountyCorrectionBatch,UUID(made['correction_batch_id']))
        from app.models.ingestion import SourceRelease
        release=s.get(SourceRelease,b.source_release_id)
        from pathlib import Path
        Path(release.raw_path).write_bytes(b'corrupt archive')
    with pytest.raises(ValueError,match='archive checksum'),Session(pg_engine) as s:
        _plan(s,2008,None)


def test_failed_publication_rolls_back_every_database_write(pg_engine,tmp_path):
    review=fixture_review(pg_engine,tmp_path)
    def fail(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO canonical_publication'):raise RuntimeError('simulated publication failure')
    event.listen(pg_engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='simulated'),Session(pg_engine) as s,s.begin():
            s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
            apply(s,review,tmp_path,prepare(s,review)['fingerprint'])
    finally:event.remove(pg_engine,'before_cursor_execute',fail)
    with Session(pg_engine) as s:
        assert s.scalar(select(func.count()).select_from(CountyCorrectionBatch))==0
        assert s.scalar(select(func.count()).select_from(CountyVoteCorrection))==0
        assert s.scalar(select(func.count()).select_from(CanonicalResultBatch))==1
        assert s.scalar(select(func.count()).select_from(DataSource).where(DataSource.name=='official_presidential_county_corrections'))==0


def test_newly_excluded_observation_cannot_be_amended(pg_engine,tmp_path):
    review=fixture_review(pg_engine,tmp_path)
    with Session(pg_engine) as s,s.begin():
        from app.models.geography import GeographicResolution
        geo=s.scalar(select(GeographicResolution).where(GeographicResolution.observation_id==UUID(review['changes'][0]['observation_id'])))
        geo.status='UNRESOLVED'
        geo.reference_id=None
        geo.jurisdiction_id=None
    with Session(pg_engine) as s:
        review['proposal']['current_canonical_preview']['fingerprint']=_plan(s,2008,None)['fingerprint']
        with pytest.raises(ValueError,match='not currently eligible'):prepare(s,review)


def test_county_supersession_does_not_republish_fec_authority(pg_engine,tmp_path):
    from test_fec_state_authority import seed_comparison,official_fixture
    from app.services import fec_state_results as fec
    from app.models.state_results import StateResultBatch
    prior=seed_comparison(pg_engine,tmp_path)
    evidence=official_fixture(tmp_path/'fec')
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        fec_preview=fec.plan(s,evidence)
        state=fec.publish(s,evidence,expected_fingerprint=fec_preview['fingerprint'],actor='test',archive_dir=tmp_path/'fec-archive')
        base=_plan(s,2008,None)
        o,g,_,_=base['accepted'][0]
        change=dict(observation_id=str(o.id),row_sha256=o.row_sha256,observed_votes=100,official_votes=101,
            proposed_votes=101,vote_adjustment=1,state='NY',source_fips='36001',candidate_bucket='BARACK OBAMA',
            disposition='AUTHORITY_CORRECTION_EVIDENCED',election_year=2008,reporting_level='county',
            election_stage='general',vote_mode='TOTAL',canonical_preview_accepted=True)
        review=dict(changes=[change],review_sha256=digest([change]),evidence_files=[],
            proposal=dict(current_canonical_preview=dict(fingerprint=base['fingerprint']),
                source_release=dict(id=str(base['release'].id)),current_county_batch=dict(id=prior['batch_id'],fingerprint=prior['fingerprint'])))
        apply(s,review,tmp_path,prepare(s,review)['fingerprint'])
    with Session(pg_engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        assert fec.plan(s,evidence)['fingerprint']==fec_preview['fingerprint']
        replay=fec.publish(s,evidence,expected_fingerprint=fec_preview['fingerprint'],actor='test',archive_dir=tmp_path/'fec-archive')
        assert replay['action']=='UNCHANGED' and replay['batch_id']==state['batch_id']
        assert s.scalar(select(func.count()).select_from(StateResultBatch))==1


def test_real_migration_guards_history_and_corrected_vote_lineage(pg,tmp_path):
    with pg.begin() as c,Operations.context(MigrationContext.configure(c)):
        migration('d005fec2008a_authoritative_state_results.py').upgrade()
        migration('d005county01_reviewed_county_corrections.py').upgrade()
    review=fixture_review(pg,tmp_path)
    with Session(pg) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        made=apply(s,review,tmp_path,prepare(s,review)['fingerprint'])
    for table in ('county_correction_batch','county_vote_correction','canonical_result_batch','canonical_vote_return'):
        with pytest.raises(DBAPIError,match='append-only'),pg.begin() as c:
            c.execute(text(f'DELETE FROM {table}'))
    with pytest.raises(DBAPIError,match='Invalid canonical correction lineage'),pg.begin() as c:
        c.execute(text('''INSERT INTO canonical_vote_return SELECT gen_random_uuid(),batch_id,observation_id,
            contest_id,jurisdiction_id,geographic_resolution_id,candidacy_id,ballot_line_id,source_label,
            reporting_level,reporting_mode,vote_kind,votes+1,correction_id FROM canonical_vote_return
            WHERE correction_id IS NOT NULL'''))
    with pg.connect() as c:
        original=dict(c.execute(select(CanonicalResultBatch.__table__).where(CanonicalResultBatch.id==UUID(made['batch_id']))).mappings().one())
    from uuid import uuid4
    incomplete=uuid4()
    with pg.begin() as c:
        c.execute(CanonicalResultBatch.__table__.insert().values({**original,'id':incomplete,'fingerprint':'f'*64}))
    with pytest.raises(DBAPIError,match='Incomplete corrected'),pg.begin() as c:
        c.execute(text('UPDATE canonical_publication SET batch_id=:id'),{'id':incomplete})
    with pg.begin() as c,Operations.context(MigrationContext.configure(c)):
        with pytest.raises(RuntimeError,match='history'):
            migration('d005county01_reviewed_county_corrections.py').downgrade()
