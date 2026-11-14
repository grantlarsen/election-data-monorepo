"""Small geographic resolver fixtures; SQLite/Postgres connections not needed."""
from datetime import date
from uuid import uuid4
from zipfile import ZipFile

import pytest
pytest.importorskip("polars")

from ingestion.geography.resolve import assess_observation
from ingestion.geography.rules import name_key
from ingestion.adapters.census_2000_counties_gazetteer import parse_counties


def _observation(state, code, label, year):
    return {"year": year, "state_code": state, "state_fips": code[:2],
            "county_raw": label, "county_fips_raw": code, "county_fips": code}


def _ref(code, name, year):
    return {"id": uuid4(), "jurisdiction_id": uuid4(), "geoid": code,
            "name_raw": name, "name_key": name_key(name), "state_fips": code[:2],
            "vintage_end": year, "release_id": uuid4()}


def _assess(observation, refs, **kwargs):
    by_code = {r["geoid"]: r for r in refs}
    by_name = {(r["state_fips"], name_key(r["name_raw"])): [r] for r in refs}
    return assess_observation(observation, by_code, by_name, {}, uuid4(),
                              1996 if observation["year"] == 2000 else 2012,
                              2001 if observation["year"] == 2000 else 2016, **kwargs)


def test_virginia_independent_and_county_cases():
    city = _ref("51600", "Fairfax city", 2001)
    county = _ref("51059", "Fairfax County", 2001)
    assert _assess(_observation("VA", "51600", "FAIRFAX", 2000), [city, county])["jurisdiction_id"] == city["jurisdiction_id"]
    assert _assess(_observation("VA", "51059", "FAIRFAX", 2000), [city, county])["jurisdiction_id"] == county["jurisdiction_id"]
    assert _assess(_observation("VA", "51600", "CHARLES CITY", 2000), [city, county])["status"] == "AMBIGUOUS"
    assert _assess(_observation("VA", "51036", "CHARLES CITY", 2000), [_ref("51036", "Charles City County", 2001)])["status"] == "RESOLVED"


def test_bedford_after_2013_no_stale_cbp_match():
    bedford = _ref("51515", "Bedford city", 2016)
    out = _assess(_observation("VA", "51515", "BEDFORD", 2016), [bedford])
    assert out["status"] == "PENDING_REVIEW"
    assert out["method"] == "RETIRED_OFFICIAL_GEOID"
    assert out["jurisdiction_id"] is None
    assert out["evidence_json"]["retirement_evidence"]["reason"].startswith("Bedford ceased")
    assert out["evidence_json"]["retirement_evidence"]["official_retirement_date"] == "2013-07-01"


def test_missing_census_2000_reference_needs_exact_2000_gazetteer():
    for state, code, label, reference_name in [
        ("DC", "11001", "DISTRICT OF COLUMBIA", "District of Columbia"),
        ("FL", "12086", "MIAMI-DADE", "Miami-Dade County"),
    ]:
        reference = _ref(code, reference_name, 2000)
        obs = _observation(state, code, label, 2000)
        assert _assess(obs, [])["status"] == "UNRESOLVED"
        out = _assess(obs, [], supplemental_2000_by_code={code: reference})
        assert out["status"] == "RESOLVED_HISTORICAL"
        assert out["method"] == "CENSUS_2000_GAZETTEER_SUPPLEMENT"
        assert out["jurisdiction_id"] == reference["jurisdiction_id"]
        assert _assess({**obs, "county_raw": "WRONG NAME"}, [],
                       supplemental_2000_by_code={code: reference})["status"] == "UNRESOLVED"


def test_south_dakota_retired_code_is_review_only():
    old = _ref("46113", "Shannon County", 2016)
    out = _assess(_observation("SD", "46113", "SHANNON", 2016), [old])
    assert out["status"] == "PENDING_REVIEW"
    assert out["jurisdiction_id"] is None
    assert out["method"] == "RETIRED_OFFICIAL_GEOID"
    assert out["evidence_json"]["retirement_evidence"]["successor_county_geoid"] == "46102"
    assert out["evidence_json"]["retirement_evidence"]["official_retirement_date"] == "2015-05-01"


def test_2000_counties_fixed_width_parser(tmp_path):
    # Published 2000 Census Gazetteer columns 1-2 USPS, 3-4 state FIPS,
    # 5-7 county FIPS, 8-71 county name. No external download.
    path = tmp_path / "counties.zip"
    data = ''.join(
        state_abbr + fips + county + name.ljust(64) + " 123\n"
        for state_abbr, fips, county, name in [
            ("DC", "11", "001", "District of Columbia"),
            ("FL", "12", "086", "Miami-Dade County"),
        ]
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("county2k.txt", data)
    frame = parse_counties(path)
    assert frame.get_column("geoid").to_list() == ["11001", "12086"]
    assert frame.get_column("name_key").to_list() == ["DISTRICT OF COLUMBIA", "MIAMI DADE"]
