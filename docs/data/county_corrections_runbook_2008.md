# published county corrections — PowerShell

The 283 amendments are already published. Their immutable review digest is
`596801cc989380199a7511b305c480f6aaa27b838b815102658d0eaa8432c9e5`;
publication digest is
`5d715d6e079ea6dfccfee7eeabe8ac9ad1540a442c26e5f2e6fe0e4089d05e0c`.
The active canonical batch is `5d21c419-327d-4327-8251-c7bdd672448e`.

Use fresh output filenames. The CLI refuses to replace evidence files.
Do not overwrite `protected-before.json`, `snapshot-before.json`, the original
proposal, released source archives or existing delivery packages.

```powershell
Set-Location C:\Users\Grant\Documents\election-data-monorepo
$d005RepoRoot = (Get-Location).Path
$d005BackendRoot = (Resolve-Path .\backend).Path
```

The live schema is at `d005county01`. The recorded upgrade/current/check all
passed. Verify its current state with:

```powershell
docker compose run --rm --no-deps --volume "${d005BackendRoot}:/app" api alembic current
docker compose run --rm --no-deps --volume "${d005BackendRoot}:/app" api alembic check
```

A fresh preview reads official evidence and transcriptions, verifies all required
checksums and the fixed 283-row digest, and checks the live source/geographic
projection. Preview is read-only:

```powershell
docker compose run --rm --no-deps --volume "${d005RepoRoot}:/workspace:ro" api `
  python -B -m app.services.county_correction_cli preview `
  --output /app/data/data005-county-apply/preview-recheck.json
```

The expected preview has 283 amendments, +89,944 votes, 9,336 accepted rows,
138 exclusions, 130,679,051 votes and PARTIAL status. It includes six previously
resolved Virginia observations (42,756 votes), separately from the correction
delta. It advances 117 existing lineage references to already-published heads;
it does not publish new geographic decisions.

The user authorized these corrections. Repeating their publication must return
UNCHANGED with the same batch and no new history:

```powershell
$d005Preview = Get-Content data/data005-county-apply/preview-recheck.json -Raw | ConvertFrom-Json
docker compose run --rm --no-deps --volume "${d005RepoRoot}:/workspace:ro" api `
  python -B -m app.services.county_correction_cli publish --actor codex `
  --expected-fingerprint $d005Preview.fingerprint `
  --output /app/data/data005-county-apply/replay-recheck.json
```

Never reuse the digest to authorize different proposals. A changed source,
review digest, geographic projection or canonical baseline fails closed and
requires a newly reviewed scope. Existing corrections are discovered through
the active canonical publication; the standard publisher also retains them:

```powershell
docker compose run --rm --no-deps api python -B -m ingestion.canonical_cli `
  medsl --year 2008 --publish --allow-partial
```

Audit the exact changed IDs/votes, expected additions, old history and unrelated
years using the frozen pre-publication baseline:

```powershell
docker compose run --rm --no-deps --volume "${d005RepoRoot}:/workspace:ro" api `
  python -B -m app.services.county_correction_cli verify `
  --output /app/data/data005-county-apply/verification-recheck.json
```

The recorded dedicated replay, standard canonical replay and FEC replay all
returned UNCHANGED. `post-publication/full-preservation.json` proves all 42 public
tables stayed identical across replay. FEC retains its original historical
MEDSL comparison and batch `5fc06d5d-d58e-4ca4-93f5-62ed675b51f8`, rather than
creating a new state publication when county comparison values change.

Re-run tests against current source in the isolated `DB_NAME + '_test'` database:

```powershell
docker compose run --rm --no-deps --volume "${d005BackendRoot}:/app" `
  -e PYTHONDONTWRITEBYTECODE=1 `
  -e GEO002_TEST_OUTPUT=/app/data/data005-county-apply/tests-recheck `
  api python -B tests/run_county2008_tests.py --install-research
if ($LASTEXITCODE -ne 0) { throw 'Regression suite failed' }
```

The release run passed 165 tests, zero failures/errors/skips. Recorded tests and
implementation hashes are in `tests-release/`. Publication evidence, the
old/new-value export `applied-283.csv`, schema proof, replay evidence and backlog
update are under `data/data005-county-apply/`. Checked source/evidence packages
are under `artifacts/data005-county-apply/`.

Remaining evidence/coverage work is [DATA-029](county_verification_followup_2008.md). The correction rollout
is complete; the county dataset and broader DATA-005 acceptance remain partial.
