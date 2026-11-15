"""Validate and package pending GEO-002 work; update only its backlog row. No DB access."""
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED


def file_sha(path):
    h = sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def dump(path, value):
    with path.open('x', encoding='utf-8') as f:
        f.write(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def update_backlog(repo):
    path = repo / 'Election_Data_Project_Backlog.csv'
    original = path.read_bytes()
    raw = original.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(raw, newline=''))
    fields = reader.fieldnames
    task = next(r for r in reader if r['Task ID'] == 'GEO-002')
    task.update({'Status': 'Blocked',
        'Completed/available evidence':
            '2026-11-14 GEO-002 technical review/approval preparation: 94,151 observations and all five step6.2.1 context/proposal digests independently reproduced; 1,955-row ledger partitions 1,766 exact routine targets, three separately gated Bedford downgrades and 186 held/unchanged concerns. Selective append-only gate binds predecessor and complete payload, actor and SHA; 121 full PostgreSQL tests passed, zero skips; six read-only CLI subset replays; all 37 public-table fingerprints and five canonical publications preserved. docs/geography/GEO002.md; GEO002-RESEARCH.md; GEO002-RUNBOOK.md; data/geo002/approval-manifest.json; artifacts/geo002/. No live publication or evidence approval performed; approving actor unset.',
        'Remaining work':
            'Obtain explicit signoff for five exact routine subset SHA targets and accountable actor; separately authorize or decline Bedford downgrade SHA. Publish only approved subsets, reconcile immutable actor/digest/payload audit, prove live zero-insert replay and expected append-only changes while preserving sources/references/identities/canonical batches. Retain observation-level research holds and DATA-005/QA-001/DATA-027/028 ownership. Cross-release eligibility and canonical supersession require separate work/authorization. Do not mark Done before live validation.',
        'Main risk':
            'Full-vintage digests do not approve held cases. Preserve 47 cross-release canonical restrictions, all old UUIDs/reference rows and canonical pointers; Bedford needs separate downgrade signoff. Research/source coverage gaps remain explicit.'})
    out = io.StringIO(newline='')
    csv.DictWriter(out, fieldnames=fields, lineterminator='\n').writerow(task)
    lines = raw.splitlines(keepends=True)
    positions = [i for i, line in enumerate(lines) if line.startswith(('GEO-002,', '"GEO-002",'))]
    assert len(positions) == 1 and all('\n' not in v and '\r' not in v for v in task.values())
    pos = positions[0]
    # This mixed-ending CSV is stored without Git CRLF normalization. Use LF
    # only for the changed row so git diff --check stays clean.
    ending = '\n' if lines[pos].endswith('\n') else ''
    lines[pos] = out.getvalue().rstrip('\n') + ending
    replacement = ''.join(lines).encode('utf-8')
    if original.startswith(b'\xef\xbb\xbf'):
        replacement = b'\xef\xbb\xbf' + replacement
    assert [x for x in original.splitlines(keepends=True) if not x.startswith((b'GEO-002,', b'"GEO-002",'))] == [
        x for x in replacement.splitlines(keepends=True) if not x.startswith((b'GEO-002,', b'"GEO-002",'))]
    path.write_bytes(replacement)


def main():
    repo = Path(__file__).resolve().parents[3]
    evidence = repo / 'data/geo002'
    read = lambda name: json.loads((evidence / name).read_text(encoding='utf-8'))
    preservation = read('full-preservation.json')
    assert all(preservation[k] for k in ('all_tables_unchanged', 'same_table_set', 'data004_files_unchanged'))
    before, after = read('before.json'), read('after.json')
    assert before['schema'] == after['schema']
    assert all(after['preservation'].values())
    assert before['canonical_publications'] == after['canonical_publications']
    assert all(x['matches_publication'] for x in before['canonical_replay'] + after['canonical_replay'])
    suites = list(ET.parse(evidence / 'tests-final/pytest.xml').getroot().iter('testsuite'))
    tests = {k: sum(int(s.attrib.get(k, 0)) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
    assert tests == {'tests': 121, 'failures': 0, 'errors': 0, 'skipped': 0}, tests
    assert read('schema-current.json')['exit_code'] == read('schema-check.json')['exit_code'] == 0
    assert 'd004a9c21e70 (head)' in read('schema-current.json')['stdout']
    assert 'No new upgrade operations detected' in read('schema-check.json')['stdout']
    package = read('approval-manifest.json')
    assert not package['publication_authorized'] and package['approving_actor'] is None
    assert not package['canonical_supersession_authorized']
    with (evidence / 'review-ledger.csv').open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len({r['observation_id'] for r in rows}) == 1955
    expected = {r['observation_id'] for r in rows if r['geo002_disposition'] != 'HOLD_NO_PUBLICATION'}
    targets = set()
    selected_checks = []
    for scope in package['routine'] + package['bedford_separate']:
        envelope = read(scope['manifest_file'])
        manifest = envelope['manifest']
        actual = sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        assert actual == envelope['publication_sha256'] == scope['publication_sha256']
        ids = {t['observation_id'] for t in manifest['targets']}
        assert not targets & ids and len(ids) == scope['target_count']
        targets |= ids
        for t in manifest['targets']:
            row = next(r for r in rows if r['observation_id'] == t['observation_id'])
            assert t['previous']['id'] == row['decision_id']
            assert t['decision']['status'] == row['proposed_status']
            assert t['decision']['reference_id'] == (row['proposed_reference_id'] or None)
            assert t['decision']['jurisdiction_id'] == (row['proposed_jurisdiction_id'] or None)
            assert t['decision']['evidence_json'] == json.loads(row['evidence_json'])
        selected_checks.append({'file': scope['manifest_file'], 'independent_sha256': actual, 'targets': len(ids)})
    assert expected == targets and len(targets) == 1769
    cli = read('cli-replays.json')
    assert len(cli) == 6 and all(not x['published'] and x['inserted'] == 0 for x in cli)
    assert {x['publication_sha256'] for x in cli} == {x['independent_sha256'] for x in selected_checks}
    original_artifacts = {}
    for owner in ('data004', 'geo001'):
        directory = repo / 'artifacts' / owner
        for line in (directory / 'SHA256SUMS.txt').read_text().splitlines():
            expected_sha, name = line.split(maxsplit=1)
            path = directory / name.strip()
            assert file_sha(path) == expected_sha
            original_artifacts[str(path.relative_to(repo)).replace('\\', '/')] = expected_sha
    # Verify every original GEO-001 evidence file against its preserved evidence ZIP.
    with ZipFile(repo / 'artifacts/geo001/GEO-001-evidence.zip') as z:
        original_checks = []
        for name in z.namelist():
            path = repo / name
            if name.startswith('data/geo001/') and not name.endswith('/'):
                assert path.is_file() and file_sha(path) == sha256(z.read(name)).hexdigest(), name
                original_checks.append(name)
    dump(evidence / 'original-evidence-checks.json', {'artifact_sha256': original_artifacts,
        'geo001_files_matching_preserved_zip': len(original_checks),
        'data004_files_unchanged': preservation['data004_files_unchanged']})
    dump(evidence / 'selected-digest-checks.json', selected_checks)
    dump(evidence / 'validation.json', {'tests': tests, 'all_public_tables_preserved': 37,
        'canonical_batches_preserved_and_replayed': 5, 'selected_targets_independently_verified': 1769,
        'held_observations_excluded': 186, 'live_publication_attempts': 0, 'approval_pending': True,
        'schema_head': before['alembic_revision'], 'cli_subset_replays': len(cli)})
    artifacts = repo / 'artifacts/geo002'
    artifacts.mkdir(exist_ok=False)
    update_backlog(repo)
    files = ['.gitignore', 'Election_Data_Project_Backlog.csv',
        'backend/ingestion/__main__.py', 'backend/ingestion/geography/cli.py',
        'backend/ingestion/geography/resolve.py', 'backend/ingestion/geography/resolution_v2.py',
        'backend/ingestion/geography/selection.py', 'backend/app/services/geo002_review.py',
        'backend/app/services/geo002_validate.py', 'backend/app/services/geo002_package.py',
        'backend/tests/test_geo002_publication.py', 'backend/tests/run_geo002_tests.py',
        'docs/geography/GEO002.md', 'docs/geography/GEO002-RESEARCH.md',
        'docs/geography/GEO002-RUNBOOK.md', 'docs/geography/GEO002-sources.json']
    patch_manifest = {f: file_sha(repo / f) for f in files}
    dump(artifacts / 'patch-manifest.json', patch_manifest)
    evidence_files = sorted(p for p in evidence.rglob('*') if p.is_file())
    evidence_manifest = {p.relative_to(repo).as_posix(): file_sha(p) for p in evidence_files}
    dump(evidence / 'file-manifest.json', evidence_manifest)
    with ZipFile(artifacts / 'GEO-002-patch.zip', 'x', ZIP_DEFLATED) as z:
        for f in files:
            z.write(repo / f, f)
        z.write(artifacts / 'patch-manifest.json', 'patch-manifest.json')
    with ZipFile(artifacts / 'GEO-002-evidence.zip', 'x', ZIP_DEFLATED) as z:
        for p in evidence_files + [evidence / 'file-manifest.json']:
            z.write(p, p.relative_to(repo).as_posix())
    for label, manifest in [('patch', patch_manifest), ('evidence', evidence_manifest)]:
        with ZipFile(artifacts / f'GEO-002-{label}.zip') as z:
            assert z.testzip() is None
            for name, expected_sha in manifest.items():
                assert sha256(z.read(name)).hexdigest() == expected_sha
    (artifacts / 'SHA256SUMS.txt').write_text(''.join(f'{file_sha(artifacts / name)}  {name}\n' for name in
        ('GEO-002-patch.zip', 'GEO-002-evidence.zip', 'patch-manifest.json')), encoding='utf-8')
    print(json.dumps({'tests': tests, 'routine': 1766, 'bedford_separate': 3, 'holds': 186,
        'original_geo001_files_verified': len(original_checks), 'publication_authorized': False,
        'artifacts': str(artifacts)}))


if __name__ == '__main__':
    main()
