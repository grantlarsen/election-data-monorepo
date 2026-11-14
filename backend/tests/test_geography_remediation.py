"""Small fixtures: matching, aliases, history, safe supersession signatures."""
from datetime import date
from uuid import uuid4
import pytest
pytest.importorskip('polars')
from ingestion.geography.resolve import assess_observation
from ingestion.geography.rules import name_key
from ingestion.geography.resolution_v2 import semantic_signature,decision_digest


def obs(state='VA',fips='51036',name='CHARLES CITY',year=2024):
    return {'year':year,'state_code':state,'state_fips':fips[:2],
        'county_raw':name,'county_fips_raw':fips,'county_fips':fips}


def ref(code='51036',label='Charles City County'):
    return {'id':uuid4(),'jurisdiction_id':uuid4(),'geoid':code,
        'state_fips':code[:2],'name_raw':label,'name_key':'INCORRECT_OLD_CACHED_KEY',
        'vintage_end':2024}


def assess(o,refs,**kwargs):
    code={r['geoid']:r for r in refs}
    names={(r['state_fips'],name_key(r['name_raw'])):[r] for r in refs}
    return assess_observation(o,code,names,{},uuid4(),2022,2024,**kwargs)


def test_virginia_county_name_key_regression():
    r=ref()
    out=assess(obs(),[r]);assert out['status']=='RESOLVED'
    assert out['jurisdiction_id']==r['jurisdiction_id']


def test_unapproved_alias_cannot_create_match():
    r=ref('27137','St. Louis County')
    o=obs('MN','27137','SAINT LOUIS')
    aliases=[dict(id=uuid4(),state_code='MN',target_geoid='27137',
        source_label_key='SAINT LOUIS',first_year=2000,last_year=2024,
        evidence_url='https://www.census.gov/')]
    assert assess(o,[r])['status']=='AMBIGUOUS'
    assert assess(o,[r],aliases=aliases)['status']=='RESOLVED_ALIAS'
    aliases[0]['target_geoid']='27001'
    assert assess(o,[r],aliases=aliases)['status']=='AMBIGUOUS'


def test_connecticut_legacy_requires_code_and_name():
    o=obs('CT','09001','FAIRFIELD')
    old=ref('09001','Fairfield County');old['vintage_end']=2021
    assert assess(o,[],legacy_by_code={'09001':old})['status']=='RESOLVED_HISTORICAL'
    assert assess(obs('CT','09001','HARTFORD'),[],legacy_by_code={'09001':old})['status']=='UNRESOLVED'


def test_dated_code_change_does_not_normalize_stale_code():
    change=dict(old_geoid='46113',new_geoid='46102',new_name='Oglala Lakota County',
                effective_date=date(2015,5,1),evidence_url='https://www.census.gov/')
    o=obs('SD','46113','OGLALA LAKOTA')
    assert assess(o,[],verified_changes=[change])['status']=='PENDING_REVIEW'
    o=obs('SD','46102','OGLALA LAKOTA')
    recent=ref('46102','Oglala Lakota County')
    out=assess(o,[],verified_changes=[change],cross_release_by_code={'46102':recent})
    assert out['status']=='RESOLVED_HISTORICAL'


def test_approval_decision_signature_idempotent():
    x={'status':'RESOLVED','method':'CENSUS_FIPS_AND_NAME','jurisdiction_id':uuid4(),
       'reference_id':uuid4(),'evidence_json':{'state':'VA'}}
    y=dict(x)
    assert semantic_signature(x)==semantic_signature(y)
    assert decision_digest(x)==decision_digest(y)
    y['status']='AMBIGUOUS'
    assert semantic_signature(x)!=semantic_signature(y)
    assert decision_digest(x)!=decision_digest(y)


def test_2024_places_gazetteer_zip_parsing():
    from pathlib import Path
    from ingestion.adapters.census_2024_places_gazetteer import parse_places
    path=Path(__file__).parent/'fixtures'/'gazetteer_places_mini.zip'
    rows=parse_places(path).to_dicts()
    assert rows[0]['geoid']=='2938000'
    assert rows[0]['state_fips']=='29'
    assert rows[0]['name_raw']=='Kansas City city'
    assert rows[1]['geoid']=='2036000'
