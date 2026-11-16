"""Publish the user-authorized FEC precedence policy at state TOTAL grain.

Existing MEDSL observations, county batches and geographic decisions are retained.
The 45 source corrections are explicitly unallocated below state level.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database import engine
from app.models.core import DataSource, Jurisdiction, Election, Contest
from app.models.election import CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn, Office
from app.models.ingestion import SourceRelease
from app.models.state_results import StateResultBatch, StateVoteReturn, StateResultPublication
from app.services.canonical_results import _plan
from app.services import elections
from ingestion.presidential_returns_2008 import digest
from ingestion.fec_authority import AUTHORIZATION, RULESET, SCOPE, authority_rows, load_authority
from ingestion.medsl import STATE_NAMES


def plan(session, evidence_dir):
    record, states=load_authority(evidence_dir)
    base=_plan(session,2008,None)
    medsl_archive=Path(base['release'].raw_path)
    if sha256(medsl_archive.read_bytes()).hexdigest()!=base['release'].sha256:
        raise ValueError('MEDSL comparison archive checksum mismatch')
    pointer=session.get(CanonicalPublication,'medsl_presidential_county:2008:county_total')
    if pointer is None:
        raise ValueError('Missing comparison county publication')
    batch=session.get(CanonicalResultBatch,pointer.batch_id)
    # A county amendment must not redefine an existing FEC publication's
    # historical MEDSL comparison or manufacture a new state publication.
    state_pointer=session.get(StateResultPublication,SCOPE)
    if state_pointer:
        authority=session.get(StateResultBatch,state_pointer.batch_id)
        if authority.compared_source_release_id==base['release'].id:
            batch=session.get(CanonicalResultBatch,authority.compared_canonical_batch_id)
    returns=list(session.scalars(select(CanonicalVoteReturn).where(CanonicalVoteReturn.batch_id==batch.id)))
    stored={str(r.observation_id): r.votes for r in returns}
    observations=[dict(observation_id=str(o.id),state=o.state_code,candidate=o.candidate_normalized,
        votes=o.candidate_votes,mode=o.mode_normalized,row_sha256=o.row_sha256) for o in base['observations']]
    observed={r['observation_id']:r for r in observations}
    if len(stored)!=batch.accepted_rows or sum(stored.values())!=batch.canonical_votes \
            or any(key not in observed or observed[key]['votes']!=votes for key,votes in stored.items()):
        raise ValueError('County comparison rows/source lineage disagree')
    rows=authority_rows(observations,stored,states)
    groups=defaultdict(list)
    for j in session.scalars(select(Jurisdiction).where(Jurisdiction.level=='state')):
        groups[j.state_code].append(j)
    if any(len(groups.get(st,[]))!=1 for st in STATE_NAMES):
        raise ValueError('State jurisdictions must each resolve uniquely')
    jurisdictions={st:str(groups[st][0].id) for st in sorted(STATE_NAMES)}
    manifest=dict(format=RULESET,scope=SCOPE,election_year=2008,
        policy='FEC_STATE_TOTALS_OVERRIDE_MEDSL; NO_COUNTY_ALLOCATION; OTHER_IS_AGGREGATE',
        fec_source={k:record[k] for k in ('url','sha256','text_sha256','retrieved_at','extraction')},
        medsl_source=dict(id=str(base['release'].id),sha256=base['release'].sha256,
            input_rows=len(observations),input_sha256=digest(observations)),
        compared_county_batch=dict(id=str(batch.id),fingerprint=batch.fingerprint),
        jurisdictions=jurisdictions,rows=rows)
    return dict(record=record,manifest=manifest,rows=rows,fingerprint=digest(manifest))


def summary(projection):
    rows=projection['rows']
    changes=[r for r in rows if r['source_adjustment']]
    return dict(scope=SCOPE,reporting_level='state',reporting_mode='TOTAL',
        fingerprint=projection['fingerprint'],authoritative_source='FEC',
        states=51,buckets=153,authoritative_votes=sum(r['votes'] for r in rows),
        medsl_source_votes_nonadditive=sum(r['medsl_source_votes'] for r in rows),
        medsl_county_votes=sum(r['medsl_county_votes'] for r in rows),
        resolved_source_discrepancies=len(changes),
        affected_states=sorted({r['state_code'] for r in changes}),
        net_source_adjustment=sum(r['source_adjustment'] for r in rows),
        county_coverage_gap=sum(r['medsl_source_votes']-r['medsl_county_votes'] for r in rows),
        county_allocation='UNALLOCATED',county_reconciliation_complete=False,
        resolution='FEC_PRECEDENCE',remaining_authority_differences=0)


def state_contest(session,st,jurisdiction_id):
    office=elections.office(session,creation_key='us:federal:president',
        name='President of the United States',office_kind='executive')
    existing=list(session.scalars(select(Contest).join(Election,Contest.election_id==Election.id)
        .where(Contest.jurisdiction_id==jurisdiction_id,Contest.office_id==office.id,
            Election.election_type=='general',Election.election_date==date(2008,11,4))))
    if len(existing)>1:
        raise ValueError(f'Ambiguous presidential contest for {st}')
    if existing:
        return existing[0]
    term=elections.office_term(session,creation_key='us:federal:president:term:2009',
        office_id=office.id,start_date=date(2009,1,20),end_date=date(2013,1,20))
    election=elections.election(session,creation_key=f'fec:president:general:2008:{st}',
        election_date=date(2008,11,4),election_type='general',jurisdiction_id=jurisdiction_id,election_cycle=2008)
    return elections.contest(session,creation_key=f'fec:president:contest:2008:{st}',
        office_name='U.S. President',election_id=election.id,jurisdiction_id=jurisdiction_id,
        office_id=office.id,office_term_id=term.id)


def publish(session, evidence_dir, *, expected_fingerprint, actor, archive_dir):
    """Caller owns a REPEATABLE READ transaction and its final commit."""
    if not actor or not actor.strip() or len(actor)>100:
        raise ValueError('A nonblank publishing actor is required')
    if session.scalar(text('SHOW transaction_isolation'))!='repeatable read':
        raise ValueError('FEC publication requires REPEATABLE READ')
    if not session.scalar(text('SELECT pg_try_advisory_xact_lock(hashtext(:scope))'),{'scope':SCOPE}):
        raise ValueError('State publication busy; retry in a fresh transaction')
    projection=plan(session,evidence_dir)
    if expected_fingerprint!=projection['fingerprint']:
        raise ValueError('Stale or changed FEC/source/baseline review fingerprint')
    report=summary(projection)
    pointer=session.get(StateResultPublication,SCOPE)
    if pointer:
        current=session.get(StateResultBatch,pointer.batch_id)
        if current.fingerprint==projection['fingerprint']:
            actual=read_state_totals(session,year=2008)
            if [(r['state_code'],r['candidate_bucket'],r['votes']) for r in actual['results']] != \
                    [(r['state_code'],r['candidate_bucket'],r['votes']) for r in sorted(projection['rows'],key=lambda r:(r['state_code'],r['candidate_bucket']))]:
                raise ValueError('Stored authority batch differs from reviewed FEC results')
            return {**report,'action':'UNCHANGED','batch_id':str(current.id),'published_by':current.published_by}
    prior=session.scalar(select(StateResultBatch).where(StateResultBatch.scope_key==SCOPE,
        StateResultBatch.fingerprint==projection['fingerprint']))
    if prior is not None:
        raise ValueError('Historical authority batch exists; explicit reactivation review required')
    record=projection['record']
    archive_dir.mkdir(parents=True,exist_ok=True)
    archive=archive_dir/(record['sha256']+'.pdf')
    original=(evidence_dir/record['file']).read_bytes()
    if archive.exists():
        if sha256(archive.read_bytes()).hexdigest()!=record['sha256']:
            raise ValueError('Archived FEC release was modified')
    else:
        with archive.open('xb') as stream:
            stream.write(original)
    source=session.scalar(select(DataSource).where(DataSource.name=='fec_presidential_official'))
    if source is None:
        source=DataSource(name='fec_presidential_official',url=record['url'])
        session.add(source);session.flush()
    release=session.scalar(select(SourceRelease).where(SourceRelease.source_id==source.id,
        SourceRelease.version=='2008-summary',SourceRelease.sha256==record['sha256']))
    if release is None:
        release=SourceRelease(source_id=source.id,version='2008-summary',sha256=record['sha256'],
            filename='2008pres.pdf',file_id=1660,download_url=record['url'],raw_path=str(archive),
            retrieved_at=datetime.fromisoformat(record['retrieved_at']),
            metadata_json=dict(resource_id_namespace='fec.gov document',license='US federal government publication',
                extraction_sha256=record['text_sha256'],authority='FEC',reporting_level='state'))
        session.add(release);session.flush()
    from uuid import UUID
    manifest=projection['manifest']
    batch=StateResultBatch(id=uuid4(),scope_key=SCOPE,fingerprint=projection['fingerprint'],
        ruleset_version=RULESET,election_year=2008,source_release_id=release.id,
        compared_source_release_id=UUID(manifest['medsl_source']['id']),
        compared_canonical_batch_id=UUID(manifest['compared_county_batch']['id']),
        published_by=actor.strip(),authorization_note=AUTHORIZATION,manifest_json=manifest,
        supersedes_id=pointer.batch_id if pointer else None)
    session.add(batch);session.flush()
    for st in sorted(STATE_NAMES):
        jurisdiction_id=UUID(manifest['jurisdictions'][st])
        contest=state_contest(session,st,jurisdiction_id)
        for row in projection['rows']:
            if row['state_code']==st:
                session.add(StateVoteReturn(batch_id=batch.id,jurisdiction_id=jurisdiction_id,
                    contest_id=contest.id,**row))
    session.flush()
    session.execute(pg_insert(StateResultPublication).values(scope_key=SCOPE,batch_id=batch.id)
        .on_conflict_do_update(index_elements=['scope_key'],set_={'batch_id':batch.id,'published_at':datetime.now(timezone.utc)}))
    session.expire_all()  # A superseding pointer must replace any cached ORM head.
    actual=read_state_totals(session,year=2008)
    if sum(r['votes'] for r in actual['results'])!=report['authoritative_votes']:
        raise ValueError('Persisted state authority totals differ')
    return {**report,'action':'CREATED','batch_id':str(batch.id),'published_by':batch.published_by}


def read_state_totals(session, *, year, state_code=None):
    """Authoritative state accessor; never adds state totals to county returns."""
    if year!=2008:
        raise ValueError('FEC-authoritative state publication is currently scoped to 2008')
    if state_code is not None and state_code not in STATE_NAMES:
        raise ValueError('Unknown state code')
    pointer=session.get(StateResultPublication,SCOPE)
    if pointer is None:
        raise ValueError('No published authoritative state totals')
    batch=session.get(StateResultBatch,pointer.batch_id)
    query=select(StateVoteReturn).where(StateVoteReturn.batch_id==batch.id)
    rows=list(session.scalars(query.order_by(StateVoteReturn.state_code,StateVoteReturn.candidate_bucket)))
    if len(rows)!=153 or digest(batch.manifest_json)!=batch.fingerprint:
        raise ValueError('Incomplete published state authority batch')
    expected=sorted(batch.manifest_json['rows'],key=lambda r:(r['state_code'],r['candidate_bucket']))
    for row,original in zip(rows,expected):
        if any(getattr(row,k)!=v for k,v in original.items()) or \
                str(row.jurisdiction_id)!=batch.manifest_json['jurisdictions'][row.state_code]:
            raise ValueError('Published state returns differ from their immutable source manifest')
    if state_code:
        rows=[r for r in rows if r.state_code==state_code]
    return dict(year=year,scope=SCOPE,batch_id=str(batch.id),source='FEC',source_release_id=str(batch.source_release_id),
        reporting_level='state',reporting_mode='TOTAL',additive_with_county_returns=False,
        county_coverage_verified=False,results=[dict(state_code=r.state_code,candidate_bucket=r.candidate_bucket,
            votes=r.votes,medsl_source_votes=r.medsl_source_votes,medsl_county_votes=r.medsl_county_votes,
            source_adjustment=r.source_adjustment,source_locator=r.source_locator) for r in rows])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--expected-fingerprint')
    parser.add_argument('--actor')
    parser.add_argument('--archive-dir',type=Path,default=Path('data/ingestion/raw/fec_presidential_official/2008'))
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Choose an unused report path')
    if args.publish and (not args.actor or not args.expected_fingerprint):
        parser.error('Publication requires --actor and --expected-fingerprint')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with Session(engine) as session,session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'+('' if args.publish else ' READ ONLY')))
        if args.publish:
            report=publish(session,args.evidence_dir,expected_fingerprint=args.expected_fingerprint,
                actor=args.actor,archive_dir=args.archive_dir)
            report['authoritative_results']=read_state_totals(session,year=2008)
        else:
            projection=plan(session,args.evidence_dir)
            report={**summary(projection),'action':'PREVIEW_ONLY','manifest':projection['manifest']}
    args.output.write_text(json.dumps(report,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('manifest','authoritative_results')},indent=2))


if __name__=='__main__':
    main()
