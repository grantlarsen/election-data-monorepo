"""Source geography must be classified BEFORE code normalization/FIPS matching."""
from ingestion.geography.rules import (name_key,non_county_classification,
                                       geographic_identifier_fingerprint)


def observation(state,label,year=2024,raw=None,normalized=None):
    return dict(state_code=state,county_raw=label,county_fips_raw=raw,
                county_fips=normalized,year=year)


def test_city_and_diacritics_are_not_erased():
    assert name_key('Charles City County, VA') == 'CHARLES CITY'
    assert name_key('CHARLES CITY') == 'CHARLES CITY'
    assert name_key('James City County') == 'JAMES CITY'
    assert name_key('Doña Ana County') == name_key('DONA ANA')
    assert name_key('St. Louis County') != name_key('Saint Louis County')
    assert name_key('Richmond city') != name_key('Richmond County')
    assert name_key('La Salle Parish') != name_key('LaSalle Parish')


def test_alaska_codes_cannot_become_counties():
    for number,code in [(13,'02013'),(16,'02016'),(20,'02020')]:
        d=non_county_classification(observation('AK',f'DISTRICT {number}',2020,code,code))
        assert d['status']=='NON_COUNTY_CLASSIFIED'
        assert d['namespace']=='AK_MEDSL_DISTRICT'
        assert d['identifier']==f'2020:{number}'
        assert d.get('jurisdiction_id') is None
    assert non_county_classification(observation('AK','DISTRICT 01',2024))['identifier']=='2024:1'
    assert non_county_classification(observation('AK','DISTRICT 99'))['status']=='PENDING_REVIEW'


def test_special_reporting_units_have_no_implied_county():
    for state,label in [('CT','STATEWIDE WRITEIN'),('ME','MAINE UOCAVA'),
                        ('RI','FEDERAL PRECINCT')]:
        d=non_county_classification(observation(state,label,2008))
        assert d['status']=='NON_COUNTY_CLASSIFIED'
        assert d['namespace']=='MEDSL_REPORTING_UNIT'


def test_kansas_city_place_is_not_a_county_and_2024_bad_code_is_not_hidden():
    good=non_county_classification(observation('MO','KANSAS CITY',2020,'2938000'))
    assert good['namespace']=='CENSUS_PLACE'
    assert good['identifier']=='2938000'
    assert non_county_classification(observation('MO','KANSAS CITY',2024,'36000')) is None


def test_original_input_fingerprint_is_stable():
    a=observation('AK','DISTRICT 20',2020,'2020','02020')
    original=dict(a)
    geographic_identifier_fingerprint(a)
    non_county_classification(a)
    assert a==original
