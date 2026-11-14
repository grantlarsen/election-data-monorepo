"""Finalize GEO-001 backlog/evidence and build a minimal patch plus evidence ZIP.

Uses only the Python standard library; never connects to a database.
Run from the host: python backend/app/services/geo001_package.py
"""
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED


def digest(path):
    h = sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def update_backlog(repo):
    path=repo/'Election_Data_Project_Backlog.csv'
    with path.open(encoding='utf-8-sig',newline='') as f:
        raw=f.read()
    reader=csv.DictReader(io.StringIO(raw,newline=''))
    fields=reader.fieldnames
    row=next(r for r in reader if r['Task ID']=='GEO-001')
    row.update({
        'Status':'Done', 'Remaining engineering hours':'0','Estimate confidence':'High',
        'Completed/available evidence':
            '2026-11-14 independent GEO-001 complete: clean base 0cfffcf; live d004a9c21e70/no schema drift; all five original step6.2.0 comparisons/context replays exact; corrected step6.2.1 comparisons cover 94,151 unique observations, 1,837 changes, 109 review cases, three zero-vote Bedford downgrades and zero jurisdiction reassignments. 113 PostgreSQL/full-suite tests passed, zero skips. All 29 original-column fingerprints, 37 public-table fingerprints and five canonical publications preserved. docs/geography/GEO001.md; GEO001-HANDOFF.md; GEO001-RUNBOOK.md; data/geo001/review-ledger.csv (1,955 observations); artifacts/geo001/GEO-001-evidence.zip and GEO-001-patch.zip.',
        'Remaining work':
            'None within GEO-001 audit/reconciliation scope (0 engineering hours; allow 1 handoff hour). GEO-002 owns approvals/publication, aliases, retired identifiers, CT legacy-area coverage, NM reference/identity repair and unsupported historical inferences; DATA-005 receives all 144 2008 exclusions; QA-001 owns Alaska hierarchy/official-total gaps; DATA-027/028 own year-specific mode/source issues. No decisions, reference records, identities or canonical batches changed in the project database.',
        'Main risk':
            'Publication must distinguish supported source classification from county eligibility/complete vote coverage. Use current step6.2.1 digests and explicit Bedford downgrade review; 47 cross-release proposals remain ineligible under DATA-003. See observation-level holds/owners; do not approve full vintage digests wholesale.',
    })
    out=io.StringIO(newline='')
    writer=csv.DictWriter(out,fieldnames=fields,lineterminator='\n')
    writer.writerow(row)
    # Replace exactly the task's single physical row; retain every unrelated byte.
    lines=raw.splitlines(keepends=True)
    indices=[i for i,line in enumerate(lines) if line.startswith('GEO-001,') or line.startswith('"GEO-001",')]
    assert len(indices)==1 and '\n' not in ''.join(row.values()).replace('\r','')
    i=indices[0]
    # Normalize only this changed row's terminator; leave unrelated rows intact.
    ending='\n' if lines[i].endswith('\n') else ''
    lines[i]=out.getvalue().rstrip('\n')+ending
    with path.open('w',encoding='utf-8-sig' if path.read_bytes().startswith(b'\xef\xbb\xbf') else 'utf-8',newline='') as f:
        f.write(''.join(lines))


def main():
    repo=Path(__file__).resolve().parents[3]
    evidence=repo/'data/geo001'
    artifacts=repo/'artifacts/geo001'
    artifacts.mkdir(parents=True,exist_ok=True)
    read=lambda name:json.loads((evidence/name).read_text(encoding='utf-8'))
    preservation=read('full-preservation.json')
    assert all(preservation[k] for k in ('all_tables_unchanged','same_table_set','data004_files_unchanged'))
    before,after=read('before.json'),read('after.json')
    assert all(after['preservation'].values())
    assert before['schema']==after['schema']
    assert before['canonical_publications']==after['canonical_publications']
    assert all(x['matches_publication'] for x in before['canonical_replay']+after['canonical_replay'])
    tests=list(ET.parse(evidence/'pytest.xml').getroot().iter('testsuite'))
    test_result={k:sum(int(t.attrib.get(k,0)) for t in tests) for k in ('tests','failures','errors','skipped')}
    assert test_result=={'tests':113,'failures':0,'errors':0,'skipped':0},test_result
    original_artifacts={}
    for line in (repo/'artifacts/data004/SHA256SUMS.txt').read_text().splitlines():
        expected,name=line.split(maxsplit=1)
        path=repo/'artifacts/data004'/name.strip()
        actual=digest(path)
        assert actual==expected,(name,expected,actual)
        original_artifacts[name.strip()]={'sha256':actual,'matches_published_manifest':True}
    dump(evidence/'original-artifact-checks.json',original_artifacts)
    cli=[]
    for path in sorted((evidence/'cli/geography').glob('resolution-*.json')):
        r=json.loads(path.read_text(encoding='utf-8'))
        expected=read(f"corrected/reproduced/compare-{r['vintage']}.json")
        r.pop('review_csv',None)
        assert r==expected
        cli.append({'file':str(path.relative_to(evidence)),'vintage':r['vintage'],
                    'equals_corrected_preview':True,'context_sha256':r['context_sha256'],
                    'proposal_sha256':r['proposal_sha256'],'records_inserted':r['records_inserted'],'published':r['published']})
    assert {r['vintage'] for r in cli}=={2000,2004,2012,2020,2024}
    dump(evidence/'cli-replays.json',cli)
    for directory in ('','corrected/'):
        check=read(directory+'independent-verification.json')
        assert check['all_observations_accounted_once'] and check['independent_vote_sums_equal_reports'] and check['all_comparison_validations_pass']
        assert not check['independent_proposed_match_errors'] and check['cross_release_matched']==47
    review=read('review-summary.json')
    assert review['original_changes_covered']==1837 and review['original_exceptions_covered']==1290
    assert review['ledger_observations']==review['unique_ledger_observations']==1955
    assert not review['publication_authorized']
    context_comparisons=[]
    for vintage in (2000,2004,2012,2020,2024):
        a=read(f'reproduced/compare-{vintage}.json')['context_manifest']
        b=read(f'corrected/reproduced/compare-{vintage}.json')['context_manifest']
        a.pop('ruleset_version');b.pop('ruleset_version')
        assert a==b
        context_comparisons.append({'vintage':vintage,'context_inputs_equal_except_ruleset':True})
    update_backlog(repo)
    files=['.gitignore','Election_Data_Project_Backlog.csv',
           'backend/ingestion/geography/cli.py','backend/ingestion/geography/context.py','backend/ingestion/geography/rules.py',
           'backend/tests/test_geography_remediation_rules.py','backend/tests/test_geography_step62_rules.py',
           'backend/tests/test_geo001_regressions.py','backend/tests/run_geo001_tests.py']
    files += [str(p.relative_to(repo)).replace('\\','/') for p in sorted((repo/'backend/app/services').glob('geo001_*.py'))]
    files += [str(p.relative_to(repo)).replace('\\','/') for p in sorted((repo/'docs/geography').glob('GEO001*'))]
    base_commit=subprocess.check_output(['git','rev-parse','0cfffcf'],cwd=repo,text=True).strip()
    manifest={'task':'GEO-001','base_commit':base_commit,'publication_authorized':False,
              'files':[{'path':name,'sha256':digest(repo/name)} for name in files]}
    dump(artifacts/'GEO-001-patch-manifest.json',manifest)
    dump(evidence/'delivery-validation.json',{'recommended_status':'Complete','remaining_geo001_engineering_hours':0,
         'handoff_review_hours':1,'executed_tests':test_result,'original_column_tables_unchanged':len(after['preservation']),
         'all_public_tables_unchanged':len(preservation['tables']),'canonical_replays_before_and_after':10,
         'schemas_equal':before['schema']==after['schema'],'cli_replays':len(cli),
         'context_comparisons':context_comparisons,
         'all_original_artifacts_match_published_checksums':True,'review_summary':review,
         'code_file_sha256':manifest['files'],'publication_authorized':False})
    delta=subprocess.check_output(['git','diff','--binary','--',*files],cwd=repo)
    (evidence/'tracked-changes.diff').write_bytes(delta)
    patch=artifacts/'GEO-001-patch.zip'
    with ZipFile(patch,'w',ZIP_DEFLATED,compresslevel=6) as z:
        for name in files:
            z.write(repo/name,name)
        z.write(artifacts/'GEO-001-patch-manifest.json','GEO-001-patch-manifest.json')
    evidence_files=sorted(p for p in evidence.rglob('*') if p.is_file() and p.name!='SHA256SUMS.txt')
    (evidence/'SHA256SUMS.txt').write_text(''.join(f'{digest(p)}  {p.relative_to(evidence).as_posix()}\n' for p in evidence_files),encoding='utf-8')
    archive=artifacts/'GEO-001-evidence.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=6) as z:
        for p in [*evidence_files,evidence/'SHA256SUMS.txt']:
            z.write(p,p.relative_to(repo).as_posix())
    for path in (patch,archive):
        with ZipFile(path) as z:
            assert z.testzip() is None
    artifact_files=[patch,archive,artifacts/'GEO-001-patch-manifest.json']
    (artifacts/'SHA256SUMS.txt').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in artifact_files),encoding='utf-8')
    print(json.dumps({'patch_files':len(files),'evidence_files':len(evidence_files)+1,
                     'patch_bytes':patch.stat().st_size,'evidence_bytes':archive.stat().st_size,
                     'test_results':test_result,'geo001_status':'Done'},indent=2))


if __name__=='__main__':
    main()
