"""2026 Senate source scope over the shared provisional-results validator."""
from ingestion.current_results import (  # noqa: F401
    REQUIRED, ResultsSourceError, download, manifest_entry, public_url, utc_timestamp, parse_contests,
)

SenateSourceError = ResultsSourceError
YEAR = 2026
ELECTION_DATE = "2026-11-03"
BASE_URL = f"https://www.callthemap.com/results/data/{YEAR}"
MANIFEST_URL = BASE_URL + "/manifest.json"
RESULTS_URL = BASE_URL + "/races.csv"
RULESET = "call-the-map-senate-v1"
# Official calendar: https://www.fec.gov/resources/cms-content/documents/2026pdates.pdf
# Class II: https://www.senate.gov/senators/Class_II.htm
REGULAR_STATES = frozenset("AK AL AR CO DE GA IA ID IL KS KY LA MA ME MI MN MS MT NC NE NH NJ NM OK OR RI SC SD TN TX VA WV WY".split())
SPECIAL_STATES = frozenset({"FL", "OH"})
EXPECTED_STATES = REGULAR_STATES | SPECIAL_STATES

EXPECTED_CONTESTS = {f"SEN-{state}": {"state_code": state,
    "seat_class": 3 if state in SPECIAL_STATES else 2, "special": state in SPECIAL_STATES}
    for state in EXPECTED_STATES}
COVERAGE_KEY = "missing_states"


def parse_results(raw: bytes, expected_rows: int) -> dict:
    result = parse_contests(raw, expected_rows, office="Senate",
                            expected_contests=EXPECTED_CONTESTS, identifier_pattern="^SEN-")
    result[COVERAGE_KEY] = [identifier.removeprefix("SEN-") for identifier in result.pop("missing_contests")]
    return result
