"""Archive five read-only comparisons and triage the original DATA-004 exceptions.

Run after the migration with --baseline /app/data/data004/before.json.
No geography decisions, alias approvals or canonical publications are written.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from uuid import UUID

import polars as pl
from sqlalchemy import select, text

from app.database import engine
from app.models.election import CanonicalVoteReturn, CanonicalPublication
from ingestion.geography.reconcile import VINTAGES, combine_reports
from ingestion.geography.resolve import resolve_medsl

CENSUS_CODES = 'https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt'
CENSUS_CHANGES = 'https://www.census.gov/programs-surveys/geography/technical-documentation/county-changes.2010.html'
CT_CHANGE = 'https://www.federalregister.gov/documents/2022/06/06/2022-12063/change-to-county-equivalents-in-the-state-of-connecticut'
AK_RESULTS = 'https://www.elections.alaska.gov/results/08GENR/data/results.htm'


def disposition(row):
    state,label,code = row['state_code'],row['county_raw'] or '',row['county_fips']
    if state == 'AK':
        return ('GEO-001;GEO-002', 'RESEARCH_SPECIAL_UNIT' if label.endswith('99') else 'CLASSIFY_NON_COUNTY',
                AK_RESULTS, 'District 1-40 classification supported; never assign a borough/census area. District 99 needs year-specific evidence.')
    if state == 'CT' and code:
        return ('GEO-001;GEO-002','VERIFY_LEGACY_REPORTING',CT_CHANGE,
                'Legacy counties and planning regions differ. Verify source reporting scope; no allocation to new regions.')
    if state == 'SD':
        return ('GEO-001;GEO-002','REVIEW_DATED_CODE_CHANGE',CENSUS_CHANGES,
                '2016 uses new 46102; 2024 still uses retired 46113. Verify source convention; no automatic remap.')
    if state in {'DC','FL'}:
        return ('GEO-001;GEO-002','REVIEW_2000_SUPPLEMENT',
                'https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2000.html',
                'Exact Census 2000 county evidence already loaded; selected CBP product lacks these two county equivalents.')
    if state == 'MO' and row['status'] == 'INVALID':
        return ('GEO-001;GEO-002;DATA-028','RESEARCH_INVALID_SOURCE_CODE','',
                'Kansas City source 36000 conflicts with Missouri 29. Do not substitute a place/county code.')
    if state in {'CT','ME','RI'} or (state=='MO' and label=='KANSAS CITY'):
        return ('GEO-001;GEO-002' + (';DATA-005' if row['year']==2008 else ''),
                'CLASSIFY_NON_COUNTY','',
                'Source-specific reporting category; classification cannot allocate votes to counties. Verify completeness separately.')
    if state=='VA':
        return ('GEO-001;GEO-002' + (';DATA-005' if row['year']==2008 else ''),
                'REVIEW_EXACT_COUNTY_LABEL',CENSUS_CODES,
                '51036 Charles City County and 51095 James City County retain CITY in their names; existing normalization defect.')
    if state=='NM':
        return ('GEO-001;GEO-002','RESEARCH_REFERENCE_ENCODING',CENSUS_CODES,
                'Loaded 2017-2021 reference has a replacement character; 2022-2024 has Do a Ana. Verify original bytes/decoder and identity continuity. Preserve released records; do not repair names in place.')
    return ('GEO-001;GEO-002','REVIEW_SOURCE_SCOPED_ALIAS',
            CENSUS_CHANGES if state=='LA' else CENSUS_CODES,
            'Exact state/code supplies a review candidate. Spelling, spacing or abbreviation is not approval. Verify election-year evidence before approving an alias.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    baseline=json.loads(args.baseline.read_text(encoding='utf-8'))
    args.output_dir.mkdir(parents=True,exist_ok=True)
    reports=[]
    review_rows=[]
    for vintage in VINTAGES:
        report,review=resolve_medsl(engine,vintage=vintage,publish=False)
        reports.append(report)
        review_rows.extend(review)
        (args.output_dir/f'compare-{vintage}.json').write_text(
            json.dumps(report,indent=2,default=str)+'\n',encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('vintage','records_examined','status_counts',
            'changed_decisions','resolved_match_downgrades','canonical_reassignments','context_sha256')}))
    combined=combine_reports(reports,expected_observations=baseline['fingerprints']['election_result_observation']['rows'])
    downgraded=[UUID(x['observation_id']) for x in combined['resolved_match_downgrade_details']]
    with engine.connect() as conn,conn.begin():
        conn.execute(text('SET TRANSACTION READ ONLY'))
        c,p=CanonicalVoteReturn,CanonicalPublication
        combined['downgrade_canonical_impact']=[dict(x) for x in conn.execute(select(
            c.observation_id,c.batch_id,c.votes,c.source_label,c.geographic_resolution_id)
            .join(p,p.batch_id==c.batch_id).where(c.observation_id.in_(downgraded))).mappings()]
    combined['input_contexts']=[{'file':f"compare-{r['vintage']}.json",'sha256':r['context_sha256']} for r in reports]
    (args.output_dir/'reconciliation.json').write_text(json.dumps(combined,indent=2,default=str)+'\n',encoding='utf-8')
    diffs={x['observation_id']:x for x in combined['all_decision_changes']}
    triage=[]
    for row in baseline['exceptions']:
        diff=diffs.get(row['observation_id'],{})
        owner,action,url,note=disposition(row)
        if row['year']==2008 and 'DATA-005' not in owner:
            owner+=';DATA-005'
        triage.append({k:row[k] for k in ('observation_id','year','state_code','county_raw',
            'county_fips_raw','county_fips','status','method','reason','reference_release_id')})
        triage[-1].update(preview_status=diff.get('proposed_status',row['status']),
            preview_method=diff.get('proposed_method',row['method']),owner=owner,action=action,
            evidence_url=url,note=note)
    frame=pl.DataFrame(triage,infer_schema_length=None)
    frame.write_csv(args.output_dir/'exception_triage.csv')
    groups=frame.group_by(['year','state_code','county_raw','county_fips','status','method',
                          'preview_status','preview_method','owner','action','evidence_url','note']).agg(pl.len().alias('observations'))
    groups.sort(['year','state_code','county_raw']).write_csv(args.output_dir/'exception_groups.csv')
    if review_rows:
        pl.DataFrame(review_rows,infer_schema_length=None).write_csv(args.output_dir/'preview_review.csv')
    summary={'original_exception_rows':len(triage),
        'original_exception_preview_statuses':dict(Counter(x['preview_status'] for x in triage)),
        'original_exception_actions':dict(Counter(x['action'] for x in triage)),
        'published_statuses_unchanged':baseline['resolution_counts'],
        'preview_statuses':combined['status_counts'],
        'preview_review_required':combined['review_required'],
        'preview_downgrades':combined['resolved_match_downgrades'],
        'preview_reassignments':combined['canonical_reassignments'],
        'publication_permitted':False}
    (args.output_dir/'triage_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
