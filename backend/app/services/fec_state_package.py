"""Package the verified FEC authority follow-up; update only DATA-005's row."""
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
from xml.etree import ElementTree

from app.services.data005_package import bundle
from ingestion.data005 import digest

ROOT=Path(__file__).resolve().parents[3]
DATA=ROOT/'data/data005-fec'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path,obj):
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def update_backlog(audit,tests):
    path=ROOT/'Election_Data_Project_Backlog.csv'
    original=path.read_bytes()
    prefix=b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    text=original.decode('utf-8-sig')
    lines=text.splitlines(keepends=True)
    reader=csv.reader(io.StringIO(text,newline=''))
    fields=next(reader)
    old_rows=[]; target=None
    while True:
        start=reader.line_num
        try:
            values=next(reader)
        except StopIteration:
            break
        row=dict(zip(fields,values));old_rows.append(row)
        if row['Task ID']=='DATA-005':
            if target is not None:
                raise ValueError('Duplicate DATA-005 backlog row')
            target=(start,reader.line_num,row)
    if target is None:
        raise ValueError('DATA-005 missing')
    start,end,old=target
    row={**old,'Status':'Partially complete',
        'Completed/available evidence':(
            '2026-11-15 user-authorized FEC source precedence applied live: all 45 original state/candidate discrepancies '
            'in 20 states RESOLVED_BY_FEC_PRECEDENCE. Published 51-state/DC, 153-bucket authority batch '
            '5fc06d5d-d58e-4ca4-93f5-62ed675b51f8 (131,313,820 votes), fingerprint '
            '1a9acd697b7def975dc0bffd11bf1462d8b8529ebc8624e8559301796da1f062; all authoritative values equal FEC; '
            'net source correction +126,483, separately identified 640,986 excluded MEDSL votes. '
            'Source release 8778d3b2-1942-4452-b6a6-c4c5f0e4ee4a; original FEC PDF checksum verified; '
            'publisher codex and exact user instruction persisted. Additive migration d005fec2008a/current/check passed; '
            f'{tests} full PostgreSQL tests passed, zero failures/skips; live replay UNCHANGED. '
            'Original MEDSL observations/geographic decisions and all five county publications preserved; '
            '32 old tables exact, protected original rows in four appended catalog/event tables exact. '
            'Original 144 dispositions, AK40/MO116/MN87/VA134 independent unit checks retained. '
            'docs/data/DATA005-FEC.md; data/data005-fec/resolved-45.csv; resolution-audit.json; artifacts/data005-fec/.'),
        'Remaining work':(
            'State-level source precedence and all 45 original discrepancies are resolved. '
            'Extend independent county verification nationwide; locate/adjudicate state corrections below state level using county evidence, '
            'keeping all signed differences explicitly unallocated until supported. Retain AK District 99 and zero-vote special-unit semantics holds; '
            'GEO-002 owns reviewed MN alias/geographic publication. Establish historical Jackson/Kansas City coverage before county aggregation. '
            'FEC wins the Virginia whole-state source conflict; county detail remains a separate comparison. '
            'Review/authorize any county canonical supersession (existing six VA additions/42,756 votes and 117 lineage changes), '
            'then verify its append-only publication and idempotence. DATA-005 remains Partially complete until county/coverage acceptance passes.'),
        'Scope evolution':(
            'Explicit user instruction makes FEC authoritative for 2008 state TOTAL results. '
            'All 45 source discrepancies are closed at their evidenced reporting level; original MEDSL values remain immutable comparison evidence. '
            'Added state-grain canonical publication reuses existing sources, jurisdictions, offices and contests; no county allocation inferred. '
            'Prior 24-hour low-confidence remaining estimate is retained pending county-evidence re-estimation.'),
        'Main risk':(
            'State authority must not be added to county returns or mistaken for verified county completeness. '
            'Use canonical_results.state_totals for FEC-backed state values. County batches remain PARTIAL; '
            'source corrections are signed state-only audit values, not fabricated county returns.')}
    out=io.StringIO(newline='')
    csv.writer(out,lineterminator='\r\n').writerow([row[f] for f in fields])
    updated=''.join(lines[:start])+out.getvalue()+''.join(lines[end:])
    new_rows=list(csv.DictReader(io.StringIO(updated)))
    if [r for r in old_rows if r['Task ID']!='DATA-005'] != [r for r in new_rows if r['Task ID']!='DATA-005']:
        raise ValueError('Unexpected unrelated backlog changes')
    final=prefix+updated.encode('utf-8')
    write(DATA/'backlog-update.json',dict(before=old,after=row,other_rows_preserved=True,
        original_sha256=sha256(original).hexdigest(),updated_sha256=sha256(final).hexdigest()))
    path.write_bytes(final)


def main():
    output=ROOT/'artifacts/data005-fec'
    if output.exists():
        raise ValueError('Refusing to overwrite the FEC follow-up delivery')
    audit=read(DATA/'resolution-audit.json')
    made,replay=read(DATA/'publication.json'),read(DATA/'replay.json')
    if made['action']!='CREATED' or replay['action']!='UNCHANGED' or made['batch_id']!=replay['batch_id']:
        raise ValueError('Missing successful live publication and exact replay')
    if audit['resolved_source_discrepancies']!=45 or not audit['all_authoritative_values_equal_fec'] \
            or not audit['county_publications_unchanged'] or not audit['original_append_table_rows_unchanged'] \
            or not all(audit['old_tables_exact_except_authorized_appends_and_revision'].values()):
        raise ValueError('Authority/preservation acceptance failed')
    preview=read(DATA/'preview.json')
    if digest(preview['manifest'])!=made['fingerprint'] or made['fingerprint']!=audit['fingerprint']:
        raise ValueError('Reviewed/published fingerprints differ')
    for phase in ('current','check'):
        if read(DATA/f'schema-{phase}.json')['exit_code']:
            raise ValueError('Schema check failed')
    suites=list(ElementTree.parse(DATA/'tests-final/pytest.xml').getroot().iter('testsuite'))
    totals={k:sum(int(s.attrib[k]) for s in suites) for k in ('tests','failures','errors','skipped')}
    if totals['tests']<138 or any(totals[k] for k in ('failures','errors','skipped')):
        raise ValueError('Final full-suite test evidence missing')
    update_backlog(audit,totals['tests'])
    output.mkdir(parents=True,exist_ok=False)
    files=[ROOT/'.gitignore',ROOT/'Election_Data_Project_Backlog.csv',
        ROOT/'backend/app/models/__init__.py',ROOT/'backend/app/models/state_results.py',
        ROOT/'backend/app/services/canonical_results.py',ROOT/'backend/ingestion/fec_authority.py',
        ROOT/'backend/ingestion/data005.py',ROOT/'backend/tests/test_fec_state_authority.py',
        ROOT/'backend/migrations/versions/d005fec2008a_authoritative_state_results.py']
    files+=list((ROOT/'backend/app/services').glob('fec_state_*.py'))
    files+=list((ROOT/'docs/data').glob('DATA005*'))
    evidence=[p for p in DATA.rglob('*') if p.is_file()]
    evidence+=[ROOT/'data/data005/final/state-comparisons.csv',ROOT/'data/data005/evidence/retrievals.json']
    record=next(r for r in read(ROOT/'data/data005/evidence/retrievals.json') if r['id']=='fec-2008-president')
    evidence+=[ROOT/'data/data005/evidence'/record[k] for k in ('file','text_file')]
    evidence+=list((ROOT/'data/ingestion/raw/fec_presidential_official').rglob('*.pdf'))
    delivery=dict(task='DATA-005 FEC authority',resolved_discrepancies=45,
        remaining_state_authority_differences=0,county_work_status='PARTIALLY_COMPLETE',
        batch_id=made['batch_id'],fingerprint=made['fingerprint'],tests=totals,
        bundles=[bundle(output/'DATA-005-FEC-source.zip',files),
                 bundle(output/'DATA-005-FEC-evidence.zip',evidence)])
    write(output/'delivery.json',delivery)
    print(json.dumps(delivery,indent=2))


if __name__=='__main__':
    main()
