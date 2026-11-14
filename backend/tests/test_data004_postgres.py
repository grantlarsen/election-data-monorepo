"""DATA-004 contracts exercised against real PostgreSQL migrations, never SQLite."""
from datetime import date, datetime, timezone
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models.core import DataSource, Jurisdiction
from app.models.geography import (GeographicReference, GeographicResolution,
    GeographicResolutionContext, JurisdictionBoundaryVintage, JurisdictionIdentifier,
    JurisdictionRelationship)
from app.models.ingestion import SourceRelease, SourceActiveYear, ElectionResultObservation
from app.services.geography import resolve_identifier
from ingestion.geography.resolve import resolve_medsl

pytestmark = pytest.mark.integration
FILES = [
    '2c9541d24f1e_initial_election_schema.py', '75c2f4a1d9be_ingestion.py',
    'c1f7a2b98d40_geographic_reference.py', 'b3d62a17f8ac_geographic_remediation.py',
    'd002a150fd10_identity_foundation.py', 'd003f93a1700_election_canonical.py',
    'd004a9c21e70_versioned_geography.py',
]


def migration(filename):
    path = Path(__file__).parents[1] / 'migrations' / 'versions' / filename
    spec = importlib.util.spec_from_file_location('data004_' + filename[:12], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pg():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Requires TEST_DATABASE_URL')
    if not (make_url(url).database or '').endswith('_test'):
        pytest.fail('Refusing to modify a non-test database')
    schema = 'data004_' + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as c:
        c.execute(text('CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public'))
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    e = create_engine(url, connect_args={'options':f'-csearch_path={schema},public'})
    try:
        with e.begin() as c, Operations.context(MigrationContext.configure(c)):
            for filename in FILES:
                migration(filename).upgrade()
        yield e
    finally:
        e.dispose()
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed(s, kind='county'):
    source = DataSource(name='dated_fixture')
    j = Jurisdiction(name='Example',level=kind,state_code='VA')
    parent = Jurisdiction(name='Virginia',level='state',state_code='VA')
    other = Jurisdiction(name='Separate identity',level=kind,state_code='VA')
    s.add_all([source,j,parent,other]); s.flush()
    rels, refs = [], []
    for n in (1,2):
        rel = SourceRelease(source_id=source.id,version=str(n),sha256=str(n)*64,
            filename='fixture',file_id=n,download_url='https://example.invalid/evidence',
            raw_path='fixture',retrieved_at=datetime.now(timezone.utc),metadata_json={})
        s.add(rel);s.flush();rels.append(rel)
        ref = GeographicReference(release_id=rel.id,jurisdiction_id=j.id,kind=kind,
            geoid='5101' if kind=='congressional_district' else '51001',state_fips='51',
            name_raw='Example',name_key='EXAMPLE',vintage_start=2000,vintage_end=2030)
        s.add(ref);s.flush();refs.append(ref)
    return j,parent,other,rels,refs


def boundary(s,j,ref,label,start,end):
    row = JurisdictionBoundaryVintage(jurisdiction_id=j.id,reference_id=ref.id,
        version_label=label,valid_from=start,valid_until=end,
        evidence_url='https://example.invalid/legal-order',evidence_note='Synthetic legal-date fixture')
    s.add(row);s.flush()
    return row


@pytest.mark.parametrize('kind',['county','congressional_district'])
def test_identity_multiple_nonoverlapping_vintages_and_endpoints(pg,kind):
    with Session(pg) as s,s.begin():
        j,_,_,rels,refs=seed(s,kind)
        first=boundary(s,j,refs[0],'old',date(2000,1,1),date(2013,1,3))
        second=boundary(s,j,refs[1],'new',date(2013,1,3),None)
        for d,expected in [(date(2013,1,2),first.id),(date(2013,1,3),second.id)]:
            b=JurisdictionBoundaryVintage
            assert s.scalar(select(b.id).where(b.jurisdiction_id==j.id,b.valid_from<=d,
                b.valid_until.is_(None)|(b.valid_until>d)))==expected
        assert refs[0].id!=refs[1].id and refs[0].jurisdiction_id==refs[1].jurisdiction_id
        for a,b in [(date(2012,1,1),date(2014,1,1)),(date(2020,1,1),None),
                    (date(1999,1,1),date(2000,1,2)),(date(2010,1,1),date(2010,1,1))]:
            with pytest.raises(IntegrityError), s.begin_nested():
                boundary(s,j,refs[1],uuid4().hex,a,b)
        with pytest.raises(IntegrityError),s.begin_nested():
            boundary(s,j,refs[0],'old',date(1900,1,1),date(1901,1,1))


def test_identifiers_and_historical_containment_require_evidence_and_identity(pg):
    with Session(pg) as s,s.begin():
        j,parent,other,rels,refs=seed(s)
        for n,ref in enumerate(refs):
            # Synthetic, explicitly assigned recode: identity survives a changed
            # released identifier; lookup must never invent a cross-release alias.
            ref.geoid='51001' if n==0 else '51003'
            s.add(JurisdictionIdentifier(jurisdiction_id=j.id,reference_id=ref.id,scheme='FIPS_COUNTY',
                value=ref.geoid,valid_from=date(2000+10*n,1,1),valid_until=date(2010+10*n,1,1),
                validity_evidence_url='https://example.invalid/legal'))
            s.add(JurisdictionRelationship(parent_id=parent.id if n==0 else other.id,child_id=j.id,
                reference_id=ref.id,valid_from=date(2000+10*n,1,1),valid_until=date(2010+10*n,1,1),
                validity_evidence_url='https://example.invalid/legal'))
        s.flush()
        for n,ref in enumerate(refs):
            args=dict(release_id=rels[n].id,kind='county',scheme='FIPS_COUNTY',
                      value=ref.geoid,as_of=date(2005+10*n,1,1))
            assert resolve_identifier(s,**args)['jurisdiction_id']==str(j.id)
            assert resolve_identifier(s,**{**args,'value':refs[1-n].geoid})['status']=='UNRESOLVED'
        r=JurisdictionRelationship
        for d,pid in [(date(2009,12,31),parent.id),(date(2010,1,1),other.id)]:
            assert s.scalar(select(r.parent_id).where(r.child_id==j.id,r.valid_from<=d,r.valid_until>d))==pid
        for model,values in [
            (JurisdictionIdentifier,dict(jurisdiction_id=other.id,reference_id=refs[0].id,scheme='X',value='1')),
            (JurisdictionRelationship,dict(parent_id=parent.id,child_id=other.id,reference_id=refs[0].id)),
            (JurisdictionIdentifier,dict(jurisdiction_id=j.id,reference_id=refs[0].id,scheme='Y',value='1',valid_from=date(2000,1,1))),
        ]:
            with pytest.raises(IntegrityError),s.begin_nested():
                s.add(model(**values));s.flush()
        with pytest.raises(IntegrityError),s.begin_nested():
            boundary(s,other,refs[0],'mismatched',date(2000,1,1),None)


def test_release_pinned_dated_lookup_unknown_dates_ambiguity_and_replay(pg):
    with Session(pg) as s,s.begin():
        j,_,other,rels,refs=seed(s,'congressional_district')
        s.add(JurisdictionIdentifier(jurisdiction_id=j.id,reference_id=refs[0].id,scheme='CENSUS_CD',
            value='5101',valid_from=date(2000,1,1),valid_until=date(2013,1,3),
            validity_evidence_url='https://example.invalid/legal'))
        s.add(JurisdictionIdentifier(jurisdiction_id=j.id,reference_id=refs[1].id,scheme='CENSUS_CD',value='5101'))
        s.flush()
        args=dict(release_id=rels[0].id,kind='congressional_district',scheme='CENSUS_CD',value='5101',as_of=date(2012,1,1))
        first=resolve_identifier(s,**args)
        assert first['status']=='RESOLVED' and first['jurisdiction_id']==str(j.id)
        assert resolve_identifier(s,**{**args,'as_of':date(2013,1,3)})['status']=='OUT_OF_VINTAGE'
        assert resolve_identifier(s,**{**args,'release_id':rels[1].id})['status']=='PENDING_REVIEW'
        assert resolve_identifier(s,**{**args,'value':'missing'})['status']=='UNRESOLVED'
        assert resolve_identifier(s,**{**args,'kind':'election_district'})['status']=='INVALID'
        assert resolve_identifier(s,**args)==first
        # A competing source identifier is evidence of ambiguity, never a tie-break.
        extra=GeographicReference(release_id=rels[0].id,jurisdiction_id=other.id,kind='congressional_district',
            geoid='5102',state_fips='51',name_raw='Other',name_key='OTHER',vintage_start=2000,vintage_end=2030)
        s.add(extra);s.flush()
        s.add(JurisdictionIdentifier(jurisdiction_id=other.id,reference_id=extra.id,scheme='CENSUS_CD',value='5101'))
        s.flush()
        ambiguous=resolve_identifier(s,**args)
        assert ambiguous['status']=='AMBIGUOUS' and ambiguous['jurisdiction_id'] is None
        with pytest.raises(IntegrityError),s.begin_nested():
            s.add(JurisdictionIdentifier(jurisdiction_id=j.id,reference_id=refs[0].id,scheme='CENSUS_CD',value='another'));s.flush()


def medsl_fixture(pg):
    from test_geography import fixture_reference,ref_asset,medsl_asset,FIXTURES
    from ingestion.loader import register_run,load
    from ingestion.medsl import normalize,parse_csv
    from ingestion.geography.load import load_reference
    import polars as pl
    run=uuid4()
    source=register_run(pg,run,'census_state_county_georef','fixture',datetime.now(timezone.utc),{})
    load_reference(pg,source,run,ref_asset(),fixture_reference(),{})
    run=uuid4()
    source=register_run(pg,run,'medsl_presidential_county','fixture',datetime.now(timezone.utc),{})
    frame=normalize(parse_csv(str(FIXTURES/'medsl_small.csv'))).filter(pl.col('year_int')==2000)
    load(pg,source,run,medsl_asset(),frame,{2000},[],datetime.now(timezone.utc),datetime.now(timezone.utc),0)


def test_medsl_context_publication_replay_new_references_and_active_release_change(pg):
    medsl_fixture(pg)
    preview,_=resolve_medsl(pg,vintage=2000,publish=False)
    with pg.connect() as c:
        assert c.scalar(select(func.count()).select_from(GeographicResolutionContext))==0
    made,_=resolve_medsl(pg,vintage=2000,actor='fixture',context_manifest=preview['context_manifest'])
    assert made['records_inserted']==6 and made['context_sha256']==preview['context_sha256']
    replay,_=resolve_medsl(pg,vintage=2000,actor='fixture',context_sha256=made['context_sha256'])
    assert replay['records_inserted']==0 and replay['status_counts']=={'RESOLVED':6}
    with Session(pg) as s,s.begin():
        old=s.scalars(select(GeographicReference).where(GeographicReference.kind=='county')).first()
        release=SourceRelease(source_id=s.scalar(select(SourceRelease.source_id).where(SourceRelease.id==old.release_id)),
            version='future',sha256='e'*64,filename='future',file_id=9,download_url='fixture',raw_path='fixture',
            retrieved_at=datetime.now(timezone.utc),metadata_json={})
        s.add(release);s.flush()
        s.add(GeographicReference(release_id=release.id,jurisdiction_id=old.jurisdiction_id,kind='county',
            geoid=old.geoid,state_fips=old.state_fips,name_raw='Changed',name_key='CHANGED',vintage_start=2024,vintage_end=2024))
    fresh,_=resolve_medsl(pg,vintage=2000,publish=False)
    assert fresh['context_sha256']!=made['context_sha256']
    assert fresh['status_counts']!={'RESOLVED':6}
    frozen,_=resolve_medsl(pg,vintage=2000,publish=False,context_sha256=made['context_sha256'])
    assert frozen['status_counts']==made['status_counts']
    with pg.begin() as c:
        c.execute(text('DELETE FROM source_active_year'))
    frozen,_=resolve_medsl(pg,vintage=2000,publish=False,context_sha256=made['context_sha256'])
    assert frozen['status_counts']==made['status_counts']
    with pg.connect() as c:
        assert c.scalar(select(func.count()).select_from(GeographicResolution))==6


def test_append_only_decisions_context_and_chain_scope(pg):
    medsl_fixture(pg)
    made,_=resolve_medsl(pg,vintage=2000,actor='fixture')
    with pg.connect() as c:
        rows=c.execute(select(GeographicResolution.__table__)).mappings().all()
        other_jid=c.scalar(select(Jurisdiction.id).where(Jurisdiction.id!=rows[0]['jurisdiction_id']))
    for table in ('geographic_resolution','geographic_resolution_context'):
        for sql in (f'DELETE FROM {table}',f'UPDATE {table} SET '+('reason=reason' if table=='geographic_resolution' else 'manifest=manifest')):
            with pytest.raises(DBAPIError,match='append-only'),pg.begin() as c:
                c.execute(text(sql))
    first=dict(rows[0])
    for edits in [dict(observation_id=rows[1]['observation_id'],supersedes_id=first['id']),
                  dict(jurisdiction_id=other_jid,supersedes_id=first['id'])]:
        child={**first,'id':uuid4(),**edits}
        with pytest.raises(IntegrityError),pg.begin() as c:
            c.execute(GeographicResolution.__table__.insert().values(child))
    with pg.begin() as c:
        child={**first,'id':uuid4(),'supersedes_id':first['id']}
        c.execute(GeographicResolution.__table__.insert().values(child))
    with pytest.raises(IntegrityError),pg.begin() as c:
        c.execute(GeographicResolution.__table__.insert().values({**child,'id':uuid4()}))


def fingerprint(c, tables):
    q=c.dialect.identifier_preparer.quote
    return {t:c.scalar(text(f"SELECT md5(coalesce(string_agg(h,'' ORDER BY h),'')) FROM "
        f"(SELECT md5(row_to_json(r)::text) h FROM (SELECT {','.join(q(n) for n in cols)} FROM {q(t)}) r) hashes"))
        for t,cols in tables.items()}


def test_upgrade_downgrade_reupgrade_preserves_canonical_and_legacy_rows(pg):
    from test_data003_postgres import _seed,_observe
    from app.services.canonical_results import materialize_medsl_year
    with Session(pg) as s,s.begin():
        seed_data=_seed(s)
        _observe(s,seed_data,2,name='A',votes=100,total=180)
        _observe(s,seed_data,3,name='B',votes=80,total=180)
    with Session(pg) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        result=materialize_medsl_year(s,year=2008,dry_run=False)
        assert result['accepted_rows']==2
    # Remove the new nullable columns before choosing the original row projection.
    with pg.begin() as c,Operations.context(MigrationContext.configure(c)):
        migration(FILES[-1]).downgrade()
    with pg.connect() as c:
        inspector=inspect(c)
        tables={t:[x['name'] for x in inspector.get_columns(t)] for t in inspector.get_table_names()}
        before=fingerprint(c,tables)
    for action in ('upgrade','downgrade','upgrade'):
        with pg.begin() as c,Operations.context(MigrationContext.configure(c)):
            getattr(migration(FILES[-1]),action)()
        with pg.connect() as c:
            assert fingerprint(c,tables)==before


def test_downgrade_refuses_to_discard_new_history(pg):
    with Session(pg) as s,s.begin():
        j,_,_,_,refs=seed(s)
        boundary(s,j,refs[0],'retained',date(2000,1,1),None)
    with pytest.raises(DBAPIError,match='discard recorded history'),pg.begin() as c,Operations.context(MigrationContext.configure(c)):
        migration(FILES[-1]).downgrade()
    with pg.connect() as c:
        assert c.scalar(select(func.count()).select_from(JurisdictionBoundaryVintage))==1


def test_conflicting_supplemental_references_fail_instead_of_picking_first(pg):
    medsl_fixture(pg)
    with Session(pg) as s,s.begin():
        j,_,other,rels,refs=seed(s)
        refs[0].vintage_end=2030
        refs[1].vintage_end=2030
        refs[1].jurisdiction_id=other.id
        refs[1].name_raw='Contradiction'
    with pytest.raises(ValueError,match='Conflicting supplemental'):
        resolve_medsl(pg,vintage=2000,publish=False)


def test_concurrent_overlapping_boundaries_are_rejected(pg):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic,sleep
    with Session(pg) as s,s.begin():
        j,_,_,_,refs=seed(s)
        values=dict(jurisdiction_id=j.id,reference_id=refs[0].id,version_label='first',
            valid_from=date(2000,1,1),valid_until=date(2010,1,1),
            evidence_url='fixture',evidence_note='synthetic concurrent fixture')
    table=JurisdictionBoundaryVintage.__table__
    ready=Event()
    pid=[]
    def compete():
        with pg.begin() as c:
            c.execute(text("SET LOCAL lock_timeout='5s'"))
            pid.append(c.scalar(text('SELECT pg_backend_pid()')))
            ready.set()
            c.execute(table.insert().values(id=uuid4(),**{**values,'version_label':'competing'}))
    with pg.connect() as first:
        transaction=first.begin()
        first.execute(table.insert().values(id=uuid4(),**values))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(compete)
            assert ready.wait(2)
            waiting=False
            deadline=monotonic()+3
            while monotonic()<deadline:
                with pg.connect() as observer:
                    waiting=observer.scalar(text("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"),{'pid':pid[0]})
                if waiting:break
                sleep(.02)
            transaction.commit()
            with pytest.raises(IntegrityError) as error:
                future.result(timeout=6)
            assert error.value.orig.sqlstate=='23P01' and waiting


def test_congressional_reference_quality_uses_its_own_namespace(pg):
    from ingestion.geography.load import stable_jurisdiction_id
    from ingestion.geography.quality import validate_loaded_reference
    with Session(pg) as s,s.begin():
        j,_,_,rels,refs=seed(s,'congressional_district')
        state_id=stable_jurisdiction_id('state','51','')
        s.add(Jurisdiction(id=state_id,name='Virginia',level='state',state_code='VA'));s.flush()
        s.add(JurisdictionIdentifier(jurisdiction_id=j.id,reference_id=refs[0].id,
            scheme='CENSUS_CD_GEOID',value='5101'))
        s.add(JurisdictionRelationship(parent_id=state_id,child_id=j.id,reference_id=refs[0].id))
        release_id=rels[0].id
    report=validate_loaded_reference(pg,release_id)
    assert report['ok'] and report['congressional_district_count']==1
    assert report['county_count']==0


def test_resolution_roots_cross_release_supersession_and_invalid_targets(pg):
    medsl_fixture(pg)
    resolve_medsl(pg,vintage=2000,actor='fixture')
    with pg.connect() as c:
        original=dict(c.execute(select(GeographicResolution.__table__)).mappings().first())
        another=c.scalar(select(SourceRelease.id).where(SourceRelease.id!=original['reference_release_id']))
    new_id=uuid4()
    for edits in [dict(),dict(supersedes_id=original['id'],reference_release_id=another),
                  dict(status='UNRESOLVED',supersedes_id=original['id']),
                  dict(status='NOT_A_STATUS',supersedes_id=original['id']),
                  dict(reference_id=None,supersedes_id=original['id']),dict(supersedes_id=new_id)]:
        with pytest.raises(IntegrityError),pg.begin() as c:
            c.execute(GeographicResolution.__table__.insert().values({**original,'id':new_id,**edits}))


def test_context_detects_modified_observation_inputs(pg):
    medsl_fixture(pg)
    made,_=resolve_medsl(pg,vintage=2000,actor='fixture')
    with pg.begin() as c:
        c.execute(text('UPDATE election_result_observation SET candidate_votes=candidate_votes+1'))
    with pytest.raises(ValueError,match='observation inputs changed'):
        resolve_medsl(pg,vintage=2000,publish=False,context_sha256=made['context_sha256'])
