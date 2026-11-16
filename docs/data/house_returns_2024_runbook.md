# 2024 House ingestion runbook

Run these PowerShell commands from the repository root. Compose supplies database
configuration; credentials never need to be copied into command arguments.

```powershell
docker compose up -d db
docker compose run --rm --no-deps -v ./backend:/app api alembic upgrade head
docker compose exec -T api python -m ingestion run medsl_house --years 2024 --validate-only
docker compose exec -T api python -m ingestion run census_congressional_districts --vintage 2024 --validate-only
```

The MEDSL download uses the existing Dataverse guestbook response configuration
(`DATAVERSE_GUESTBOOK_RESPONSE_FILE`, or `data/ingestion/guestbook_response.json`
inside the container). Use truthful user-provided responses. Raw files are cached
under `data/ingestion/raw/<source>/<version>/`; hashes are checked on every reuse.

For a pinned replay, archive the official metadata response and require the exact
original-file hash. A validated cached original and archived metadata allow an
offline replay; absent cached bytes, acquisition still needs the upstream server.
An unpinned normal run checks the latest released metadata.

```powershell
New-Item -ItemType Directory -Force ./data/house-returns | Out-Null
Invoke-WebRequest -Uri 'https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/IG0UN2' -OutFile ./data/house-returns/metadata.json
$sourceHash = '76eec42483ee9f0fc5cf6e377442c783d1ae6eefa929729fd6561a69bab47f2a'
docker compose exec -T api python -m ingestion run medsl_house --years 2024 --source-metadata-file data/house-returns/metadata.json --expected-sha256 $sourceHash --validate-only
```

The documented hash refers to V15.0. Keep that metadata file with its cached
original. A different hash fails before loading observations; review a newer
release deliberately rather than substituting its hash silently.

Load, preview, and publish the reviewed partial coverage:

```powershell
docker compose exec -T api python -m ingestion run medsl_house --years 2024 --source-metadata-file data/house-returns/metadata.json --expected-sha256 $sourceHash
docker compose exec -T api python -m ingestion run census_congressional_districts --vintage 2024
docker compose exec -T api python -m ingestion.house --output data/house-returns/preview.json
Get-Content ./data/house-returns/preview.json
docker compose exec -T api python -m ingestion.house --publish --allow-partial --output data/house-returns/publication.json
docker compose exec -T api python -m ingestion.house --publish --allow-partial --output data/house-returns/repeated-publication.json
```

The second materialization must report `UNCHANGED`, reuse the batch UUID and leave
the pointer timestamp intact. Rerunning the observation loader must report zero
inserted, 1,353 already present and zero active-year switches for this snapshot.
`records_updated` retains the existing shared loader's meaning: replacement-release
active rows, rather than SQL updates to immutable observations. Raw unselected
rows are counted as `records_excluded` in the ingestion JSON report.

If multiple Census releases have the same version, pass their explicit UUID with
`--reference-release-id`; the publisher refuses an ambiguous reference selection.
Reference file hashes are captured in every preview/publication fingerprint.

The additive revision creates only `house_return_detail` and
`house_district_reconciliation`. Source ingestion and canonical publication use
separate transactions: a new raw active release becomes visible to result clients
only after successful canonical publication. Publication failures preserve the
previous result pointer. Partial publication requires the explicit flag above.

## Verification

```powershell
$results = Invoke-RestMethod 'http://localhost:8000/api/v1/results?year=2024&office=U.S.%20House&reporting_level=congressional_district&state_code=NY&limit=200'
$results.total
$results.items | Select-Object label, votes, basis
Invoke-RestMethod 'http://localhost:8000/api/v1/contests?year=2024&office=U.S.%20House&state_code=FL&limit=200'
```

Use the API's `has_more`, `offset` and `limit` fields when checking every result;
its maximum page size is 200. Fusion party filtering retains the whole candidate
total under the existing API contract. County defaults remain unchanged: request
`reporting_level=congressional_district` explicitly for House results.

Useful SQL (run through your normal database client):

```sql
SELECT b.status, b.input_rows, b.accepted_rows, b.excluded_rows, b.canonical_votes
FROM canonical_publication p JOIN canonical_result_batch b ON b.id=p.batch_id
WHERE p.scope_key='medsl_house:2024:district_total';

SELECT r.geoid, r.status, r.reported_total, r.canonical_votes, r.checks_json
FROM house_district_reconciliation r JOIN canonical_publication p ON p.batch_id=r.batch_id
WHERE p.scope_key='medsl_house:2024:district_total' ORDER BY r.geoid;

SELECT i.code, count(*) FROM canonical_materialization_issue i
JOIN canonical_publication p ON p.batch_id=i.batch_id
WHERE p.scope_key='medsl_house:2024:district_total' GROUP BY i.code;
```

Tests create isolated schemas in `DB_NAME + '_test'`, never in the application
database. This command installs optional test/research libraries only in the
disposable container and runs the full suite:

```powershell
$testOutput = '/app/data/house-returns/tests-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
docker compose run --rm --no-deps -v ./backend:/app -e GEO002_TEST_OUTPUT=$testOutput api sh -c 'python -m pip install -q --root-user-action=ignore -r requirements-dev.txt -r requirements-research.txt && python tests/run_county2008_tests.py tests --tb=short'
```

For focused checks, replace the final `tests` argument with
`tests/test_house_returns.py tests/test_house_returns_postgres.py`.
Coverage includes missing data, invalid numeric/boolean/geographic values, fusion,
write-ins, source selection, pinned offline replay/hash failure, district totals,
migration constraints, atomic rollback, idempotency, supersession/reactivation,
and the existing HTTP results interface. It does not establish certified
all-district accuracy or supply district map shapes.
