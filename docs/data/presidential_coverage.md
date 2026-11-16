# Presidential results, 2000–2024

The backend reuses the existing MEDSL observations, geographic decisions and
canonical county publications. FEC state summaries use the existing separate
state-result tables. State and county results describe different reporting
levels and must never be added together.

Before this change, all seven MEDSL observation years were present; county
publications existed for 2000, 2004, 2008, 2012 and 2016, while FEC state totals
existed only for 2008. The 2024 House publication is unrelated to presidential
county coverage and is preserved.

## Sources and interpretation

The [pinned source catalog](../sources/presidential_state_returns.json) records
six official FEC workbook URLs, retrieval timestamps, SHA-256 checksums, exact
worksheet/header/column selections, explicit footnoted state labels and printed
national reference totals. These are linked from the FEC's
[election results index](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/).
The existing [2008 FEC authority publication](fec_state_authority_2008.md) retains
its original PDF, manifest, comparison, actor, identifiers and precedence policy.

Each new state summary has three source buckets: the two named major nominees
and `OTHER`. The latter represents all remaining reported votes, including
write-ins; it is not a candidate/person identity. For 2000–2020, these values
come from the FEC's presidential electoral/popular vote summary, not party-wide
congressional totals. For 2024, the parser sums every printed popular-vote
candidate column once and derives `OTHER` after checking the printed state total.
Electoral-vote columns, percentages and RCV later rounds are never added.
The source's 2020 `Trunp (R)` header typo is pinned literally. The source's
`DC*`, `ME*` and `NE*` labels have explicit year-specific mappings.

Preparation rejects changed headers, missing/duplicate states, invalid numeric
values, state sums and national sums. XLS extraction uses the existing optional
`xlrd` research dependency; XLSX uses the Python standard library and cached
numeric cell values. The runtime API needs neither Excel library nor network.
Source releases are unique by source/version/checksum. Publication binds the
entire prepared package and state-jurisdiction selection to a reviewed digest,
uses a scope lock and REPEATABLE READ transaction, and verifies persisted rows
against their immutable manifest. Replay returns `UNCHANGED` without new rows.

The migration `presidential_state_coverage` extends year/scope constraints,
retains historical immutability and state/contest/complete-publication triggers,
and adds year-specific candidate-bucket checks. New FEC summaries have **null**
MEDSL comparison/adjustment fields because a comparable source-wide comparison
has not been established. Null does not mean zero. The original 2008 comparison
fields remain required. Downgrade refuses to discard non-2008 state history.

## Coverage and API

`GET /api/v1/presidential-coverage` inventories exactly seven general elections.
Each item includes active MEDSL release/checksum, observed rows and source modes,
county publication status and source/reference IDs, excluded counts by state and
primary reason, missing county states, FEC state availability, and per-state
official votes minus published county votes. A missing county observation is
represented separately from a published zero. The signed difference combines
coverage gaps and source disagreements; it is **not** a county allocation or an
assertion that the accepted county data are independently verified.

Use the existing filtered discovery and results endpoints:

```text
/api/v1/elections?year=2024&office=U.S.%20President&stage=general
/api/v1/contests?year=2020&office=U.S.%20President&state_code=NY
/api/v1/results?year=2024&office=U.S.%20President&reporting_level=county
/api/v1/state-results?year=2024&office=U.S.%20President&state_code=NY
```

State items now include `election_id` and `election_date`, so unfiltered pages
across multiple years remain unambiguous. Pagination orders by election year
descending, state, source bucket and batch; every matching year's manifest is
validated, including requests beyond the last page. Party filters remain
unsupported for state source buckets. `/results` remains county/district grain;
state totals are served separately.

County publication retains the existing conservative `TOTAL`-only policy.
Neither null nor component modes become totals, and no duplicates are silently
removed. DATA-027 owns proof of additive complementary voting modes; DATA-028
owns the 2024 duplicates and total/missing-value anomalies; DATA-029 owns the
remaining 2008 authority/geographic coverage work. All seven county publications
remain `PARTIAL`. Historical reference vintages remain attached to each return;
new map boundary acquisition and the frontend election pages are separate tasks.

## Verified local publication, 2026-11-16

| Election | FEC state votes, 51 states/DC | Published county votes | County rows | County status |
| --- | ---: | ---: | ---: | --- |
| 2000 | 105,405,100 | 104,163,480 | 12,428 | PARTIAL |
| 2004 | 122,295,345 | 121,536,863 | 9,330 | PARTIAL |
| 2008 | 131,313,820 | 130,679,051 | 9,336 | PARTIAL |
| 2012 | 129,085,410 | 128,446,248 | 9,330 | PARTIAL |
| 2016 | 136,669,276 | 135,881,227 | 9,327 | PARTIAL |
| 2020 | 158,429,631 | 126,699,119 | 9,831 | PARTIAL |
| 2024 | 155,238,302 | 131,610,369 | 10,797 | PARTIAL |

The [seven-election inventory](presidential_coverage_inventory.csv) records
active source hashes, source/reference/publication IDs, exclusions and missing
county states. The [357-row state/county comparison](presidential_state_county_coverage.csv)
records exact signed differences and exclusions per state/year. Empty county
fields indicate no published county rows; they do not assert zero ballots.
The FEC summary values are the pinned publications' reported popular votes,
not all ballots cast or necessarily every write-in that states did not report.

The new county batches are `08061353-0903-439f-91a0-27385d46c1ed` (2020) and
`908d6723-0fbc-4183-8af7-f39dbc1e81b5` (2024). The 2020 batch excludes 12,262
observations: 12,034 unsupported modes and 228 unresolved geographies. The 2024
batch excludes 10,737: 8,693 unsupported modes, 1,522 duplicate-key observations,
237 unresolved geographies, 235 total mismatches, 46 incomplete reporting-unit
observations and four missing vote values. These are mutually exclusive primary
reasons; a source observation can have additional overlapping concerns. Counts
differ from older previews because existing published geographic heads advanced;
this work did not alter geography or expand source/mode eligibility.

Validation used Python 3.12 and PostgreSQL 18/PostGIS. The full backend run passed
378 tests with one optional archived FEC import test initially skipped; that
test was then run separately with both existing pinned ZIPs and passed. Thus all
379 collected tests were executed successfully across the two final runs.
All six FEC workbook extractions reproduced identical packages under Python 3.12.
Live HTTP checks verified all seven years: 51 discovered elections per year,
all 153 state buckets and exact state vote sums, plus first/last county pages,
county counts, election dates, reference vintages, nonadditive scopes and empty
unsupported modes. These checks did not exhaustively retrieve every county API
page; database materialization checks validate the full inserted row/vote counts.

A full 39,501,474-byte PostgreSQL custom-format backup was saved before migration.
Alembic upgrade and schema-drift checks passed. Every original row in 52 protected
tables remained identical; only the Alembic revision changed in the 53rd table.
The change added six state batches/918 returns, two county batches/20,628 returns,
22,999 explicit county issues, six source releases/runs and the necessary
election/contest/candidacy/term records. All old county/state publication pointers,
House data, geography, identities and source observations were preserved.
All eight identical publication replays returned `UNCHANGED`, with identical
whole-database row fingerprints before/after replay.

Detailed local receipts and evidence are under `data/presidential-coverage/`:
`before.json`, `review.json`, `publish-receipts.json`, `after.json`,
`replay-receipts.json`, `replay-after.json`, `http-smoke.json`, `full-tests.xml`
and `pinned-fec-replay-tests.xml`. They follow the repository's ignored-data
convention; the source catalog, inventory snapshots and reproduction commands
are tracked. The backup and raw workbooks also remain in that local directory.

## PowerShell reproduction

From the repository root, prepare the pinned official workbooks in a Python
environment with runtime plus optional research requirements installed. This
does not access the database; an upstream checksum change fails closed.

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python -m ingestion.presidential prepare --catalog .\docs\sources\presidential_state_returns.json --directory .\data\presidential-coverage --download
if ($LASTEXITCODE -ne 0) { throw 'FEC preparation failed' }
```

Apply the additive migration and audit published coverage:

```powershell
docker compose run --rm -v ./backend:/app api alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
docker compose run --rm -v ./backend:/app api alembic check
docker compose exec -T api python -m ingestion.presidential inventory --output /app/data/presidential-coverage/inventory-recheck.json
```

Preview one prepared state package, inspect its manifest/fingerprint, then
publish that exact projection. Repeat for 2000, 2004, 2012, 2016, 2020 and 2024;
retain the separate existing 2008 workflow.

```powershell
docker compose exec -T api python -m ingestion.presidential state --directory /app/data/presidential-coverage --year 2024 --output /app/data/presidential-coverage/state-preview.json
if ($LASTEXITCODE -ne 0) { throw 'State preview failed' }
$preview = Get-Content .\data\presidential-coverage\state-preview.json -Raw | ConvertFrom-Json
docker compose exec -T api python -m ingestion.presidential state --directory /app/data/presidential-coverage --year 2024 --publish --expected-fingerprint $preview.fingerprint --actor codex --authorization-note 'Implement DATA-030 and publish supported presidential results.' --output /app/data/presidential-coverage/state-replay.json
```

Preview/replay the supported county subsets using the existing command:

```powershell
docker compose exec -T api python -m ingestion.canonical_cli medsl --year 2020
docker compose exec -T api python -m ingestion.canonical_cli medsl --year 2020 --publish --allow-partial
docker compose exec -T api python -m ingestion.canonical_cli medsl --year 2024 --publish --allow-partial
Invoke-RestMethod 'http://localhost:8000/api/v1/presidential-coverage'
```

Tests require the existing development requirements in the execution environment
and a disposable database whose name ends in `_test`:

```powershell
docker compose run --rm -v ./backend:/app api python tests/run_candidate_tests.py --create-test-db -q tests
```

The runner creates only the guarded test database when absent; tests use isolated
schemas. The API image does not include pytest by default, so install
`requirements-dev.txt` in an isolated test environment first.
