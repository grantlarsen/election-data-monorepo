"""2026 state gubernatorial general-election scope over the shared validator."""
from ingestion.current_results import (  # noqa: F401
    ResultsSourceError, download, manifest_entry, utc_timestamp, parse_contests,
)

YEAR = 2026
ELECTION_DATE = "2026-11-03"
BASE_URL = f"https://www.callthemap.com/results/data/{YEAR}"
MANIFEST_URL = BASE_URL + "/manifest.json"
RESULTS_URL = BASE_URL + "/races.csv"
RULESET = "call-the-map-governor-v1"
COVERAGE_KEY = "missing_states"
# NGA lists 36 states and three territories. The feed covers the states only.
# https://www.nga.org/governors/elections/
EXPECTED_STATES = frozenset("AK AL AR AZ CA CO CT FL GA HI IA ID IL KS MA MD ME MI MN NE NH NM NV NY OH OK OR PA RI SC SD TN TX VT WI WY".split())
EXPECTED_CONTESTS = {f"GOV-{state}": {"state_code": state} for state in EXPECTED_STATES}


def parse_results(raw: bytes, expected_rows: int) -> dict:
    result = parse_contests(raw, expected_rows, office="Governor",
                            expected_contests=EXPECTED_CONTESTS, identifier_pattern="^GOV-",
                            allow_missing_votes=True)
    result[COVERAGE_KEY] = [identifier.removeprefix("GOV-") for identifier in result.pop("missing_contests")]
    return result
