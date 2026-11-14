"""Defects and date boundaries identified by the independent GEO-001 audit."""
import json

import pytest

from ingestion.geography.context import digest, read_preview
from ingestion.geography.resolve import assess_observation
from ingestion.geography.rules import non_county_classification
from uuid import uuid4


def test_archived_preview_rejects_corrupt_supplemental_inputs(tmp_path):
    path = tmp_path / 'preview.json'
    manifest = {'references': [{'geoid': '11001', 'name_raw': 'District of Columbia'}]}
    report = {'context_manifest': manifest, 'context_sha256': digest(manifest)}
    path.write_text(json.dumps(report), encoding='utf-8')
    assert read_preview(path) == manifest
    # The old CLI accepted this changed reference while keeping the recorded SHA.
    report['context_manifest']['references'][0]['name_raw'] = 'Corrupted label'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(ValueError, match='corrupt archived'):
        read_preview(path)
    report.pop('context_sha256')
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(ValueError, match='corrupt archived'):
        read_preview(path)


def test_kansas_city_place_style_code_does_not_assert_whole_place_coverage():
    obs = {'state_code':'MO','year':2008,'county_raw':'KANSAS CITY','county_fips_raw':'2938000'}
    out = non_county_classification(obs)
    assert out['status'] == 'NON_COUNTY_CLASSIFIED'
    assert out['kind'] == 'source_reporting_unit'
    assert out['namespace'] == 'MEDSL_REPORTING_UNIT'
    assert out['identifier'] == 'MO:2008:KANSAS CITY'
    assert non_county_classification({**obs,'county_fips_raw':'36000'}) is None


@pytest.mark.parametrize('state,code,label,reference,year,expected', [
    ('VA','51515','BEDFORD','Bedford city',2012,'RESOLVED_HISTORICAL'),
    ('VA','51515','BEDFORD','Bedford city',2016,'PENDING_REVIEW'),
    ('SD','46113','SHANNON','Shannon County',2012,'RESOLVED_HISTORICAL'),
    ('SD','46113','SHANNON','Shannon County',2016,'PENDING_REVIEW'),
    ('SD','46102','OGLALA LAKOTA','Oglala Lakota County',2016,'UNRESOLVED'),
])
def test_same_2012_product_does_not_define_legal_identifier_lifetime(state,code,label,reference,year,expected):
    obs = {'year':year,'state_code':state,'state_fips':code[:2],
           'county_raw':label,'county_fips_raw':code,'county_fips':code}
    ref = {'id':uuid4(),'jurisdiction_id':uuid4(),'geoid':code,
           'state_fips':code[:2],'name_raw':reference,'vintage_end':2016}
    # The archived georef12 product contains Bedford/Shannon but no 46102.
    by_code = {} if code == '46102' else {code:ref}
    latest = {'46102':(2024,'OGLALA LAKOTA')}  # Neither retired identifier is current.
    decision = assess_observation(obs,by_code,{},latest,uuid4(),2012,2016)
    assert decision['status'] == expected
    if expected == 'RESOLVED_HISTORICAL':
        assert decision['jurisdiction_id'] == ref['jurisdiction_id']
        assert decision['evidence_json']['legal_effective_dates_verified'] is False
    else:
        assert decision['jurisdiction_id'] is None  # No successor remapping.
