"""Pure, conservative election-geography rules.

Source labels are classified before any attempt to interpret an apparent FIPS code.
Classification is *not* a canonical geographic identity match.
"""
from __future__ import annotations

import re
import unicodedata

RULESET_VERSION = "step6.2.0"
ALASKA_ELECTION_RESULTS = "https://www.elections.alaska.gov/election-results/"
ALASKA_2018_DISTRICT_99_EVIDENCE = "https://www.elections.alaska.gov/doc/mp/2018/2018GenMedaiPacket.pdf"
CENSUS_CT_CHANGE = "https://www.federalregister.gov/documents/2022/06/06/2022-12063/change-to-county-equivalents-in-the-state-of-connecticut"
CENSUS_2015_CHANGES = "https://www.census.gov/programs-surveys/acs/technical-documentation/table-and-geography-changes/2015/geography-changes.html"
CENSUS_MO_PLACES = "https://tigerweb.geo.census.gov/tigerwebmain/Files/bas26/tigerweb_bas26_incplace_mo.html"

# Avoid stripping CITY: Charles City County and independent Richmond city differ
# from counties/cities named Charles or Richmond. Suffixes removed only at end.
SUFFIX = re.compile(r"\s+(?:CITY AND BOROUGH|CENSUS AREA|INDEPENDENT CITY|COUNTY|PARISH|BOROUGH|MUNICIPALITY)$")


def name_key(value: str | None) -> str:
    if not value:
        return ""
    value = value.split(",", 1)[0].strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^A-Za-z0-9]+", " ", value.upper())
    value = " ".join(value.split())
    return SUFFIX.sub("", value).strip()


def non_county_classification(obs: dict) -> dict | None:
    """Classify reporting units; never infer a county or canonical UUID.

    The election source is scoped to MEDSL presidential county observations.
    District numbers can be reused in different years and plans.
    """
    state = (obs.get("state_code") or "").upper()
    label = name_key(obs.get("county_raw"))
    year = int(obs["year"])
    raw = str(obs.get("county_fips_raw") or "").strip()
    if state == "AK":
        m = re.fullmatch(r"DISTRICT\s+0*([1-9][0-9]?)", label)
        if m:
            number = int(m.group(1))
            if number == 99:
                return dict(status="PENDING_REVIEW", method="AK_DISTRICT_99_UNKNOWN",
                            kind="special_reporting_unit", namespace="AK_MEDSL_DISTRICT",
                            identifier=f"{year}:{number}", evidence_url=ALASKA_2018_DISTRICT_99_EVIDENCE,
                            reason="Alaska 2018 source documents federal-only overseas absentee ballots; meaning for this specific MEDSL year still requires verification")
            return dict(status="NON_COUNTY_CLASSIFIED", method="AK_ELECTION_DISTRICT",
                        kind="state_legislative_reporting_district", namespace="AK_MEDSL_DISTRICT",
                        identifier=f"{year}:{number}", evidence_url=ALASKA_ELECTION_RESULTS,
                        reason="Election district is not a Census county; no canonical district boundary asserted")
    if state == "CT" and label == "STATEWIDE WRITEIN":
        kind = "statewide_reporting_unit"
        method = "SOURCE_STATEWIDE_WRITEIN"
    elif state == "ME" and label == "MAINE UOCAVA":
        kind = "special_reporting_unit"
        method = "SOURCE_UOCAVA"
    elif state == "RI" and label == "FEDERAL PRECINCT":
        kind = "special_reporting_unit"
        method = "SOURCE_FEDERAL_PRECINCT"
    elif state == "MO" and label == "KANSAS CITY":
        if raw == "2938000":
            return dict(status="NON_COUNTY_CLASSIFIED", method="CENSUS_PLACE_GEOID",
                        kind="census_place", namespace="CENSUS_PLACE", identifier=raw,
                        evidence_url=CENSUS_MO_PLACES,
                        reason="Seven-digit Census place GEOID, not a county identifier; no county allocation")
        # A contradictory code is an error, not a valid place match.
        return None
    else:
        return None
    return dict(status="NON_COUNTY_CLASSIFIED", method=method, kind=kind,
                namespace="MEDSL_REPORTING_UNIT", identifier=f"{state}:{year}:{label}",
                evidence_url=None,
                reason="Source reports votes in a non-county category; county is intentionally null")


def geographic_identifier_fingerprint(obs: dict) -> dict:
    """Immutable set of values used for regression and drift evidence."""
    return {k: obs.get(k) for k in
            ("year", "state_code", "state_fips", "county_raw", "county_fips_raw", "county_fips")}

# Documentary evidence: Census classifies Virginia independent cities as county
# equivalents, distinguished from ordinary counties by a 3-digit county code
# >= 500. Other independent cities are only recognized by explicit codes.
CENSUS_INDEPENDENT_CITIES = (
    "https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2025/"
    "TGRSHP2025_TechDoc_Ch4.pdf"
)
CENSUS_BEDFORD_RETIREMENT = (
    "https://www.census.gov/programs-surveys/geography/technical-documentation/"
    "county-changes.2010.html"
)
CENSUS_SD_RECODE = (
    "https://www.census.gov/programs-surveys/geography/technical-documentation/"
    "county-changes.2010.html"
)


def retired_identifier_evidence(state_code: str, geoid: str, year: int) -> dict | None:
    """Known legal retirement dates, independent of CBP publication ranges.

    Checks use election years only where the change happened well before the
    presidential election. Nothing is mapped to a successor automatically.
    """
    if state_code == "VA" and geoid == "51515" and year >= 2016:
        return {
            "official_retirement_date": "2013-07-01",
            "evidence_url": CENSUS_BEDFORD_RETIREMENT,
            "former_kind": "independent_city_county_equivalent",
            "successor_county_geoid": "51019",
            "reason": "Bedford ceased to be an independent city on July 1, 2013",
        }
    if state_code == "SD" and geoid == "46113" and year >= 2016:
        return {
            "official_retirement_date": "2015-05-01",
            "evidence_url": CENSUS_SD_RECODE,
            "former_kind": "county",
            "successor_county_geoid": "46102",
            "reason": "Shannon County code retired with Oglala Lakota recoding May 1, 2015",
        }
    return None


def county_equivalent_name_match(
    state_code: str, geoid: str, source_label: str, census_name: str, year: int
) -> str | None:
    """Name match using a known county GEOID and Census entity type.

    A terminal 'city' may be dropped *only* from an authoritative independent
    city county-equivalent reference. The source code must already match that
    record. This does not equate a city and a surrounding county (Fairfax).
    """
    source = name_key(source_label)
    reference = name_key(census_name)
    display = census_name.split(",", 1)[0].strip()
    ref_is_city = bool(re.search(r"\s+city$", display, flags=re.I))
    ref_is_county = bool(re.search(r"\s+county$", display, flags=re.I))
    if state_code == "VA" and len(geoid) == 5 and geoid.startswith("51") and geoid[2:].isdigit():
        # The Census county-equivalent code category and the published type
        # must agree, even when stripping COUNTY would produce equal names.
        is_city_code = int(geoid[2:]) >= 500
        if (is_city_code and not ref_is_city) or (not is_city_code and ref_is_city):
            return None
    if ref_is_city and re.search(r"\s+county\s*$", source_label, flags=re.I):
        return None
    if not source or not reference:
        return None
    if source == reference:
        return "CENSUS_NAME_EXACT"
    # Restrict to Census independent city county equivalents. Virginia county
    # codes >= 500 can still be obsolete: retirement is independently checked.
    va_city = (
        state_code == "VA" and len(geoid) == 5 and geoid[:2] == "51"
        and geoid[2:].isdigit() and int(geoid[2:]) >= 500
    )
    other_city = (state_code, geoid) in {
        ("MD", "24510"), ("MO", "29510"), ("NV", "32510")
    }
    # Parse the original name, not merely name_key() output, to verify that
    # 'city' is the Census entity suffix and not part of a county name.
    if (va_city or other_city) and ref_is_city:
        basename = re.sub(r"\s+city$", "", display, flags=re.I)
        if source == name_key(basename) and not retired_identifier_evidence(state_code, geoid, year):
            return "CENSUS_INDEPENDENT_CITY_SUFFIX"
    return None
