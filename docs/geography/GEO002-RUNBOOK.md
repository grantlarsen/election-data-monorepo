# GEO-002 reproduction and publication runbook

Run from `C:\Users\Grant\Documents\election-data-monorepo`. Use existing Compose configuration without printing credentials. No project migration is required. Mount the complete current backend for disposable containers: the older API image does not contain the DATA-004 migration files. Initial image-only Alembic checks failed for that reason; the recorded current-source subprocess checks both exit 0.

## Fresh read-only reproduction

Choose an unused evidence directory for each run. Commands below intentionally refuse to overwrite an approval package or test output. Check each native process exit code before continuing.

```powershell
$geo002Backend = (Resolve-Path .\backend).Path
$geo002Output = '/app/data/geo002-replay'
docker compose exec -T api python -m app.services.data004_audit --baseline /app/data/data004/before.json --output "$geo002Output/before.json" --canonical-replay
if ($LASTEXITCODE -ne 0) { throw 'Baseline failed' }
docker compose exec -T api python -m app.services.geo001_audit before --output-dir $geo002Output
if ($LASTEXITCODE -ne 0) { throw 'Inventory failed' }
docker compose exec -T api python -m app.services.geo001_audit sources --output-dir $geo002Output
if ($LASTEXITCODE -ne 0) { throw 'Source integrity failed' }
docker compose exec -T api python -m app.services.data004_reconcile --baseline "$geo002Output/before.json" --output-dir "$geo002Output/reproduced"
if ($LASTEXITCODE -ne 0) { throw 'Comparison failed' }
docker compose exec -T api python -m app.services.geo001_audit verify --output-dir $geo002Output --archive-dir /app/data/geo001/corrected/reproduced
if ($LASTEXITCODE -ne 0) { throw 'Independent verification failed' }
docker compose exec -T api python -m app.services.geo002_review --output-dir $geo002Output
if ($LASTEXITCODE -ne 0) { throw 'Review preparation failed' }
docker compose exec -T api python -m app.services.geo002_validate cli --output-dir $geo002Output
if ($LASTEXITCODE -ne 0) { throw 'CLI replay failed' }
docker compose run --rm --no-deps --volume "${geo002Backend}:/app" api python -m app.services.geo002_validate schema --output-dir $geo002Output
if ($LASTEXITCODE -ne 0) { throw 'Schema check failed' }
docker compose run --rm --no-deps --volume "${geo002Backend}:/app" -e GEO002_TEST_OUTPUT=/app/data/geo002-replay/tests api python tests/run_geo002_tests.py
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
docker compose exec -T api python -m app.services.data004_audit --baseline "$geo002Output/before.json" --output "$geo002Output/after.json" --canonical-replay
if ($LASTEXITCODE -ne 0) { throw 'Canonical preservation failed' }
docker compose exec -T api python -m app.services.geo001_audit after --output-dir $geo002Output
if ($LASTEXITCODE -ne 0) { throw 'Full preservation failed' }
```

`geo001_audit after` intentionally requires zero live changes and is suitable **before** publication. It is not a post-publication success test: geographic append-only publication legitimately changes decision/context/reporting-unit tables, and a fresh canonical plan may also differ. Post-publication verification must preserve old canonical records and pointers rather than expect the new plan's fingerprint to equal the old batch.

## Exact publication, only after signoff

No command in this section was run against the project database. Substitute only the actor explicitly supplied in the approval. The approved manifest list and SHA values are in `data/geo002/approval-manifest.json`. Do not use full-vintage approval digests to authorize these subsets.

For each explicitly approved routine vintage, use this pattern (example: vintage 2000):

```powershell
$geo002Actor = '<accountable actor from explicit signoff>'
$geo002ApprovedSha = '9fd8701c319372562c44ca7fb3a22e737bfcc8c47dc922ba5aa6788bb7f9396b'
docker compose exec -T -e INGESTION_DATA_DIR=/app/data/geo002/publication api python -m ingestion geo resolve --vintage 2000 --context-file /app/data/geo002/reproduced/compare-2000.json --publication-manifest /app/data/geo002/approvals/routine-2000.json --publish --approve-changes --actor $geo002Actor --expected-proposal-sha256 $geo002ApprovedSha
if ($LASTEXITCODE -ne 0) { throw 'Publication failed; inspect before retrying' }
# Repeat the identical command to prove zero inserts; retain both JSON reports.
```

Only a separate approval of `approvals/bedford-2012.json` permits its three downgrades. Use `--vintage 2012`, that exact manifest, the corresponding context file and SHA `75ebbee8c38a213647e9efd58c79850f3e2281bcc8b7460d7a761feb747a50d7`, adding **`--allow-downgrades`**. No jurisdiction reassignment flag or canonical command belongs to either approval scope.

After each publication, reconcile selected observation IDs, exact predecessor links, actor, complete stored payloads, context and subset audit SHA against the approved envelope. Verify every held/unselected head remains unchanged; preserve immutable old rows. Inventory any newly inserted reporting units against selected classifications only. Repeat the same publication to establish zero new decisions/reporting units/contexts. Save both process results and database audits. Compare source votes and all unrelated/reference/identity/canonical tables to the fresh baseline, allowing only the explicitly expected append-only geography additions. Do not mark GEO-002 Done until this live evidence exists.

## Research and evidence package

```powershell
Copy-Item -LiteralPath docs/geography/GEO002-sources.json -Destination data/geo002-replay/research-requests.json
docker compose exec -T api python -m app.services.geo001_research /app/data/geo002-replay/research-requests.json --output-dir /app/data/geo002-replay/research
docker compose run --rm --no-deps --volume "${geo002Backend}:/app" api python -m app.services.geo001_research /app/data/geo002-replay/research-requests.json --output-dir /app/data/geo002-replay/research --extract-only
```

Research transport completion is not source validation: retain the four Alaska 404s and the MEDSL HTTP 202/empty response as failures of evidence acquisition. Do not modify released records to repair encoding. The original source files are read-only inputs and are not reimported.

The delivered package was validated and built on the host with:

```powershell
.\.venv\Scripts\python.exe backend/app/services/geo002_package.py
```

The packager requires the fixed `data/geo002/` delivery, all passing checks and a previously unused `artifacts/geo002/` directory. It verifies original artifact checksums and every archived GEO-001 evidence file, independently hashes the selective manifests, updates only the GEO-002 backlog row, and creates separate patch/evidence ZIPs with inner and outer checksum manifests. It does not access the database. Use the fresh-run commands above for further verification; do not overwrite the delivered packages.
