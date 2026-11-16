"""Verify authorized state corrections and preservation of existing history."""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.database import engine
from app.services.fec_state_results import plan, read_state_totals, summary
from app.services.geo001_audit import all_fingerprints
from ingestion.data005 import digest
from ingestion.fec_authority import SCOPE
from app.models.state_results import StateResultBatch, StateVoteReturn, StateResultPublication
from app.models.core import DataSource
from app.models.ingestion import SourceRelease


APPENDS=('data_source','source_release','election','contest')


def dump(path,obj):
    path.write_text(json.dumps(obj,indent=2,default=str)+'\n',encoding='utf-8')


def preserved_rows(conn,table):
    return {str(r[0]):r[1] for r in conn.execute(text(
        f'SELECT id,md5(row_to_json(r)::text) FROM {table} r'))}


def before(directory):
    with engine.connect() as c,c.begin():
        c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        old=dict(fingerprints=all_fingerprints(c),
                 append_rows={t:preserved_rows(c,t) for t in APPENDS})
    path=directory/'protected-before.json'
    if path.exists():
        raise ValueError('Refusing to replace preservation baseline')
    dump(path,old)
    print(json.dumps({'protected_tables':len(old['fingerprints'])}))


def after(directory,evidence_dir,comparison):
    old=json.loads((directory/'protected-before.json').read_text(encoding='utf-8'))
    with Session(engine) as s,s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        projection=plan(s,evidence_dir)
        authority=read_state_totals(s,year=2008)
        published=s.get(StateResultBatch,__import__('uuid').UUID(authority['batch_id']))
        if published.fingerprint!=projection['fingerprint']:
            raise ValueError('Published state results are stale relative to reviewed inputs')
        current=all_fingerprints(s.connection())
        exact={t:f==current.get(t) for t,f in old['fingerprints'].items() if t not in (*APPENDS,'alembic_version')}
        additions={}
        for table in APPENDS:
            now=preserved_rows(s.connection(),table)
            if any(now.get(key)!=value for key,value in old['append_rows'][table].items()):
                raise ValueError(f'Existing {table} history changed')
            additions[table]=len(set(now)-set(old['append_rows'][table]))
        if not all(exact.values()) or set(current)-set(old['fingerprints'])!={'state_result_batch','state_vote_return','state_result_publication'}:
            raise ValueError('Unexpected changes to unrelated tables')
        if additions!=dict(data_source=1,source_release=1,election=1,contest=1):
            raise ValueError('Unexpected append scope; review every new source/election/contest')
        if s.scalar(text('SELECT version_num FROM alembic_version'))!='d005fec2008a':
            raise ValueError('Unexpected migration revision')
        counts={t:current[t]['rows'] for t in ('state_result_batch','state_vote_return','state_result_publication')}
        if counts!=dict(state_result_batch=1,state_vote_return=153,state_result_publication=1):
            raise ValueError('Unexpected authoritative publication counts')
        fec=s.get(SourceRelease,published.source_release_id)
        if sha256(Path(fec.raw_path).read_bytes()).hexdigest()!=fec.sha256 or fec.sha256!=projection['record']['sha256']:
            raise ValueError('Registered FEC raw archive checksum mismatch')
        expected={(r['state_code'],r['candidate_bucket']):r for r in projection['rows']}
        totals=[]
        for r in authority['results']:
            target=expected[(r['state_code'],r['candidate_bucket'])]
            if r['votes']!=target['votes']:
                raise ValueError('Published authority does not equal FEC')
            totals.append({**r,'fec_votes':target['votes'],'remaining_difference':0,
                'resolution':'FEC_AUTHORITY_ACCEPTED','county_allocation':'UNALLOCATED',
                'source_url':projection['record']['url'],'source_sha256':fec.sha256})
        changes=[r for r in totals if r['source_adjustment']]
        with comparison.open(encoding='utf-8',newline='') as stream:
            original=[r for r in csv.DictReader(stream) if r['scope']=='source' and r['disposition']=='MISMATCH']
        if {(r['state'],r['candidate_bucket'],int(r['expected_votes']),int(r['observed_votes'])) for r in original} != \
                {(r['state_code'],r['candidate_bucket'],r['fec_votes'],r['medsl_source_votes']) for r in changes}:
            raise ValueError('Authority does not resolve exactly the original 45 source discrepancies')
        if len(changes)!=45:
            raise ValueError('Original correction count changed')
        result={**summary(projection), 'batch_id':authority['batch_id'],
            'published_by':published.published_by,'authorization_note':published.authorization_note,
            'source_release_id':str(fec.id),'source_sha256':fec.sha256,
            'old_tables_exact_except_authorized_appends_and_revision':exact,
            'original_append_table_rows_unchanged':True,'expected_appends':additions,
            'new_table_counts':counts,'county_publications_unchanged':exact['canonical_publication'],
            'all_authoritative_values_equal_fec':True}
    for name,rows in [('resolved-45.csv',changes),('authoritative-state-results.csv',totals)]:
        path=directory/name
        with path.open('x',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)
    dump(directory/'resolution-audit.json',result)
    dump(directory/'protected-after.json',dict(fingerprints=current))
    print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['before','after'])
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--evidence-dir',type=Path,default=Path('/app/data/data005/evidence'))
    parser.add_argument('--comparison',type=Path,default=Path('/app/data/data005/final/state-comparisons.csv'))
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.phase=='before':
        before(args.output_dir)
    else:
        after(args.output_dir,args.evidence_dir,args.comparison)


if __name__=='__main__':
    main()
