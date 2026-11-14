"""DATA-003 A-I acceptance fixtures: isolated schemas in disposable *_test DB only."""
from __future__ import annotations

from datetime import date, datetime, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytest.importorskip('psycopg')
from app.database import Base
import app.models
import app.models.ingestion
from app.models.core import (Person, Jurisdiction, DataSource, Election, Contest,
                             Candidacy, PoliticalParty)
from app.models.election import (Office, BallotLine, CanonicalResultBatch,
                                 CanonicalPublication, CanonicalVoteReturn,
                                 CanonicalMaterializationIssue)
from app.models.geography import GeographicReference, GeographicResolution
from app.models.ingestion import (ElectionResultObservation, SourceRelease,
                                  SourceActiveYear, IngestionRun)
from app.services import elections
from app.services.canonical_results import (MaterializationError,
                                             materialize_medsl_year, candidate_totals)


@pytest.fixture
def pg_engine():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL required')
    if not (make_url(url).database or '').endswith('_test'):
        pytest.fail('Refusing to modify non-test database')
    schema = 'data003_test_' + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _begin_repeatable(session):
    session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))


def _seed(session, year=2008):
    source = DataSource(name='medsl_presidential_county')
    ref_source = DataSource(name='census_state_county_georef')
    session.add_all([source, ref_source]); session.flush()
    release = SourceRelease(source_id=source.id, version='20.0', sha256='1'*64,
        filename='medsl.csv', file_id=1, download_url='fixture',raw_path='fixture',
        retrieved_at=datetime.now(timezone.utc),metadata_json={})
    reference_release = SourceRelease(source_id=ref_source.id, version='cbp', sha256='2'*64,
        filename='ref.csv', file_id=2,download_url='fixture',raw_path='fixture',
        retrieved_at=datetime.now(timezone.utc),metadata_json={})
    session.add_all([release,reference_release]);session.flush()
    run = IngestionRun(source_id=source.id,release_id=release.id,status='SUCCEEDED',
        started_at=datetime.now(timezone.utc),records_read=0,
        warnings_json=[],errors_json=[],options_json={})
    session.add(run);session.flush()
    session.add(SourceActiveYear(source_id=source.id, year=year,
        release_id=release.id,run_id=run.id));session.flush()
    state=Jurisdiction(name='New York',level='state',state_code='NY')
    county=Jurisdiction(name='Albany',level='county',state_code='NY')
    session.add_all([state, county]);session.flush()
    ref=GeographicReference(release_id=reference_release.id,jurisdiction_id=county.id,
        kind='county',geoid='36001',state_fips='36',name_raw='Albany',name_key='albany',
        vintage_start=year,vintage_end=year)
    session.add(ref);session.flush()
    return dict(source=source, release=release,reference_release=reference_release,
                run=run,state=state,county=county,ref=ref)


def _observe(session, seed, n, *, name='ALICE EXAMPLE', votes=100, total=200,
             kind='candidate', mode='TOTAL', logical=None, status='RESOLVED',
             geography=True):
    row = ElectionResultObservation(release_id=seed['release'].id,
        source_row_number=n,row_sha256=f'{n:064x}',logical_key=logical or f'{n:064x}',
        year=2008,state_code='NY',state_fips='36',county_fips=seed['ref'].geoid,
        county_raw=seed['ref'].name_raw,county_normalized=seed['ref'].name_raw.upper(),office_raw='US PRESIDENT',
        candidate_raw=name,candidate_normalized=name,
        candidate_kind=kind,mode_normalized=mode,candidate_votes=votes,
        total_votes=total,raw_json={'candidate':name},warnings_json=[])
    session.add(row);session.flush()
    if geography:
        geo = GeographicResolution(observation_id=row.id,
            reference_release_id=seed['reference_release'].id,
            reference_id=seed['ref'].id if status in {'RESOLVED','RESOLVED_HISTORICAL'} else None,
            jurisdiction_id=seed['county'].id if status in {'RESOLVED','RESOLVED_HISTORICAL'} else None,
            status=status,method='FIXTURE',reason='deterministic fixture',
            evidence_json={},ruleset_version='fixture-v1')
        session.add(geo);session.flush()
    return row


def test_a_general_write_in_aggregate_unresolved_identity_and_idempotence(pg_engine):
    with Session(pg_engine) as s, s.begin():
        seed = _seed(s)
        rows = [_observe(s, seed, i, name=name,votes=votes,total=187,kind=kind)
            for i,(name,votes,kind) in enumerate([
                ('ALICE EXAMPLE',100,'candidate'),('BOB EXAMPLE',80,'candidate'),
                ('WRITEIN',2,'write_in'),('OTHER',5,'aggregate')],start=2)]
        original = [(r.id,r.row_sha256,r.candidacy_id) for r in rows]
    with Session(pg_engine) as s, s.begin():
        _begin_repeatable(s)
        preview=materialize_medsl_year(s, year=2008)
        assert preview['input_rows']==4 and preview['accepted_rows']==4
        assert preview['status']=='COMPLETE' and preview['dry_run']
        assert s.scalar(select(func.count()).select_from(CanonicalResultBatch))==0
    with Session(pg_engine) as s, s.begin():
        _begin_repeatable(s)
        made=materialize_medsl_year(s, year=2008,dry_run=False)
        assert made['action']=='CREATED' and made['eligible_canonical_votes']==187
        assert s.scalar(select(func.count()).select_from(CanonicalVoteReturn))==4
        assert s.scalar(select(func.count()).select_from(Person))==0
        assert s.scalar(select(func.count()).select_from(Candidacy))==2
        assert s.scalar(select(func.count()).select_from(BallotLine))==0
        assert all(r.person_id is None for r in s.scalars(select(Candidacy)))
        contest_id=s.scalar(select(Contest.id))
        totals=candidate_totals(s,batch_id=__import__('uuid').UUID(made['batch_id']),contest_id=contest_id,reporting_level='county')
        assert sorted(r['votes'] for r in totals)==[80,100]
        assert all(r['basis']=='candidate_total' for r in totals)
        assert s.scalar(select(func.count()).select_from(Election))==1
    with Session(pg_engine) as s, s.begin():
        _begin_repeatable(s)
        repeated=materialize_medsl_year(s,year=2008,dry_run=False)
        assert repeated['action']=='UNCHANGED' and repeated['batch_id']==made['batch_id']
        assert [(r.id,r.row_sha256,r.candidacy_id) for r in s.scalars(select(ElectionResultObservation).order_by(ElectionResultObservation.source_row_number))]==original


def test_b_c_primary_runoff_linking_and_party_evidence(pg_engine):
    with Session(pg_engine) as s,s.begin():
        j=Jurisdiction(name='Test State',level='state',state_code='NY')
        p=PoliticalParty(name='DEMOCRATIC')
        s.add_all([j,p]);s.flush()
        office=elections.office(s,creation_key='state:governor',name='Governor',
            office_kind='executive',jurisdiction_id=j.id)
        primary=elections.election(s,creation_key='2024-prim',election_date=date(2024,6,1),
            election_type='primary',jurisdiction_id=j.id,election_cycle=2024)
        initial=elections.contest(s,creation_key='prim-gov',office_name='Governor',
            election_id=primary.id, jurisdiction_id=j.id,office_id=office.id,
            nomination_party_id=p.id)
        a=elections.candidacy(s,creation_key='candidateA',contest_id=initial.id,
            source_label='A',party_id=p.id)
        b=elections.candidacy(s,creation_key='candidateB',contest_id=initial.id,
            source_label='B',party_id=p.id)
        assert a.id!=b.id and a.person_id is None
        runoff=elections.election(s,creation_key='2024-runoff',election_date=date(2024,7,1),
            election_type='runoff',jurisdiction_id=j.id,parent_election_id=primary.id,
            election_cycle=2024)
        follow=elections.contest(s,creation_key='runoff-gov',office_name='Governor',
            election_id=runoff.id,jurisdiction_id=j.id,office_id=office.id,
            preceding_contest_id=initial.id,nomination_party_id=p.id)
        assert follow.id!=initial.id and follow.preceding_contest_id==initial.id
        assert elections.election(s,creation_key='2024-runoff',election_date=date(2024,7,1),
            election_type='runoff',jurisdiction_id=j.id,parent_election_id=primary.id,
            election_cycle=2024).id==runoff.id


def test_d_fusion_has_one_candidacy_two_ballot_lines(pg_engine):
    with Session(pg_engine) as s,s.begin():
        j=Jurisdiction(name='NY',level='state',state_code='NY')
        p=PoliticalParty(name='DEMOCRATIC');q=PoliticalParty(name='WORKING FAMILIES')
        s.add_all([j,p,q]);s.flush()
        event=elections.election(s,creation_key='2024-g',election_date=date(2024,11,5),
            election_type='general',jurisdiction_id=j.id)
        c=elections.contest(s,creation_key='2024-gov',office_name='Governor',
            election_id=event.id,jurisdiction_id=j.id)
        person=elections.candidacy(s,creation_key='2024-gov-X',contest_id=c.id,
            source_label='Candidate X',party_id=p.id)
        first=elections.ballot_line(s,creation_key='line-D',candidacy_id=person.id,
            line_label='Democratic',line_kind='party',party_id=p.id)
        second=elections.ballot_line(s,creation_key='line-W',candidacy_id=person.id,
            line_label='Working Families',line_kind='party',party_id=q.id)
        assert first.id != second.id
        assert s.scalar(select(func.count()).select_from(Candidacy))==1
        assert s.scalar(select(func.count()).select_from(BallotLine))==2
        assert elections.ballot_line(s,creation_key='line-D',candidacy_id=person.id,
            line_label='Democratic',line_kind='party',party_id=p.id).id==first.id
        with pytest.raises(ValueError):
            elections.ballot_line(s,creation_key='line-W',candidacy_id=person.id,
                line_label='Changed',line_kind='party',party_id=q.id)


def test_g_i_missing_conflicts_geography_and_mode_excluded(pg_engine):
    with Session(pg_engine) as s,s.begin():
        seed=_seed(s)
        _observe(s,seed,2,name='ALICE EXAMPLE',votes=100,logical='same')
        _observe(s,seed,3,name='ALICE EXAMPLE',votes=100,logical='same')
        _observe(s,seed,4,name='BOB EXAMPLE',votes=None)
        _observe(s,seed,5,name='CAROL EXAMPLE',votes=20,mode='ABSENTEE')
        _observe(s,seed,6,name='DAN EXAMPLE',votes=10,status='UNRESOLVED')
        _observe(s,seed,8,name='FIONA EXAMPLE',votes=0)
        # Independent verified county remains eligible despite incomplete Albany.
        county2=Jurisdiction(name='Rensselaer',level='county',state_code='NY')
        s.add(county2);s.flush()
        ref2=GeographicReference(release_id=seed['reference_release'].id,
            jurisdiction_id=county2.id,kind='county',geoid='36083',state_fips='36',
            name_raw='Rensselaer',name_key='rensselaer',vintage_start=2008,vintage_end=2008)
        s.add(ref2);s.flush()
        seed2={**seed,'county':county2,'ref':ref2}
        _observe(s,seed2,7,name='ERIN EXAMPLE',votes=2,total=2)
        county3=Jurisdiction(name='Ulster',level='county',state_code='NY')
        s.add(county3);s.flush()
        ref3=GeographicReference(release_id=seed['reference_release'].id,
            jurisdiction_id=county3.id,kind='county',geoid='36111',state_fips='36',
            name_raw='Ulster',name_key='ulster',vintage_start=2008,vintage_end=2008)
        s.add(ref3);s.flush()
        seed3={**seed,'county':county3,'ref':ref3}
        _observe(s,seed3,9,name='GINA EXAMPLE',votes=12,total=20)
        _observe(s,seed3,10,name='HENRY EXAMPLE',votes=8,total=21)
    with Session(pg_engine) as s,s.begin():
        _begin_repeatable(s)
        preview=materialize_medsl_year(s,year=2008)
        assert preview['accepted_rows']==1 and preview['excluded_rows']==8
        assert preview['issue_counts']=={
            'DUPLICATE_LOGICAL_KEY':2, 'GEOGRAPHY_NOT_RESOLVED':1,
            'MISSING_VOTES':1,'UNSUPPORTED_VOTING_MODE':1,
            'REPORTING_UNIT_INCOMPLETE':1,'CONFLICTING_REPORTED_TOTAL':2}
        with pytest.raises(MaterializationError):
            materialize_medsl_year(s,year=2008,dry_run=False)
    with Session(pg_engine) as s,s.begin():
        _begin_repeatable(s)
        actual=materialize_medsl_year(s,year=2008,dry_run=False,allow_partial=True)
        assert actual['status']=='PARTIAL'
        assert s.scalar(select(func.count()).select_from(CanonicalMaterializationIssue))==8
        assert s.scalar(select(func.count()).select_from(CanonicalVoteReturn))==1


def test_h_active_release_change_preserves_previous_batch(pg_engine):
    with Session(pg_engine) as s,s.begin():
        seed=_seed(s)
        _observe(s,seed,2,name='ALICE EXAMPLE',votes=100,total=100)
        original_release_id=seed['release'].id
        original_source_id=seed['source'].id
        geographic_release_id=seed['reference_release'].id
        county_id=seed['county'].id
        reference_id=seed['ref'].id
    with Session(pg_engine) as s,s.begin():
        _begin_repeatable(s)
        first=materialize_medsl_year(s,year=2008,dry_run=False)
    with Session(pg_engine) as s,s.begin():
        prior=s.get(SourceRelease,original_release_id)
        alternate=SourceRelease(source_id=prior.source_id,version='21.0',sha256='3'*64,
            filename='medsl2.csv',file_id=3,download_url='fixture',raw_path='fixture',
            retrieved_at=datetime.now(timezone.utc),metadata_json={})
        s.add(alternate);s.flush()
        seed2={'release':alternate, 'reference_release':s.get(SourceRelease,geographic_release_id),
               'county':s.get(Jurisdiction,county_id),
               'ref':s.get(GeographicReference,reference_id)}
        _observe(s,seed2,3,name='ALICE EXAMPLE',votes=111,total=111)
        active=s.get(SourceActiveYear,(original_source_id,2008))
        active.release_id=alternate.id
    with Session(pg_engine) as s,s.begin():
        _begin_repeatable(s)
        next_=materialize_medsl_year(s,year=2008,dry_run=False)
        assert next_['batch_id']!=first['batch_id']
        assert next_['eligible_canonical_votes']==111
        old=s.get(CanonicalResultBatch,__import__('uuid').UUID(first['batch_id']))
        assert old.canonical_votes==100
        assert s.get(CanonicalPublication,next_['scope']).batch_id==__import__('uuid').UUID(next_['batch_id'])
        assert s.scalar(select(func.count()).select_from(ElectionResultObservation))==2
        assert s.scalar(select(func.count()).select_from(CanonicalResultBatch))==2


def test_constraints_and_transaction_rollback(pg_engine):
    with Session(pg_engine) as s,s.begin():
        j=Jurisdiction(name='Test',level='state',state_code='NY')
        s.add(j);s.flush()
        item=elections.election(s,creation_key='unique-event',election_date=date(2024,11,5),
            election_type='general',jurisdiction_id=j.id)
        with pytest.raises(IntegrityError):
            with s.begin_nested():
                s.add(Election(creation_key='unique-event',election_date=date(2024,11,5),
                    election_type='general',jurisdiction_id=j.id))
                s.flush()
    with pytest.raises(RuntimeError):
        with Session(pg_engine) as s,s.begin():
            j=s.scalar(select(Jurisdiction.id))
            elections.election(s,creation_key='rolled-back',election_date=date(2024,11,6),
                election_type='general',jurisdiction_id=j)
            raise RuntimeError('rollback')
    with Session(pg_engine) as s:
        assert s.scalar(select(Election).where(Election.creation_key=='rolled-back')) is None
        assert s.scalar(select(func.count()).select_from(Election))==1


def test_fusion_vote_returns_aggregate_once_and_reject_mixed_basis(pg_engine):
    with Session(pg_engine) as s, s.begin():
        seed = _seed(s)
        a = _observe(s, seed, 2, name='FUSION CANDIDATE', votes=60)
        b = _observe(s, seed, 3, name='FUSION CANDIDATE', votes=40)
        c = _observe(s, seed, 4, name='FUSION CANDIDATE', votes=100)
        election=elections.election(s, creation_key='fusion-event',
            election_date=date(2008,11,4),election_type='general',jurisdiction_id=seed['state'].id)
        contest=elections.contest(s,creation_key='fusion-contest',office_name='U.S. President',
            election_id=election.id,jurisdiction_id=seed['state'].id)
        cand=elections.candidacy(s,creation_key='fusion-candidate',contest_id=contest.id,
            source_label='FUSION CANDIDATE')
        party1=PoliticalParty(name='DEMOCRATIC');party2=PoliticalParty(name='WORKING FAMILIES')
        s.add_all([party1,party2]);s.flush()
        lines=[elections.ballot_line(s,creation_key=f'fusion-line-{i}',candidacy_id=cand.id,
            line_label=p.name,line_kind='party',party_id=p.id) for i,p in enumerate([party1,party2])]
        batch=CanonicalResultBatch(scope_key='fusion:test',fingerprint='a'*64,
            ruleset_version='fixture',source_release_id=seed['release'].id,
            reference_release_id=seed['reference_release'].id,election_year=2008,
            status='COMPLETE',input_rows=3,accepted_rows=3,excluded_rows=0,
            raw_votes_nonadditive=200,canonical_votes=200)
        s.add(batch);s.flush()
        for obs,line in zip([a,b],lines):
            geo=s.scalar(select(GeographicResolution).where(GeographicResolution.observation_id==obs.id))
            s.add(CanonicalVoteReturn(batch_id=batch.id,observation_id=obs.id,
                contest_id=contest.id,jurisdiction_id=seed['county'].id,
                geographic_resolution_id=geo.id,candidacy_id=cand.id,ballot_line_id=line.id,
                source_label=obs.candidate_raw,reporting_level='county',reporting_mode='TOTAL',
                vote_kind='ballot_line',votes=obs.candidate_votes))
        s.flush()
        assert candidate_totals(s,batch_id=batch.id,contest_id=contest.id,reporting_level='county')[0]['votes']==100
        # An additional candidate-total observation is NOT additive with lines.
        geo=s.scalar(select(GeographicResolution).where(GeographicResolution.observation_id==c.id))
        s.add(CanonicalVoteReturn(batch_id=batch.id,observation_id=c.id,
            contest_id=contest.id,jurisdiction_id=seed['county'].id,
            geographic_resolution_id=geo.id,candidacy_id=cand.id,
            source_label=c.candidate_raw,reporting_level='county',reporting_mode='TOTAL',
            vote_kind='candidate_total',votes=100))
        s.flush()
        with pytest.raises(MaterializationError,match='overlap'):
            candidate_totals(s,batch_id=batch.id,contest_id=contest.id,reporting_level='county')


def test_data003_postgres_migration_preserves_existing_rows(pg_engine):
    """On a separate schema install old migrations then upgrade/downgrade DATA-003."""
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    # Use a second schema (not metadata.create_all fixture schema) so the
    # complete migration chain can be replayed without table collisions.
    url = os.environ['TEST_DATABASE_URL']
    name = 'data003_migrate_' + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{name}"'))
    e = create_engine(url,connect_args={'options':f'-csearch_path={name}'})
    filenames = ['2c9541d24f1e_initial_election_schema.py',
                 '75c2f4a1d9be_ingestion.py',
                 'c1f7a2b98d40_geographic_reference.py',
                 'b3d62a17f8ac_geographic_remediation.py',
                 'd002a150fd10_identity_foundation.py',
                 'd003f93a1700_election_canonical.py']
    mods=[]
    for f in filenames:
        spec=importlib.util.spec_from_file_location('data003_migration_'+f[:12],
            Path(__file__).parents[1]/'migrations'/'versions'/f)
        mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod);mods.append(mod)
    try:
        with e.begin() as c:
            with Operations.context(MigrationContext.configure(c)):
                for mod in mods[:-1]:
                    mod.upgrade()
            person_id, jurisdiction_id, election_id, contest_id, candidacy_id=(uuid4() for _ in range(5))
            c.execute(text('INSERT INTO person (id,full_name) VALUES (:i,\'Fixture person\')'),{'i':person_id})
            c.execute(text('INSERT INTO jurisdiction (id,name,level) VALUES (:i,\'Fixture\',\'state\')'),{'i':jurisdiction_id})
            c.execute(text('INSERT INTO election (id,election_date,election_type,jurisdiction_id) VALUES (:i,\'2008-11-04\',\'general\',:j)'),{'i':election_id,'j':jurisdiction_id})
            c.execute(text('INSERT INTO contest (id,office_name,election_id,jurisdiction_id) VALUES (:i,\'President\',:e,:j)'),{'i':contest_id,'e':election_id,'j':jurisdiction_id})
            c.execute(text('INSERT INTO candidacy (id,person_id,contest_id) VALUES (:i,:p,:c)'),{'i':candidacy_id,'p':person_id,'c':contest_id})
            with Operations.context(MigrationContext.configure(c)):
                mods[-1].upgrade()
            assert c.scalar(text('SELECT count(*) FROM person WHERE id=:i'),{'i':person_id})==1
            assert c.scalar(text('SELECT count(*) FROM candidacy WHERE id=:i'),{'i':candidacy_id})==1
            nullability=c.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='candidacy' AND column_name='person_id'"))
            assert nullability=='YES'
            with Operations.context(MigrationContext.configure(c)):
                mods[-1].downgrade()
            assert c.scalar(text('SELECT count(*) FROM candidacy WHERE id=:i'),{'i':candidacy_id})==1
            assert c.scalar(text('SELECT count(*) FROM person WHERE id=:i'),{'i':person_id})==1
    finally:
        e.dispose()
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        admin.dispose()
