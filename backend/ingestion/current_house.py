"""2026 voting House districts; source IDs are not historical geographic identities."""
from ingestion.current_results import (  # noqa: F401
    ResultsSourceError, download, manifest_entry, utc_timestamp, parse_contests,
)
from ingestion.medsl import STATE_FIPS

YEAR = 2026
ELECTION_DATE = "2026-11-03"
BASE_URL = f"https://www.callthemap.com/results/data/{YEAR}"
MANIFEST_URL = BASE_URL + "/manifest.json"
RESULTS_URL = BASE_URL + "/races.csv"
RULESET = "call-the-map-house-v1"
COVERAGE_KEY = "missing_districts"
# Census 2020 apportionment, Table 1. Counts apply to the 2026 election;
# these identifiers make no assertion that 2024 and 2026 boundaries coincide.
# https://www2.census.gov/programs-surveys/decennial/2020/data/apportionment/apportionment-2020-table01.pdf
DISTRICT_COUNTS = dict(
    AL=7, AK=1, AZ=9, AR=4, CA=52, CO=8, CT=5, DE=1, FL=28, GA=14,
    HI=2, ID=2, IL=17, IN=9, IA=4, KS=4, KY=6, LA=6, ME=2, MD=8,
    MA=9, MI=13, MN=8, MS=4, MO=8, MT=2, NE=3, NV=4, NH=2, NJ=12,
    NM=3, NY=26, NC=14, ND=1, OH=15, OK=5, OR=6, PA=17, RI=2, SC=7,
    SD=1, TN=9, TX=38, UT=4, VT=1, VA=11, WA=10, WV=2, WI=8, WY=1,
)
EXPECTED_CONTESTS = {
    f"{state}-{'AL' if count == 1 else f'{district:02d}'}": {
        "state_code": state, "district_code": "00" if count == 1 else f"{district:02d}",
    }
    for state, count in DISTRICT_COUNTS.items() for district in range(1, count + 1)
}
BOUNDARY_RACES = {STATE_FIPS[scope["state_code"]] + scope["district_code"]: identifier
                  for identifier, scope in EXPECTED_CONTESTS.items()}


def parse_results(raw: bytes, expected_rows: int) -> dict:
    result = parse_contests(raw, expected_rows, office="House",
                            expected_contests=EXPECTED_CONTESTS,
                            identifier_pattern="^(?:" + "|".join(DISTRICT_COUNTS) + ")-(?:AL|[0-9]{2})$",
                            allow_missing_votes=True)
    result[COVERAGE_KEY] = result.pop("missing_contests")
    return result
