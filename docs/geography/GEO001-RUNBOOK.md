# GEO-001 reproduction and evidence integrity

Run from `C:\Users\Grant\Documents\election-data-monorepo`. Use existing Compose credentials without displaying them. Project commands below are read-only; no live upgrade/downgrade, alias approval, change verification or publication is necessary. Tests create/use only `DB_NAME + '_test'` and their isolated schemas. All tabular audit operations use Polars.

## Delivered evidence

`data/geo001/` is separate from the preserved DATA-004 evidence. `before.json` and `after.json` compare the original DATA-004 columns and replay canonical batches; `full-before.json` / `full-after.json` and `full-preservation.json` cover every column of all 37 public tables. The original artifact checksums are verified in `original-artifact-checks.json`. Do not overwrite DATA-004's before.json.

Original step6.2.0 comparisons/context replays are in `reproduced/` and `independent-verification.json`. Current step6.2.1 reports/replays are in `corrected/reproduced/` and `corrected/independent-verification.json`. `all-observation-checks.csv` in each directory checks all 94,151 UUIDs; `review-ledger.csv` selects all changed/exception/additional-concern observations. `independent-digest-checks.json` independently hashes both sets of contexts/proposals. Source bytes/checksums are in `source-integrity.json`; public research downloads and failures have a separate `research/retrievals.json` manifest. HTTP success alone is not source validation: attempted/unrelated pages and the Federal Register access response are not relied on; the Census changes page corroborates CT. The scanned CT 2008 PDF yielded no usable extracted vote table.

The original algorithm replay was executed before the ruleset changed. To reproduce it again, use source commit `0cfffcf`, rather than modifying the old context's ruleset to pass the new resolver's guard. This guard intentionally requires the recorded version.

## Reproduce into a fresh directory

The following commands illustrate a fresh run named `geo001-replay`. Use a new name for subsequent runs. Extracting the old backend changes no working-tree source or database records.

```powershell
$geo001Repo = (Get-Location).Path
$geo001Backend = (Resolve-Path .\backend).Path
$geo001Run = Join-Path $geo001Repo 'data/geo001-replay'
New-Item -ItemType Directory -Path $geo001Run | Out-Null
git archive --format=zip --output=data/geo001-replay/baseline.zip 0cfffcf backend
Expand-Archive -LiteralPath data/geo001-replay/baseline.zip -DestinationPath data/geo001-replay/baseline
$geo001Old = (Resolve-Path data/geo001-replay/baseline/backend).Path
# Add only the new read-only audit helper to the isolated old source tree.
Copy-Item -LiteralPath backend/app/services/geo001_audit.py -Destination data/geo001-replay/baseline/backend/app/services/geo001_audit.py

# Establish the current baseline; read-only and no project migrations.
docker compose exec -T api python -m app.services.data004_audit --baseline /app/data/data004/before.json --output /app/data/geo001-replay/before.json --canonical-replay
docker compose exec -T api python -m app.services.geo001_audit before --output-dir /app/data/geo001-replay
docker compose exec -T api python -m app.services.geo001_audit sources --output-dir /app/data/geo001-replay

# Explicit child mounts override Compose's ordinary app/ingestion mounts.
docker compose run --rm --no-deps --volume "${geo001Old}:/app" --volume "${geo001Old}/app:/app/app:ro" --volume "${geo001Old}/ingestion:/app/ingestion:ro" api python -m app.services.data004_reconcile --baseline /app/data/geo001-replay/before.json --output-dir /app/data/geo001-replay/reproduced
docker compose run --rm --no-deps --volume "${geo001Old}:/app" --volume "${geo001Old}/app:/app/app:ro" --volume "${geo001Old}/ingestion:/app/ingestion:ro" api python -m app.services.geo001_audit verify --output-dir /app/data/geo001-replay

# Corrected current rules; no reference/source/decision/publication writes.
docker compose exec -T api python -m app.services.data004_reconcile --baseline /app/data/geo001-replay/before.json --output-dir /app/data/geo001-replay/corrected/reproduced
docker compose exec -T api python -m app.services.geo001_audit verify --output-dir /app/data/geo001-replay/corrected --archive-dir /app/data/geo001-replay/corrected/reproduced
docker compose exec -T api python -m app.services.geo001_review --output-dir /app/data/geo001-replay

docker compose exec -T api python -m app.services.data004_audit --baseline /app/data/data004/before.json --output /app/data/geo001-replay/after.json --canonical-replay
docker compose exec -T api python -m app.services.geo001_audit after --output-dir /app/data/geo001-replay
```

Old contexts bind source/year release IDs and observation-input digests. Frozen replay survives changes to active selectors/newer references as exercised in the PostgreSQL tests. A changed input observation or mismatched archive SHA must fail. New context/proposal digests are review inputs; none is a publication approval.

## Executed current checks

```powershell
# Test launcher installs pytest only in its disposable container if needed.
# It writes data/geo001/pytest.xml. Preserve delivered logs before another run.
$geo001Backend = (Resolve-Path .\backend).Path
docker compose run --rm --no-deps --volume "${geo001Backend}:/app" api python tests/run_geo001_tests.py
docker compose run --rm --no-deps --volume "${geo001Backend}:/app" -e 'PGOPTIONS=-c default_transaction_read_only=on' api alembic current
docker compose run --rm --no-deps --volume "${geo001Backend}:/app" -e 'PGOPTIONS=-c default_transaction_read_only=on' api alembic check

# INGESTION_DATA_DIR controls CLI JSON reports; --output controls review CSVs.
foreach ($geo001Vintage in 2000,2004,2012,2020,2024) {
    docker compose exec -T -e INGESTION_DATA_DIR=/app/data/geo001/cli api python -m ingestion geo compare --vintage $geo001Vintage --context-file "/app/data/geo001/corrected/reproduced/compare-$geo001Vintage.json" --output "/app/data/geo001/cli/review-$geo001Vintage.csv"
    if ($LASTEXITCODE -ne 0) { throw 'CLI replay failed' }
}
```

Executed final suite: 113 passed, zero skipped. Alembic current: d004a9c21e70 (head); check: no new upgrade operations. Five current CLI replays match their corrected preview/context/proposal digests with zero inserts and published=false (`cli-replays.json`). During this delivery the CLI was first invoked with `DATA_DIR`; its five newly generated JSONs landed in the default directory and were moved by exact UUID filenames into `data/geo001/cli/geography/`. The command above uses the correct `INGESTION_DATA_DIR` variable. No pre-existing report was moved or changed.

## Research and packaging

```powershell
Copy-Item -LiteralPath docs/geography/GEO001-sources.json -Destination data/geo001/research-requests.json
docker compose exec -T api python -m app.services.geo001_research /app/data/geo001/research-requests.json
docker compose run --rm --no-deps --volume "${geo001Backend}:/app" api python -m app.services.geo001_research /app/data/geo001/research-requests.json --extract-only

# Standard-library packaging; refuses incomplete preservation/tests/replay checks.
# Updates only the single GEO-001 backlog row and writes separate artifacts.
.\.venv\Scripts\python.exe backend/app/services/geo001_package.py
Get-FileHash artifacts/geo001/GEO-001-patch.zip -Algorithm SHA256
Get-FileHash artifacts/geo001/GEO-001-evidence.zip -Algorithm SHA256
```

`GEO-001-patch.zip` contains only changed source/tests/docs, the GEO-001 backlog update, .gitignore and its file-level SHA-256 manifest. `GEO-001-evidence.zip` preserves `data/geo001/` paths and its internal checksum list. `artifacts/geo001/SHA256SUMS.txt` hashes both ZIPs and the external patch manifest. ZIP CRCs and file checksums are verified during packaging. Existing raw source archives are not duplicated; their release IDs, paths and whole-file checksums are recorded. Credentials, environments, Docker volumes and original DATA-004 packages are excluded from the new archives.
