# DATA-004 PowerShell / Docker runbook

Run from `C:\Users\Grant\Documents\election-data-monorepo`. Commands use existing Compose DB_* credentials inside containers and do not print secrets. The API image contains runtime dependencies; tests install pytest only in a disposable container. No running service restart or rebuild is required when using the explicit backend mount below.

## Apply and verify

The migration **has already been applied** in this workspace. Current head: `d004a9c21e70`. On another checkout, apply the minimal patch first; its prerequisite head is `d003f93a1700`.

```powershell
Set-Location -LiteralPath 'C:\Users\Grant\Documents\election-data-monorepo'
$data004Backend = (Resolve-Path .\backend).Path
docker compose ps

# Capture BEFORE applying the migration. Choose a fresh evidence directory for another run.
docker compose exec -T api python -m app.services.data004_audit --output /app/data/data004/before.json

# All tests write to isolated schemas in DB_NAME + '_test', never the project database.
docker compose run --rm --no-deps --volume "${data004Backend}:/app" api sh -c 'pip install --disable-pip-version-check --root-user-action=ignore "pytest>=8,<10" && python tests/run_data004_tests.py --create-test-db'

# Migrations are copied into the image normally; this mount runs the actual patched files.
docker compose run --rm --no-deps --volume "${data004Backend}:/app" api alembic upgrade head
docker compose run --rm --no-deps --volume "${data004Backend}:/app" api alembic current
docker compose run --rm --no-deps --volume "${data004Backend}:/app" api alembic check

# Read-only comparison and DATA-003 compatibility checks.
docker compose exec -T api python -m app.services.data004_audit --baseline /app/data/data004/before.json --output /app/data/data004/after.json --canonical-replay
docker compose exec -T api python -m app.services.data004_reconcile --baseline /app/data/data004/before.json --output-dir /app/data/data004
```

Expected: 106 tests pass with no skips; Alembic reports no new upgrade operations; all 29 original preservation comparisons are true; five canonical replay entries match publication. The two new project tables remain empty because no boundaries or geographic decisions are published by these commands. Test schemas are dropped automatically; the disposable test database/extension may remain for reuse.

The SQL migration is `backend/migrations/versions/d004a9c21e70_versioned_geography.py`. PostgreSQL creates the trusted `btree_gist` extension in `public` if needed. UUID GiST operator classes are schema-qualified so test schemas need not expose `public` in their search path. DDL and constraints execute transactionally; data are not backfilled or rewritten.

## Replay a geographic preview

```powershell
# Reuse the exact inputs archived by the five-vintage comparison.
docker compose exec -T api python -m ingestion geo compare --vintage 2000 --context-file data/data004/compare-2000.json --output data/data004/replay-2000.csv
```

The CLI writes a new `data/ingestion/geography/resolution-*.json` report, including the context and proposal digests. The same archived inputs must produce the same proposal/context digest while current decision heads are unchanged. The proposal fingerprint describes the diff against current heads; after a legitimate publication that diff can become empty even though decision inputs/outcomes reproduce. A persisted context can instead be selected by `--context-sha256 <digest>`. No project contexts have been inserted by this delivery, so that option currently applies to future approved publications.

GEO-001/002 must examine `compare-*.json` and `preview_review.csv` before publication. This runbook supplies no publish/approve command with fabricated reviewer approval. Use the existing reviewed publication workflow with a real actor, exact preview digest and separate downgrade/reassignment authorizations where warranted. Any canonical supersession is a separate explicit operation.

## Guarded rollback

The new migration's downgrade was executed and re-upgraded on populated isolated PostgreSQL fixtures, preserving observations, identifiers, identities, canonical rows and fingerprints. It was also tested to reject dropping populated new history. A live downgrade was not needed or executed.

Before any rollback, stop writers and capture an audit/backup appropriate to the environment. On a database where DATA-004's added structures contain no new facts, the exact command is:

```powershell
docker compose run --rm --no-deps --volume "${data004Backend}:/app" api alembic downgrade d003f93a1700
```

It refuses rollback when boundary rows, district references, contexts or new dated-evidence fields would be discarded. Resolve a refusal through explicit history preservation/backup handling; do not delete the history to force a downgrade. The shared `btree_gist` extension remains. Reapply with `alembic upgrade head`; do not downgrade past the older Step 6.1 migration, which explicitly disallows destructive downgrade.

## Patch and evidence integrity

The minimal ZIP preserves repository-relative source paths. Its embedded `DATA-004-patch-manifest.json` lists each changed file and SHA-256. The evidence ZIP preserves `data/data004/` paths and includes `SHA256SUMS.txt`. It excludes raw source downloads, credentials, virtual environments, Docker volumes and the user's pre-existing backlog file.

To inspect the ZIPs without applying them:

```powershell
Get-FileHash .\artifacts\data004\DATA-004-patch.zip -Algorithm SHA256
Get-FileHash .\artifacts\data004\DATA-004-evidence.zip -Algorithm SHA256
```
