"""Validate and package county verification; preserve every unrelated backlog row."""
import argparse
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
from xml.etree import ElementTree

from app.services.presidential_returns_package import bundle
from app.services.presidential_returns_reconciliation import write


ROOT=Path(__file__).resolve().parents[3]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def backlog(data,summary,tests):
    path=ROOT/'Election_Data_Project_Backlog.csv'
    original=path.read_bytes()
    bom=b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    body=original[len(bom):].decode('utf-8')
    lines=body.splitlines(keepends=True)
    reader=csv.reader(io.StringIO(body,newline=''))
    fields=next(reader)
    previous=reader.line_num
    found=[]
    for values in reader:
        end=reader.line_num
        if values[0]=='DATA-005':
            found.append((previous,end,dict(zip(fields,values))))
        previous=end
    if len(found)!=1:
        raise ValueError('Expected exactly one DATA-005 backlog row')
    start,end,old=found[0]
    row={**old,'Status':'Partially complete'}
    row['Already done in supplied archive']=(
        '2026-11-15: FEC state precedence remains published and all 45 original state discrepancies resolved '
        '(51 states/DC, 153 buckets, 131,313,820 votes; batch 5fc06d5d-d58e-4ca4-93f5-62ed675b51f8). '
        'Nationwide county verification inventories all 9,474 observations / 3,158 reporting units; '
        'Census/CQ comparison: 9,262 available bucket comparisons, 8,696 exact, 566 differences. '
        'Election-authority comparisons cover 22 states/reporting-unit sets: 4,446 source buckets; '
        '283 supported value proposals (+89,944 votes), including 245 original reference differences; '
        '58 reference differences have incomplete Pennsylvania OTHER grouping; 263 need authority evidence. '
        'All original 144 exclusions have dispositions. Full stored county coverage passes current checks only '
        f'for CA/MD/OK/TX. {tests} current-source offline/PostgreSQL tests pass, no failures/skips; '
        'identical offline replay and all 40 live public table fingerprints preserved. '
        'No county publication attempted; original observations, decisions, five county batches/pointers and '
        'FEC authority preserved. docs/data/county_returns_verification_2008.md; county_returns_verification_2008_runbook.md; '
        'data/data005-county/final/; artifacts/data005-county/.')
    row['Remaining work']=(
        'Obtain comparable election-authority evidence for GA12, IA83, KY26, LA22, MS80, OH40 county/bucket '
        'differences and extend authority checks beyond 22 reviewed state/unit sets (4,753 reference-exact '
        'observations still lack parsed authority evidence). Resolve PA county write-ins: 18,135 FEC votes '
        'unallocated by certified county API; retain alternative precinct-source conflicts. Adjudicate Idaho '
        'Bannock six-vote internal total conflict and Virginia Petersburg/Richmond OTHER differences of 4/13. '
        'Review CT town/county crosswalk historical boundaries; retain HI overseas/Kalawao coverage and '
        'AK District 99/zero-special-unit semantics holds. GEO-002 owns MN alias approval and historical '
        'Jackson/Kansas City coverage before aggregation. Backend/data maintainer must implement reviewed '
        'append-only county source corrections; authorized publisher separately reviews geography/canonical '
        'digests and supersedes/replays. Current canonical preview: 9,336 rows, 138 exclusions, 130,589,107 '
        'votes; supported numeric scenario 130,679,051 votes is not executable publication. Remain PARTIAL.')
    row['Scope evolution']=(
        'Original state-precedence work remains complete. County verification now runs nationwide and '
        'distinguishes election-authority evidence, independent Census/CQ reference, missing evidence, '
        'incompatible candidate groups and internal conflicts. No proportional/state-to-county allocation, '
        'raw OTHER identity inference or eligibility relaxation. Retain 24-hour low-confidence estimate '
        'pending authority response and publication review.')
    row['Main risk']=(
        'Reference agreement and FEC state sums do not prove full county coverage. Keep FEC state authority '
        'separate and non-additive; county values remain immutable/PARTIAL until source corrections, '
        'geography and publication have independent support. Review proposals do not authorize publication.')
    encoded=io.StringIO(newline='')
    csv.writer(encoded,lineterminator='\r\n').writerow([row[f] for f in fields])
    updated=''.join(lines[:start])+encoded.getvalue()+''.join(lines[end:])
    others_before=[r for r in csv.DictReader(io.StringIO(body)) if r['Task ID']!='DATA-005']
    others_after=[r for r in csv.DictReader(io.StringIO(updated)) if r['Task ID']!='DATA-005']
    if others_before!=others_after:
        raise ValueError('Unrelated backlog edit')
    final=bom+updated.encode('utf-8')
    prefix=''.join(lines[:start])
    untouched_original=(prefix+''.join(lines[end:])).encode('utf-8')
    untouched_updated=(updated[:len(prefix)]+updated[len(prefix)+len(encoded.getvalue()):]).encode('utf-8')
    if untouched_original!=untouched_updated:
        raise ValueError('Unrelated physical backlog bytes changed')
    write(data/'backlog-update.json',dict(before=old,after=row,other_rows_preserved=True,
        other_physical_bytes_preserved=True,other_rows_sha256=sha256(untouched_original).hexdigest(),
        original_sha256=sha256(original).hexdigest(),updated_sha256=sha256(final).hexdigest()))
    path.write_bytes(final)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,default=ROOT/'data/data005-county')
    p.add_argument('--output-dir',type=Path,default=ROOT/'artifacts/data005-county')
    args=p.parse_args()
    data=args.data_dir.resolve()
    if args.output_dir.exists():
        raise ValueError('Refusing to replace an existing delivery')
    summary=read(data/'final/summary.json')
    expected={'observation_count':9474,'source_reporting_units':3158,'reference_comparable':9262,
              'reference_exact':8696,'reference_differences':566,'evidenced_value_corrections':283,
              'proposed_vote_adjustment':89944,'authority_missing_discrepancies':263}
    if any(summary.get(k)!=v for k,v in expected.items()):
        raise ValueError('Verification scope changed; review delivery/backlog notes before packaging')
    replay=read(data/'replay/summary.json')
    if {k:v for k,v in summary.items() if k!='generated_at'}!={k:v for k,v in replay.items() if k!='generated_at'}:
        raise ValueError('County verification replay changed')
    for f in (data/'final').iterdir():
        if f.is_file() and f.name!='summary.json' and f.read_bytes()!=(data/'replay'/f.name).read_bytes():
            raise ValueError(f'Offline replay changed: {f.name}')
    preservation=read(data/'live-final/preservation.json')
    if not all(preservation[k] for k in ('all_public_tables_unchanged','same_table_set',
            'source_observations_and_decisions_unchanged','fec_batch_and_pointer_unchanged')):
        raise ValueError('Live preservation failed')
    suites=list(ElementTree.parse(data/'tests-final/pytest.xml').getroot().iter('testsuite'))
    tests={k:sum(int(s.attrib[k]) for s in suites) for k in ('tests','errors','failures','skipped')}
    source=read(data/'tests-final/test-source-hashes.json')
    if tests['tests']<158 or any(tests[k] for k in ('errors','failures','skipped')) or not source['source_unchanged_during_tests']:
        raise ValueError('Current-source full test evidence did not pass')
    for name,expected in source['after'].items():
        if sha256((ROOT/'backend'/name).read_bytes()).hexdigest()!=expected:
            raise ValueError(f'Implementation changed after tests: {name}')
    with (data/'final/original-144-dispositions.csv').open(encoding='utf-8',newline='') as stream:
        ids=[r['observation_id'] for r in csv.DictReader(stream)]
    if len(ids)!=144 or len(set(ids))!=144 or summary['reference_differences']!=566:
        raise ValueError('Incomplete observation accounting')
    write(data/'validation.json',dict(tests=tests,exact_offline_replay=True,
        all_live_tables_preserved=preservation['table_count'],publication_attempted=False,
        correction_sha256=summary['correction_sha256'],original_exclusions=144,
        source_unchanged_after_tests=True,status='PARTIALLY_COMPLETE'))
    backlog(data,summary,tests['tests'])
    source_files=[ROOT/'.gitignore',ROOT/'Election_Data_Project_Backlog.csv',ROOT/'backend/requirements-research.txt']
    source_files += list((ROOT/'backend/app/services').glob('presidential_returns_*.py')) + list((ROOT/'backend/app/services').glob('election_evidence_*.py'))
    source_files += list((ROOT/'backend/app/services').glob('county2008_*.py'))
    source_files += [ROOT/'backend/ingestion/presidential_returns_2008.py',ROOT/'backend/ingestion/county2008.py',
                     ROOT/'backend/tests/test_county2008.py',ROOT/'backend/tests/run_county2008_tests.py']
    source_files += list((ROOT/'docs/data').glob('*2008*'))+list((ROOT/'docs/sources').glob('*2008*'))
    evidence_files=[f for f in data.rglob('*') if f.is_file()]
    evidence_files += [f for f in (ROOT/'data/data005/evidence').rglob('*') if f.is_file()]
    evidence_files += [ROOT/'data/geo001/data005-144-handoff.csv']
    args.output_dir.mkdir(parents=True,exist_ok=False)
    result=dict(task='DATA-005 county verification',status='PARTIALLY_COMPLETE',
        bundles=[bundle(args.output_dir/'DATA-005-county-source.zip',source_files),
                 bundle(args.output_dir/'DATA-005-county-evidence.zip',evidence_files)],
        validation=read(data/'validation.json'))
    write(args.output_dir/'delivery.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
