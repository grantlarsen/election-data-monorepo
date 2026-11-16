# reproduction runbook

The follow-up [FEC authority publication](fec_state_authority_2008.md) is now authoritative
for 2008 state totals and resolves the original 45 source discrepancies. The
commands below reproduce the initial MEDSL comparison and county proposal;
that historical evidence intentionally retains its original mismatches. Use the
linked follow-up for current state results and publication verification.

Run in PowerShell at `C:\Users\Grant\Documents\election-data-monorepo`.
Use unused output directories. Do not print `.env` or reset the database/volumes.
No migration or reimport of MEDSL is needed.

## Reproduce from the delivered evidence, offline

The host's project virtual environment already contains the normal dependencies.
Reconciliation uses the extracted evidence and does not require pypdf or a DB
connection. Preserve the delivered `data/data005/final/` unchanged.

```powershell
$env:PYTHONPATH = 'backend'
$env:PYTHONDONTWRITEBYTECODE = '1'
$d005Replay = 'data/data005/replay'
if (Test-Path -LiteralPath $d005Replay) { throw 'Choose a fresh output directory' }
.\.venv\Scripts\python.exe -m app.services.presidential_returns_reconciliation --snapshot data/data005/snapshot.json --handoff data/geo001/data005-144-handoff.csv --evidence-dir data/data005/evidence --geo-dir data/geo002 --mn-evidence-dir data/data005/mn-additional --mn-lookup docs/sources/minnesota_county_lookup_2008.csv --output-dir $d005Replay
if ($LASTEXITCODE -ne 0) { throw 'Reconciliation execution failed' }
```

Exit 0 means the report was built, **not that the dataset reconciles**. Inspect
`summary.json`, `state-comparisons.csv`, `unit-comparisons.csv`,
`official-source-comparisons.csv`, and `original-144-dispositions.csv`.
For a completeness gate, append `--require-complete` and choose another unused
output directory: the current evidence intentionally returns **exit 2** after
writing reports because DATA-005 is incomplete. Structural/source integrity
errors also fail, with a traceback; do not reinterpret them as a vote mismatch.

Reproducing the delivered snapshot/evidence yields the same review SHA and CSVs;
only `summary.json`'s generation timestamp changes. The original-144 check is
bound to the original stored batch; if a canonical supersession has since been
approved and published, retain this snapshot as the original baseline and
explicitly review/rebaseline the comparison rather than silently changing it.

## Fresh live read-only checks

The original `data/data005/` inventory is immutable delivery evidence. Use a new
directory for fresh live checks and reports. Mount the complete current backend
for commands needing tests/migrations: the old API image omits recent files.

```powershell
$d005Backend = (Resolve-Path .\backend).Path
$d005Live = '/app/data/data005-live-replay'
docker compose ps
if ($LASTEXITCODE -ne 0) { throw 'Docker unavailable' }
docker compose exec -T api python -m app.services.geo001_audit before --output-dir $d005Live
if ($LASTEXITCODE -ne 0) { throw 'Before inventory failed' }
docker compose exec -T api python -m app.services.presidential_returns_snapshot --output "$d005Live/snapshot.json"
if ($LASTEXITCODE -ne 0) { throw 'Snapshot failed' }
docker compose run --rm --no-deps --volume "${d005Backend}:/app" api python -m app.services.geo002_validate schema --output-dir $d005Live
if ($LASTEXITCODE -ne 0) { throw 'Schema check failed' }
docker compose exec -T api python -m app.services.geo001_audit after --output-dir $d005Live
if ($LASTEXITCODE -ne 0) { throw 'Preservation audit failed' }
```

`snapshot` verifies the archived MEDSL file hash, stored return count/sum, current
geographic heads, source/preview and all public-table fingerprints. Its transaction
is REPEATABLE READ / READ ONLY. The offline report separately checks the 255
2008 successors against GEO-002 manifests and actors. An old manifest's
`publication_authorized: false` does not erase actual later published history,
and a live actor on geography does not authorize canonical supersession.

## Tests

```powershell
$env:PYTHONPATH = 'backend'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_presidential_returns_evidence.py -q
if ($LASTEXITCODE -ne 0) { throw 'Offline tests failed' }
$d005Backend = (Resolve-Path .\backend).Path
docker compose run --rm --no-deps --volume "${d005Backend}:/app" -e PYTHONDONTWRITEBYTECODE=1 -e GEO002_TEST_OUTPUT=/app/data/data005-test-replay api python tests/run_geo002_tests.py
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL suite failed' }
```

The existing runner is reused: `GEO002_TEST_OUTPUT` selects a fresh report path,
not a test selection. It runs the entire current suite in `DB_NAME + '_test'`,
with per-test schemas. Expected current result: 132 passed, no failures/skips.
Live county-scope DATA-005 publication/replay were not run. The later FEC
state-scope publication and UNCHANGED replay are recorded in fec_state_authority_2008.md.

## Retrieve new official evidence

The published evidence is already available; re-downloading can return changed
files, rate limits or CAPTCHA responses. Archive to fresh paths and review those
inputs separately. The raw downloader needs only the standard library. It stores
checksums, timestamps, status, final URL and response bytes without any ingestion.

```powershell
$d005Backend = (Resolve-Path .\backend).Path
Copy-Item -LiteralPath docs/sources/presidential_returns_2008_sources.json -Destination data/data005-fresh-requests.json
docker compose run --rm --no-deps --volume "${d005Backend}:/app" api python -m app.services.election_evidence_archive /app/data/data005-fresh-requests.json --output-dir /app/data/data005-fresh-raw --download-only
if ($LASTEXITCODE -ne 0) { throw 'Download process failed' }
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-research.txt
if ($LASTEXITCODE -ne 0) { throw 'Research dependencies failed' }
.\.venv\Scripts\python.exe -m app.services.election_evidence_extract data/data005-fresh-raw --output-dir data/data005-fresh-evidence
if ($LASTEXITCODE -ne 0) { throw 'Extraction failed' }
```

Inspect `retrievals.json`; process success does not validate every response.
CAPTCHA HTML/404s are unavailable evidence. Do not bypass TLS verification or
interactive challenges. The delivered Minnesota results file was successfully
archived before later challenge responses; use its original checksum-verified
bytes and the documented reviewed lookup extraction for reproducibility.
PDF extraction records layout and plain text; Alaska uses plain text because
rotated layout extraction warns of omissions. Maine's pre-existing OCR and CT's
scanned statement are not treated as verified special-unit definitions.

## Canonical supersession review

No publication command is part of routine reproduction. The concrete review
envelope is `data/data005/final/canonical-publication-review.json`, SHA-256
`fe3e75c048c3ed4b895831848b41f2c7ffcc608d562baeda97b7af074032c41b`.
It describes six new Virginia rows / 42,756 votes, 117 lineage changes, zero
removals, and a PARTIAL 9,336/138 batch. Separate explicit canonical approval
must identify this exact scope and acknowledge the remaining official-source
discrepancies and incomplete county coverage.

After approval, implement/execute a transaction-bound check of the approved
source release/hash, predecessor batch and exact preview fingerprint before
calling the established `materialize_medsl_year(..., dry_run=False,
allow_partial=True)` service in REPEATABLE READ with its publication lock. A
changed fingerprint or pointer requires fresh review; a preview in a separate
transaction alone does not prevent stale approval. Record the approving actor
and exact review envelope in publication evidence; existing canonical batches
have no actor column, so do not claim that actor was persisted there.

After an authorized publication, preserve the original batch/returns/issues,
all unrelated-year pointers, immutable sources/references/decisions and
identities. Permit only the expected new canonical batch/returns/issues and the
2008 pointer change. Verify counts/sums/exclusions and exact reviewed lineage,
then repeat the same materialization to prove UNCHANGED with no new batch/rows.
The general `geo001_audit after` zero-change assertion is for read-only work;
it is not a post-publication success criterion. Retain PARTIAL status and do not
mark DATA-005 Done while official reconciliation and coverage requirements fail.
