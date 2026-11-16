"""Preview, publish, replay and audit the authorized DATA-005 county corrections."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from app.database import engine
from app.models.election import CanonicalResultBatch,CanonicalVoteReturn,CanonicalPublication
from app.services.county_corrections import SCOPE,prepare,publish
from app.services.geo001_audit import all_fingerprints
from app.services.fec_state_results import read_state_totals
from ingestion.county_corrections import load_review
from ingestion.presidential_returns_2008 import digest

APPENDS=('data_source','source_release','canonical_result_batch','canonical_vote_return','canonical_materialization_issue')


def write(path,obj):
    with path.open('x',encoding='utf-8') as f:
        json.dump(obj,f,indent=2,default=str,ensure_ascii=False);f.write('\n')


def row_hashes(c,table,columns):
    q=c.dialect.identifier_preparer.quote
    return {str(json.loads(r[0])['id']):sha256(r[0].encode()).hexdigest() for r in c.execute(text(
        f'SELECT row_to_json(r)::text FROM (SELECT {",".join(q(x) for x in columns)} FROM {q(table)}) r'))}


def baseline(directory):
    with engine.connect() as c,c.begin():
        c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        fp=all_fingerprints(c)
        result=dict(fingerprints=fp,append_rows={t:row_hashes(c,t,fp[t]['columns']) for t in APPENDS},
                    publications=[dict(r) for r in c.execute(text('SELECT * FROM canonical_publication ORDER BY scope_key')).mappings()])
    write(directory/'protected-before.json',result)
    return dict(tables=len(fp),action='BASELINE')


def audit(session,directory,review):
    from app.services.canonical_results import _plan,materialize_medsl_year
    old=json.loads((directory/'protected-before.json').read_text(encoding='utf-8'))
    snapshot=json.loads((directory/'snapshot-before.json').read_text(encoding='utf-8'))
    c=session.connection();fp=all_fingerprints(c)
    pointer=session.get(CanonicalPublication,SCOPE)
    batch=session.get(CanonicalResultBatch,pointer.batch_id)
    rows=list(session.scalars(select(CanonicalVoteReturn).where(CanonicalVoteReturn.batch_id==batch.id)))
    actual={str(r.observation_id):r for r in rows}
    previous={r['observation_id']:r for r in snapshot['observations'] if r['stored_accepted']}
    changes={r['observation_id']:r for r in review['changes']}
    if not set(previous)<=set(actual):raise ValueError('Previous county observations removed')
    changed={k for k,r in actual.items() if k in previous and r.votes!=previous[k]['stored_votes']}
    if changed!=set(changes):raise ValueError('Published value changes differ from exactly the reviewed 283')
    if any(actual[k].votes!=v['proposed_votes'] or actual[k].correction_id is None for k,v in changes.items()):
        raise ValueError('Correction votes/lineage differ')
    added=[r for k,r in actual.items() if k not in previous]
    if len(added)!=6 or sum(r.votes for r in added)!=42756:
        raise ValueError('Unexpected current-geography additions')
    if (len(rows),sum(r.votes for r in rows),batch.excluded_rows,batch.status)!=(9336,130679051,138,'PARTIAL'):
        raise ValueError('Canonical accounting differs')
    preserved={}
    for table,meta in old['fingerprints'].items():
        if table in APPENDS:
            current=row_hashes(c,table,meta['columns'])
            preserved[table]=all(current.get(k)==v for k,v in old['append_rows'][table].items())
        elif table not in ('alembic_version','canonical_publication'):
            preserved[table]=fp[table]==meta
    if not all(preserved.values()):raise ValueError(f'Historical/unrelated data changed: {[k for k,v in preserved.items() if not v]}')
    expected_additions=dict(data_source=1,source_release=1,canonical_result_batch=1,canonical_vote_return=9336,canonical_materialization_issue=138)
    if any(fp[t]['rows']-old['fingerprints'][t]['rows']!=n for t,n in expected_additions.items()):
        raise ValueError('Unexpected appended rows')
    pub=[dict(r) for r in c.execute(text('SELECT * FROM canonical_publication ORDER BY scope_key')).mappings()]
    def normalize(rows):return json.loads(json.dumps([r for r in rows if r['scope_key']!=SCOPE],default=str))
    if normalize(pub)!=normalize(old['publications']):raise ValueError('Unrelated year pointers changed')
    if set(fp)!=set(old['fingerprints'])|{'county_correction_batch','county_vote_correction'}:
        raise ValueError('Unexpected schema/table set')
    if fp['county_correction_batch']['rows']!=1 or fp['county_vote_correction']['rows']!=283:
        raise ValueError('Unexpected correction history count')
    for table,col in (('canonical_result_batch','correction_batch_id'),('canonical_vote_return','correction_id')):
        clause='id' if table=='canonical_result_batch' else 'batch_id'
        if session.scalar(text(f'SELECT count(*) FROM {table} WHERE {col} IS NOT NULL AND {clause}<>:batch'),{'batch':batch.id}):
            raise ValueError('Correction lineage added to historical batches')
    planned=_plan(session,2008,None)
    if planned['fingerprint']!=batch.fingerprint or planned['target_sum']!=batch.canonical_votes:
        raise ValueError('Default planner lost the active corrections')
    state=read_state_totals(session,year=2008)
    if sum(r['votes'] for r in state['results'])!=131313820:raise ValueError('FEC state authority changed')
    issue_ids=set(session.scalars(text('SELECT observation_id::text FROM canonical_materialization_issue WHERE batch_id=:b'),{'b':batch.id}))
    if issue_ids!={r['observation_id'] for r in snapshot['observations']} - set(actual):
        raise ValueError('Excluded observations differ')
    return dict(action='VERIFIED',status='PARTIAL',batch_id=str(batch.id),fingerprint=batch.fingerprint,
        correction_batch_id=str(batch.correction_batch_id),corrected_observations=len(changed),vote_adjustment=89944,
        geography_added_rows=6,geography_added_votes=42756,
        existing_geographic_lineage_changes=sum(str(actual[k].geographic_resolution_id)!=v['stored_resolution_id'] for k,v in previous.items()),
        accepted_rows=len(rows),excluded_rows=138,canonical_votes=batch.canonical_votes,
        historical_and_unrelated_tables_preserved=preserved,all_historical_rows_preserved=True,
        unrelated_year_pointers_preserved=True,appended_rows=expected_additions,
        fec_batch_id=state['batch_id'],fec_votes=131313820,alembic_revision=session.scalar(text('SELECT version_num FROM alembic_version')),
        rejected_observation_ids=sorted(issue_ids),review_sha256=review['review_sha256'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['before','preview','publish','verify'])
    p.add_argument('--root',type=Path,default=Path('/workspace'))
    p.add_argument('--review-dir',type=Path,default=Path('/workspace/data/data005-county/final'))
    p.add_argument('--directory',type=Path,default=Path('/app/data/data005-county-apply'))
    p.add_argument('--output',type=Path)
    p.add_argument('--expected-fingerprint')
    p.add_argument('--actor')
    args=p.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    if args.phase=='before':result=baseline(args.directory)
    else:
        review=load_review(args.review_dir,args.root)
        with Session(engine) as s,s.begin():
            s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'+(' READ ONLY' if args.phase in ('preview','verify') else '')))
            if args.phase=='preview':result=prepare(s,review)
            elif args.phase=='verify':result=audit(s,args.directory,review)
            else:result=publish(s,review,expected_fingerprint=args.expected_fingerprint,actor=args.actor,
                archive_dir=Path('/app/data/ingestion/raw/official_presidential_county_corrections/2008'),root=args.root)
        if args.output:write(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='manifest'},indent=2,default=str))


if __name__=='__main__':main()
