# DATA-005 county verification — PowerShell runbook

Run from `C:\Users\Grant\Documents\election-data-monorepo`. The source and
evidence delivery ZIPs provide archived inputs. Commands below generate reports
without publishing source, geography or canonical data. Use fresh output paths;
commands refuse to overwrite existing reports or publication evidence.

```powershell
Set-Location C:\Users\Grant\Documents\election-data-monorepo
$env:PYTHONPATH = 'backend'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-research.txt
```

The tested parsers are pypdf 6.21.4, PyMuPDF 1.28.2, BeautifulSoup 4.15.0 and
xlrd 2.0.2. PDF research rendering/OCR is supplemental; the production verifier
uses checked transcriptions for MT/WY, validates their source/table checksums,
and checks every printed candidate-column total. Changing a transcription or
source requires another numeric review and updated evidence, not an automatic
geographic approval.

Generate a fresh live baseline before further work:

```powershell
docker compose run --rm --no-deps api python -B -m app.services.geo001_audit before `
  --output-dir /app/data/data005-county-next
docker compose run --rm --no-deps api python -B -m app.services.data005_snapshot `
  --output /app/data/data005-county-next/snapshot.json
```

The delivered baseline is `data/data005-county/snapshot.json`. Offline replay
uses its immutable observation IDs/checksums and the original 144-row handoff.
The verifier checks all successful raw downloads before parsing, even if a
research response is not ultimately used as numeric evidence.

```powershell
$d005CountyArchives = (Get-ChildItem data/data005-county -Directory |
  Where-Object {
    $_.Name -like 'raw*' -and
    (Test-Path (Join-Path $_.FullName retrievals.json))
  }).FullName

.\.venv\Scripts\python.exe -B -m app.services.county2008_verify `
  --snapshot data/data005-county/snapshot.json `
  --archives $d005CountyArchives `
  --prior-evidence data/data005/evidence `
  --mn-evidence data/data005-county/mn-input `
  --output-dir data/data005-county-next/reports
if ($LASTEXITCODE -ne 0) { throw 'County report generation failed' }
```

The delivered `final/` and `replay/` were generated with these same inputs.
All files except `summary.json` must be byte-identical; summary generation times
may differ. The correction digest must match the reviewed manifest. No new
downloads are needed for replay.

To enforce the backlog acceptance gate, add `--require-complete` and a different
fresh output directory. **Its expected exit code is currently 2**, because
county verification remains PARTIAL. Exit 0 without that option means the
audit completed, not that all county acceptance criteria passed.

New downloads are a separate evidence collection run. Expose the repository's
source catalog with an explicit read-only bind mount:

```powershell
$d005RepoRoot = (Get-Location).Path
docker compose run --rm --no-deps --volume "${d005RepoRoot}:/workspace:ro" api `
  python -B -m app.services.data005_sources `
  /workspace/docs/sources/DATA005-county-sources.json `
  --output-dir /app/data/data005-county-next/raw --download-only
```

The catalog records all 131 research requests, including unsuccessful attempts.
Transport success is distinct from
numeric validation. Illinois's public form state/download links may need to be
refreshed from its recorded download page; never overwrite the existing raw
archive or disable TLS checks to force a download. Supplemental MN raw inputs
are copied into `mn-input/` with original checksums; the user's fresh directories
remain untouched.

Run the full suite against current source, including PostgreSQL, in the isolated
`DB_NAME + '_test'` database. The explicit install flag installs optional parsers
inside the disposable container; it does not change production requirements.

```powershell
$d005BackendRoot = (Resolve-Path .\backend).Path
docker compose run --rm --no-deps --volume "${d005BackendRoot}:/app" `
  -e PYTHONDONTWRITEBYTECODE=1 `
  -e GEO002_TEST_OUTPUT=/app/data/data005-county-next/tests `
  api python -B tests/run_county2008_tests.py --install-research
if ($LASTEXITCODE -ne 0) { throw 'Full test suite failed' }
```

The delivered final run has 158 passing tests and no errors/failures/skips.
`test-source-hashes.json` proves implementation files stayed unchanged during
the run. Packaging also verifies those hashes against the current files.

Prove live preservation in a repeatable-read, read-only transaction:

```powershell
docker compose run --rm --no-deps api python -B -m app.services.county2008_live `
  --before /app/data/data005-county/full-before.json `
  --fec-baseline /app/data/data005-fec/publication.json `
  --output-dir /app/data/data005-county-next/live-proof
if ($LASTEXITCODE -ne 0) { throw 'Live preservation verification failed' }
```

For a new session use that session's `full-before.json` instead. Any changed live
table set/row fingerprint, FEC pointer/fingerprint or state total fails the
check. The script also recomputes the existing county canonical preview through
the established planner; it never calls a publisher.

The deliverable packaging command validates the final/replay reports, final
test source hashes, live proof, 566 differences and 144 distinct original
exclusions. It updates only DATA-005's backlog row, preserving the UTF-8 BOM,
CRLF and every unrelated physical row. Existing delivery directories cause a
failure; keep previous packages immutable.

```powershell
.\.venv\Scripts\python.exe -B -m app.services.county2008_package
```

That command is for the recorded delivery layout (`final/`, `replay/`,
`tests-final/`, `live-final/`). The existing delivery has already been packaged;
do not overwrite it. A future run needs fresh paths and reviewed delivery notes
if the evidence or scope changes. Both ZIPs contain `SHA256SUMS.json`, and
`delivery.json` records their checksums and validation result.

`correction-manifest.json` is a **verification proposal**, not a canonical CLI
input. Source corrections require reviewed append-only ingestion and separate
publication authorization. Keep FEC state totals authoritative, retain original
observations and county batches, and retain PARTIAL until evidence, geography,
reporting coverage and publication criteria are satisfied.
