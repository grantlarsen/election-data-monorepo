# Election discovery and published results

The [election map display API](election-map.md) reuses these publication and result
contracts for the 2008 state/county map, with a separate pinned boundary package.

The read-only API under `/api/v1` uses existing canonical election entities,
active county publications and the separate FEC state authority publication.
It does not materialize results or update source, identity, geography or
publication records. Presidential 2000–2024 coverage uses the additive
`presidential_state_coverage` migration; see the
[presidential source, coverage and replay guide](../data/presidential_coverage.md).
`GET /api/v1/presidential-coverage` provides all seven years, publication availability,
excluded county observations and explicit state-minus-county differences.
State-result items include election ID/date; `source_adjustment` is nullable when
no comparable MEDSL source-wide adjustment has been established.

| GET endpoint | Items |
| --- | --- |
| `/api/v1/elections` | Election events, including events with no published returns |
| `/api/v1/contests` | Office contests, including contests with no published returns |
| `/api/v1/results` | Candidate totals and separately labeled anonymous vote buckets at one reporting grain/mode |
| `/api/v1/state-results` | Verified FEC state candidate buckets for the seven 2000–2024 presidential general elections |

The full typed contract is available at `/docs` and `/openapi.json`.

## Filtering and pagination

All four endpoints accept `year`, `office`, `office_id`, `stage`, `state_code`,
`jurisdiction_id`, `election_id`, `contest_id`, `limit` and `offset`.
Filters combine with AND. UUID filters use canonical IDs.

- `year` is the calendar year of the election date, not its cycle or term.
- `office` matches an exact canonical office name or contest office name,
  ignoring case. Use `office_id` for an unambiguous identity.
- `stage` accepts `general`, `primary`, `runoff`, `special`, `special_primary`,
  `special_runoff` or `other`.
- `state_code` accepts the 50 states and DC, ignoring case.
- On discovery endpoints, `jurisdiction_id` matches the event/contest scope
  or a reporting unit with active published returns. On results endpoints it
  matches the exact reporting unit. To discover county returns within a state,
  use `state_code`; a state jurisdiction UUID does not aggregate counties.
- `/elections`, `/contests` and `/results` also accept `party_id`. This selects
  candidacies with that party affiliation or a ballot line for that party.
  The result retains the **whole candidate total**, including all fusion lines.
  It does not produce a party vote total or infer party from a source label.
  `nomination_party_id` is separately exposed on contests.
- `/state-results` rejects `party_id` with 422: its source buckets have no
  established canonical party/candidacy links. OTHER remains an aggregate.
- `/results` accepts `reporting_level` (default `county`) and `reporting_mode`
  (default `TOTAL`). Supported grain names also include `congressional_district`,
  `legislative_district`, `precinct` and `place`; data appears only when published.
  State authority is available at `/state-results`.

`limit` defaults to 50 and allows 1–200. `offset` defaults to zero. Every response
includes `items`, `total`, `limit`, `offset`, `has_more` and `availability`.
`total` counts all matching items before pagination. An offset beyond the last
page returns an empty `items` array while retaining the matching `total` and
`availability: "available"`.

Discovery sorts by election date descending, then event/contest UUID ascending.
County results sort by election date descending, contest UUID, reporting-unit
UUID, batch UUID and result key ascending. A candidate's result key is its
candidacy UUID; an anonymous bucket uses its immutable return UUID. State
results sort by election year descending, then state code, bucket label and
batch UUID ascending.

Counts, publication selection and page reads share a PostgreSQL repeatable-read,
read-only transaction. Across separate page requests, a publication may advance.
Clients requiring a consistent export should compare batch IDs and restart if
they change. There is no historical-batch query or cross-request snapshot token.

## Coverage and aggregation

Only current publication pointers supply votes. Superseded batches, raw
observations, legacy snapshots and ingestion previews never contribute votes.
Discovery shows an empty `publications` list for modeled events without votes.
No matching discovery data yields `availability: "no_matching_data"`; no
matching published results yields `"no_matching_published_results"`. These
states never create zero-vote candidate records. A stored zero remains zero.

Publication metadata includes source name, release UUID/version/checksum,
download URL, retrieval time, publication time, scope key, reporting levels and
modes. County publications also expose reference release, original batch input/
accepted/excluded counts, correction batch and correction source when present.
Those counts describe the **whole publication**, not the selected state,
candidate or page (`coverage_scope: "publication"`). PARTIAL remains PARTIAL
after filtering. `county_coverage_verified` remains false; the API does not
assert county-level independent verification.

Each county item includes its historical geographic reference and statistical
vintage, observation UUIDs and correction UUIDs. A reference vintage is not a
claim that a legal boundary was effective for that entire period. Candidate
votes use the existing aggregation service, summing distinct ballot lines once
and rejecting mixed candidate-total/ballot-line representations and duplicate
candidate totals. Different reporting units, modes, contests and batches remain
separate. Write-in and OTHER buckets retain their source labels and nullable
candidacy/person IDs; labels never create person matches. No national total,
share, margin, turnout or reconstructed geography is inferred.

State authority uses the existing manifest-verified accessor. State and county
figures are **non-additive** and may differ due to source corrections and
county coverage. Every results response exposes this explicitly. Unsupported
years/offices return empty pages without a county-derived fallback. The
[2024 House ingestion](../data/house_returns_2024.md) publishes source-scoped
district returns through these same endpoints. Request `year=2024`,
`office=U.S. House`, and `reporting_level=congressional_district` for results.
Its partial coverage, missing-vote contests and ranked-choice source conventions
are documented in that contract. House district geometry remains separate work.

The [Senate ingestion guide](../data/senate_returns.md) covers MEDSL 2000–2024
and January 2021 runoffs. Use `office=U.S. Senate` and `reporting_level=state`
on `/results`. `seat_class=1|2|3` filters election, contest and result discovery;
contests and canonical result items expose nullable `seat_class`. Senate candidate
profiles default to state reporting. `/state-results` retains its separate FEC
presidential authority semantics. Partial or withheld source counts and missing
historical elections are explicitly documented in the Senate guide.

Malformed or unknown query parameters return 422. Database failures and detected
published-result integrity failures return sanitized 503 responses. Existing
`/health` and `/health/db` behavior is preserved.

## Local verification (PowerShell)

With the existing Compose stack running and migrated:

```powershell
Invoke-RestMethod 'http://localhost:8000/api/v1/elections?year=2008&stage=general&limit=10'
Invoke-RestMethod 'http://localhost:8000/api/v1/contests?year=2008&state_code=NY'
Invoke-RestMethod 'http://localhost:8000/api/v1/results?year=2008&state_code=NY&limit=200'
Invoke-RestMethod 'http://localhost:8000/api/v1/state-results?year=2008&state_code=NY'
```

The API source is mounted by Compose and reloads automatically. On a fresh
database apply the existing migrations with `docker compose exec api alembic
upgrade head`; this does not populate results. No ingestion or publication run
is required for an already populated installation.

Tests use isolated schemas in a disposable database whose name must end in
`_test`. The HTTPX dependency is development-only. From `backend`, with
`TEST_DATABASE_URL` pointing to a disposable PostgreSQL database and `DB_*`
configured (or the existing test defaults):

```powershell
python -m pip install -r requirements-dev.txt -r requirements-research.txt
python -m pytest -q tests/test_election_api_contract.py tests/test_election_api.py
python -m pytest -q
```

Research dependencies are needed for existing PDF extraction regression tests.
PostgreSQL tests skip when `TEST_DATABASE_URL` is absent. API integration tests
apply the existing migration chain through head in each isolated schema.

Verified on 2026-11-15 with Python 3.12 and PostgreSQL 18: **238 tests passed,
zero failures or skips**, including 72 new HTTP contract tests. Positive district,
House, primary, runoff and special-result cases use explicitly synthetic fixtures.
The installed Starlette version emits one HTTPX test-client deprecation warning;
it does not affect the runtime API. The initial full-suite run required the
existing research extras for a PDF extraction test; the final run includes them.

Live read-only HTTP pagination reconciled all 9,336 active 2008 county items to
**130,679,051** votes (PARTIAL batch `5d21c419-327d-4327-8251-c7bdd672448e`) and
all 153 FEC state buckets to **131,313,820** votes (batch
`5fc06d5d-d58e-4ca4-93f5-62ed675b51f8`). Both health endpoints passed, and
unavailable 2024 House results returned an explicit empty page. No live source,
geography, identity, result or publication data was changed. Local verification
artifacts are `artifacts/election-api-full-tests.xml` and
`artifacts/election-api-live-smoke.json` (ignored by Git).

Implementation references: [FastAPI query parameter models](https://fastapi.tiangolo.com/tutorial/query-param-models/),
[FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/), and
[SQLAlchemy transaction isolation](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#setting-transaction-isolation-levels-dbapi-autocommit).
