"""Presidential returns: exact independent comparisons, hierarchy and evidence failures."""
from copy import deepcopy
import json

import pytest

from ingestion.presidential_returns_2008 import (BUCKETS, alaska_district, bucket, compare, digest,
    evidence, exclusion_partition, fec_states, manual_units, minnesota_units,
    sum_observations, virginia_units)
from app.services.presidential_returns_reconciliation import geography_audit


RECORD = dict(id='fixture', url='https://authority.example/results', sha256='a'*64,
              retrieved_at='2026-11-15T03:00:00Z')


def test_exact_differences_missing_evidence_and_incompatible_levels():
    assert compare(100, 100, comparable=True, complete=True)['disposition'] == 'EXACT'
    assert compare(100, 99, comparable=True, complete=True)['difference'] == -1
    assert compare(100, 99, comparable=True, complete=True)['disposition'] == 'MISMATCH'
    assert compare(100, 100, comparable=True, complete=False)['disposition'] == 'PARTIAL_COVERAGE'
    assert compare(100, 99, comparable=False, complete=True)['difference'] is None
    assert compare(None, 99, comparable=True, complete=True, evidence_available=False)['disposition'] == 'EVIDENCE_UNAVAILABLE'


def test_grouping_preserves_other_and_rejects_duplicates_modes_missing_votes():
    rows = [dict(observation_id=str(i), candidate=b, votes=v, mode='TOTAL')
            for i,(b,v) in enumerate(zip(BUCKETS,(100,80,3)))]
    assert sum_observations(rows) == dict(zip(BUCKETS,(100,80,3)))
    with pytest.raises(ValueError, match='Duplicate observation'):
        sum_observations(rows + [rows[0]])
    for value in (None, -1):
        with pytest.raises(ValueError, match='missing votes'):
            sum_observations([{**rows[0], 'votes': value}])
    with pytest.raises(ValueError, match='reporting mode'):
        sum_observations([{**rows[0], 'mode': 'ABSENTEE'}])
    with pytest.raises(ValueError, match='Unreviewed'):
        bucket('RALPH NADER')


def test_fec_combined_parties_do_not_double_count_or_lose_writeins():
    from ingestion.medsl import STATE_NAMES
    pages = []
    for state, name in STATE_NAMES.items():
        text = (f'{name}\nObama, Barack Combined Parties: 100 50.00%\n'
                'Obama, Barack D [80] 40.00%\nObama, Barack WF [20 10.00%\n'
                'McCain, John R 90 45.00%\nScattered W 10 5.00%\nTotal State Votes: 200')
        pages.append(dict(page=len(pages)+1,text=text))
    result = fec_states(pages, RECORD)
    assert len(result) == 51 and result['NY']['totals'] == dict(zip(BUCKETS,(100,90,10)))
    changed = deepcopy(pages)
    changed[0]['text'] = changed[0]['text'].replace('Total State Votes: 200','Total State Votes: 201')
    with pytest.raises(ValueError, match='component sum'):
        fec_states(changed, RECORD)
    with pytest.raises(ValueError, match='Incomplete FEC'):
        fec_states(pages[:-1], RECORD)


def test_alaska_totals_are_not_added_to_their_precincts():
    header = 'Official Results\nDistrict 8 - Absentee\nUS PRESIDENT\n'
    # registered, cards, turnout, registered, presidential total, six categories
    text = header + '100 20 20.00% 100 20 1 1 10 2 5 1\n100 20 20.00% 100 20 1 1 10 2 5 1'
    result = alaska_district([dict(page=1,plain_text=text)], RECORD, 8)
    assert result['totals'] == dict(zip(BUCKETS,(5,10,5)))
    assert result['precinct_rows'] == 1
    with pytest.raises(ValueError, match='hierarchy'):
        alaska_district([dict(page=1,plain_text=text[:-1]+'2')], RECORD, 8)
    with pytest.raises(ValueError, match='hierarchy'):
        alaska_district([dict(page=1,plain_text=text+'\n100 20 20.00% 100 20 1 1 10 2 5 1')], RECORD,8)


def test_manual_facing_pages_and_duplicate_or_incomplete_rows():
    rows = manual_units('JACKSON 10 20 1 2 3 4     KANSAS CITY 30 40 2 3 4 5',
        ['JOHN MCCAIN','BARACK OBAMA']+['OTHER']*4, RECORD, 'page 4',2)
    assert rows[0]['totals'] == dict(zip(BUCKETS,(20,10,10)))
    assert rows[1]['totals']['OTHER'] == 14
    with pytest.raises(ValueError, match='distinct manual'):
        manual_units('JACKSON 10 20\nJACKSON 10 20',['JOHN MCCAIN','BARACK OBAMA'],RECORD,'page 4',2)


def test_minnesota_scattered_and_named_writeins_reconcile_independently():
    lookup, lines = [], []
    for code in range(1,88):
        lookup.append(f'{code:02d};COUNTY {code};1')
        for cid,name,votes in [('0301','JOHN MCCAIN AND SARAH PALIN',8),
                               ('0401','BARACK OBAMA AND JOE BIDEN',10),
                               ('9901','WRITE-IN**',1),('9902','NAMED WRITE-IN**',1)]:
            row = ['MN',f'{code:02d}','','0101','US PRESIDENT & VICE PRESIDENT','',cid,name,'','','WI','1','1',str(votes),'0','20']
            lines.append(';'.join(row))
    result = minnesota_units('\n'.join(lines),'\n'.join(lookup),RECORD)
    assert len(result) == 87 and result[0]['totals']['OTHER'] == 2
    with pytest.raises(ValueError, match='duplicate Minnesota'):
        minnesota_units('\n'.join(lines+[lines[0]]),'\n'.join(lookup),RECORD)
    with pytest.raises(ValueError, match='office totals differ'):
        minnesota_units('\n'.join(lines).replace(';20\n',';21\n',1),'\n'.join(lookup),RECORD)


def test_virginia_never_adds_precinct_and_statewide_to_localities():
    import csv,io
    s = io.StringIO(); w=csv.writer(s)
    w.writerow(['','','Barack Obama and Joe Biden','John McCain and Sarah Palin','Nader','Barr','Baldwin','McKinney','Write-Ins','Total Votes Cast','Undervotes'])
    w.writerow(['','']+['']*9)
    w.writerow(['State','Virginia',1340,1072,0,0,0,0,134,2546,0])
    w.writerow(['Precinct','P1',10,8,0,0,0,0,1,19,0])
    for i in range(134):
        w.writerow(['Locality',f'County {i} County',10,8,0,0,0,0,1,19,0])
    rows=virginia_units(s.getvalue(),RECORD)
    assert len(rows)==134 and sum(r['totals']['BARACK OBAMA'] for r in rows)==1340
    with pytest.raises(ValueError,match='columns changed'):
        virginia_units(s.getvalue().replace('Write-Ins','Unknown'),RECORD)


def test_exclusions_require_exact_144_ids_partitions_and_lineage():
    rows=[]
    specs=[('AK','DISTRICT 1',120),('AK','DISTRICT 99',3),('MN','SAINT LOUIS',3),
           ('VA','CHARLES CITY',6),('CT','SPECIAL',12)]
    for state,name,count in specs:
        for _ in range(count):
            rows.append(dict(observation_id=str(len(rows)),state=state,county=name,
                row_sha256='a'*64,votes=0,stored_accepted=False))
    handoff=[dict(observation_id=r['observation_id'],row_sha256=r['row_sha256'],votes='0') for r in rows]
    assert len(exclusion_partition(handoff,rows))==144
    with pytest.raises(ValueError,match='144 distinct'):
        exclusion_partition(handoff[:-1]+[handoff[0]],rows)
    corrupted=deepcopy(handoff);corrupted[0]['row_sha256']='b'*64
    with pytest.raises(ValueError,match='source lineage'):
        exclusion_partition(corrupted,rows)


def test_evidence_checksum_tampering_fails(tmp_path):
    (tmp_path/'raw').write_bytes(b'official')
    from hashlib import sha256
    r={**RECORD,'success':True,'file':'raw','sha256':sha256(b'official').hexdigest()}
    (tmp_path/'retrievals.json').write_text(json.dumps([r]))
    assert evidence(tmp_path)['fixture']['success']
    (tmp_path/'raw').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Corrupt raw'):
        evidence(tmp_path)


def test_published_geographic_actor_digest_and_complete_payload(tmp_path):
    (tmp_path/'approvals').mkdir()
    decision=dict(status='RESOLVED',method='EXACT',reference_id='ref',jurisdiction_id='county',reason='cited',evidence_json={'evidence_url':'official'})
    manifest=dict(context_sha256='context',targets=[dict(observation_id='obs',previous={'id':'old'},decision=decision)])
    sha=digest(manifest)
    (tmp_path/'approvals'/'subset.json').write_text(json.dumps(dict(manifest=manifest,publication_sha256=sha)))
    head={**decision,'id':'new','supersedes_id':'old','published_by':'reviewer','context_sha256':'context',
          'evidence_json':{**decision['evidence_json'],'publication_audit':{'publication_sha256':sha}}}
    row=dict(observation_id='obs',geography=head)
    assert geography_audit([row],tmp_path)[0]['exact_manifest_successor']
    altered=deepcopy(row);altered['geography']['reason']='unsupported replacement'
    with pytest.raises(ValueError,match='direct successor'):
        geography_audit([altered],tmp_path)
    altered=deepcopy(row);altered['geography']['published_by']=''
    with pytest.raises(ValueError,match='actor'):
        geography_audit([altered],tmp_path)
