"""Validate the delivery, update only DATA-005, and bundle reviewable evidence.

Host-only, no database access. Refuses to replace an existing delivery directory.
"""
from __future__ import annotations

import csv
from hashlib import sha256
import io
import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'data/data005'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def file_sha(path):
    h = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def backlog(summary):
    path = ROOT / 'Election_Data_Project_Backlog.csv'
    original_bytes = path.read_bytes()
    bom = b'\xef\xbb\xbf' if original_bytes.startswith(b'\xef\xbb\xbf') else b''
    body = original_bytes.decode('utf-8-sig')
    physical = body.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(body, newline=''))
    fields = next(reader)
    records, position = [], None
    while True:
        start = reader.line_num
        try:
            values = next(reader)
        except StopIteration:
            break
        row = dict(zip(fields, values))
        records.append(row)
        if row['Task ID'] == 'DATA-005':
            if position is not None:
                raise ValueError('Duplicate DATA-005 rows')
            position = (start, reader.line_num, row)
    if position is None:
        raise ValueError('DATA-005 missing from backlog')
    start, end, old = position
    updated = dict(old)
    updated.update({
        'Status': 'Partially complete', 'Remaining engineering hours': '24', 'Estimate confidence': 'Low',
        'Completed/available evidence': (
            '2026-11-14 independently verified MEDSL V20.0/9,474 observations and original PARTIAL batch '
            'f44e7295-900f-47ec-9947-97d4c7c74ded (9,330 accepted/144 excluded; 130,546,351 votes). '
            'Live geography advanced: 255 2008 successors exactly match GEO-002 manifests, predecessor/payload/context/digest and actor glarsen; '
            'current preview 9,336/138 and 130,589,107 votes. FEC 51-state/DC comparison: 31 all-bucket exact, 45 discrepancies in 20 states. '
            'Official unit comparisons: AK 40 districts, MO 116 authority/county units, MN 87 counties all source-bucket exact; '
            'VA 134 localities has two OTHER differences totaling 17 versus historical export. MN manual/export 33 named write-ins explained. '
            'All original 144 observation dispositions delivered; 132 PostgreSQL/full-suite tests passed, zero skips; schema current/check passed; '
            'all 37 live table fingerprints and five stored canonical publications preserved. '
            'docs/data/presidential_returns_2008.md; presidential_returns_2008_runbook.md; data/data005/final/; artifacts/data005/. No canonical publication attempted.'),
        'Remaining work': (
            'Resolve/adjudicate 45 source/FEC bucket discrepancies in 20 states and Virginia official-export conflict; '
            'extend independent county coverage nationwide; retain unknown AK District 99 and zero-vote special-unit semantics; '
            'GEO-002 owns reviewed MN alias/geographic publication. Establish historical Jackson/Kansas City segment coverage before county aggregation. '
            'Obtain separate explicit canonical approval for the concrete partial supersession (six VA additions/42,756 votes; 117 lineage-only changes), '
            'then verify append-only live publication, invariants and UNCHANGED replay. Do not mark Done while reconciliation/coverage acceptance fails.'),
        'Scope evolution': (
            'Original end-to-end requirement retained. Independent evidence exposes source discrepancies beyond geographic exclusions; '
            '24 remaining hours is a provisional low-confidence re-estimate, not a completion guarantee. '
            'GEO-002 recorded approval preparation is stale relative to live published history; canonical authorization remains separate.'),
        'Main risk': (
            'Numerically exact state or reporting-segment sums do not prove complete county coverage. '
            'Current and proposed canonical batches remain PARTIAL; no silent source corrections, alias approvals, non-county allocation or national-total claims.')})
    encoded = io.StringIO(newline='')
    csv.writer(encoded, lineterminator='\r\n').writerow([updated[k] for k in fields])
    after = ''.join(physical[:start]) + encoded.getvalue() + ''.join(physical[end:])
    parsed = list(csv.DictReader(io.StringIO(after)))
    if [r for r in parsed if r['Task ID'] != 'DATA-005'] != [r for r in records if r['Task ID'] != 'DATA-005']:
        raise ValueError('Unexpected unrelated backlog edit')
    after_bytes = bom + after.encode('utf-8')
    write(DATA / 'backlog-update.json', dict(before=old, after=updated,
        original_file_sha256=sha256(original_bytes).hexdigest(),
        resulting_file_sha256=sha256(after_bytes).hexdigest(), other_rows_preserved=True))
    path.write_bytes(after_bytes)


def bundle(path, files):
    hashes = {}
    with ZipFile(path, 'x', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(set(files)):
            name = file.relative_to(ROOT).as_posix()
            hashes[name] = file_sha(file)
            archive.write(file, name)
        archive.writestr('SHA256SUMS.json', json.dumps(hashes, indent=2)+'\n')
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP integrity failure')
        for name, digest in hashes.items():
            if sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError('ZIP evidence hash differs')
    return dict(file=path.name, sha256=file_sha(path), files=len(hashes), bytes=path.stat().st_size)


def main():
    output = ROOT / 'artifacts/data005'
    if output.exists():
        raise ValueError('Refusing to replace an existing DATA-005 delivery')
    before, after = read(DATA/'snapshot.json'), read(DATA/'snapshot-after.json')
    preservation = read(DATA/'full-preservation.json')
    summary = read(DATA/'final/summary.json')
    schema = {k: read(DATA/f'schema-{k}.json') for k in ('current','check')}
    suites = list(ElementTree.parse(DATA/'tests/pytest.xml').getroot().iter('testsuite'))
    tests = {k: sum(int(s.attrib[k]) for s in suites) for k in ('tests','errors','failures','skipped')}
    if tests['tests'] < 132 or any(tests[k] for k in ('errors','failures','skipped')):
        raise ValueError('Full PostgreSQL test evidence did not pass')
    if before['fingerprints'] != after['fingerprints'] or not preservation['all_tables_unchanged']:
        raise ValueError('Live database preservation failed')
    if any(v['exit_code'] for v in schema.values()):
        raise ValueError('Schema verification failed')
    envelope = read(DATA/'final/canonical-publication-review.json')
    digest = sha256(json.dumps(envelope['review'],sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    if digest != envelope['review_sha256'] or digest != summary['canonical_publication_review_sha256']:
        raise ValueError('Canonical review envelope changed')
    with (DATA/'final/original-144-dispositions.csv').open(encoding='utf-8',newline='') as stream:
        ids=[r['observation_id'] for r in csv.DictReader(stream)]
    if len(ids)!=144 or len(set(ids))!=144:
        raise ValueError('Incomplete original exclusion ledger')
    write(DATA/'validation.json', dict(tests=tests, schema_passed=True,
        unchanged_public_tables=len(before['fingerprints']),
        canonical_batches_and_pointers_unchanged=before['stored_batch']==after['stored_batch'],
        original_exclusions=144, review_sha256=digest,
        status='PARTIALLY_COMPLETE', publication_attempted=False))
    backlog(summary)
    output.mkdir(parents=True, exist_ok=False)
    source = [ROOT/'.gitignore', ROOT/'Election_Data_Project_Backlog.csv',
              ROOT/'backend/requirements-research.txt']
    source += list((ROOT/'backend/app/services').glob('presidential_returns_*.py')) + list((ROOT/'backend/app/services').glob('election_evidence_*.py'))
    source += [ROOT/'backend/ingestion/presidential_returns_2008.py']
    source += list((ROOT/'backend/tests').glob('test_presidential_returns_*.py'))
    source += list((ROOT/'docs/data').glob('*2008*'))
    source += list((ROOT/'docs/sources').glob('*2008*'))
    evidence_files = [p for p in DATA.rglob('*') if p.is_file()]
    evidence_files += [ROOT/'data/geo001/data005-144-handoff.csv', ROOT/'data/geo002/approval-manifest.json']
    evidence_files += list((ROOT/'data/geo002/approvals').glob('*.json'))
    result = dict(task='DATA-005', status='PARTIALLY_COMPLETE',
        bundles=[bundle(output/'DATA-005-source.zip',source),
                 bundle(output/'DATA-005-evidence.zip',evidence_files)],
        validation=read(DATA/'validation.json'))
    write(output/'delivery.json',result)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
