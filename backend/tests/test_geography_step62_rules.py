"""No database, Polars, or download required; real Step 6.1 regression fixture."""
import json
from pathlib import Path

import pytest

from ingestion.geography.rules import (
    RULESET_VERSION, county_equivalent_name_match, name_key,
    retired_identifier_evidence, non_county_classification,
)

FIXTURE = Path(__file__).parent / "fixtures" / "virginia_2000_2016_regressions.json"


def test_real_virginia_regressions_keep_only_retired_bedford_pending():
    fixture = json.loads(FIXTURE.read_text())
    assert sum(row["count"] for row in fixture) == 624
    assert len(fixture) == 195
    restored = retired = 0
    for row in fixture:
        # Source Census references are county-equivalent names ending in 'city'.
        # This verifies the matching predicate against real source FIPS/labels.
        # Full PostgreSQL integration remains a separate test.
        match = county_equivalent_name_match(
            "VA", row["county_fips"], row["label"], row["label"].title() + " city", row["year"]
        )
        if row["county_fips"] == "51515" and row["year"] >= 2016:
            assert match is None
            assert retired_identifier_evidence("VA", row["county_fips"], row["year"])
            retired += row["count"]
        else:
            assert match == "CENSUS_INDEPENDENT_CITY_SUFFIX", row
            assert retired_identifier_evidence("VA", row["county_fips"], row["year"]) is None
            restored += row["count"]
    assert restored == 621 and retired == 3


@pytest.mark.parametrize("geoid,label,refname,expected", [
    ("51510", "ALEXANDRIA", "Alexandria city", "CENSUS_INDEPENDENT_CITY_SUFFIX"),
    ("51600", "FAIRFAX", "Fairfax city", "CENSUS_INDEPENDENT_CITY_SUFFIX"),
    ("51059", "FAIRFAX", "Fairfax County", "CENSUS_NAME_EXACT"),
    ("51059", "FAIRFAX", "Fairfax city", None),
    ("51600", "FAIRFAX COUNTY", "Fairfax city", None),
    ("51036", "CHARLES CITY", "Charles City County", "CENSUS_NAME_EXACT"),
    ("51095", "JAMES CITY", "James City County", "CENSUS_NAME_EXACT"),
    ("51036", "CHARLES", "Charles City County", None),
    ("51515", "BEDFORD", "Bedford city", "CENSUS_INDEPENDENT_CITY_SUFFIX"),
])
def test_code_and_name_specific_virginia_matches(geoid, label, refname, expected):
    assert county_equivalent_name_match("VA", geoid, label, refname, 2008) == expected


def test_context_not_global_city_strip():
    assert name_key("Richmond city") != name_key("Richmond County")
    assert county_equivalent_name_match("VA", "51760", "RICHMOND", "Richmond County", 2024) is None
    assert county_equivalent_name_match("VA", "51760", "RICHMOND", "Richmond city", 2024)
    assert county_equivalent_name_match("VA", "51036", "CHARLES", "Charles City County", 2024) is None
    assert county_equivalent_name_match("NY", "36061", "NEW YORK", "New York city", 2024) is None
    assert RULESET_VERSION == "step6.2.0"


def test_known_identifier_retirements_are_never_automatically_mapped():
    assert retired_identifier_evidence("VA", "51515", 2012) is None
    assert retired_identifier_evidence("VA", "51515", 2016)["successor_county_geoid"] == "51019"
    assert retired_identifier_evidence("SD", "46113", 2012) is None
    assert retired_identifier_evidence("SD", "46113", 2024)["successor_county_geoid"] == "46102"


def test_district_99_remains_pending_without_multiyear_evidence():
    for year in (2000, 2004, 2008, 2012, 2016, 2020, 2024):
        decision = non_county_classification({"year": year, "state_code": "AK", "county_raw": "DISTRICT 99"})
        assert decision["status"] == "PENDING_REVIEW"
        assert decision["namespace"] == "AK_MEDSL_DISTRICT"
