# Electoral Platform: Docker Compose starter

Minimal local development stack with PostgreSQL 18 + PostGIS 3.7 and Python 3.12 + FastAPI. Intended only for local development.

## 1. Prerequisites

- Docker Desktop running with the Linux/WSL 2 backend (or Docker Engine with Compose on Linux)
- PowerShell and VS Code (instructions below), or equivalent shell

## 2. Configure secrets

From the project folder in PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

Replace `POSTGRES_PASSWORD` with a strong password. `.env` is ignored by Git.

## 3. Start the stack

```powershell
docker compose config
docker compose up -d --build
docker compose ps
```

Wait for `db` to show `(healthy)` and `api` to show `Up`.

## 4. Verify

Open:

- http://localhost:8000/health
- http://localhost:8000/health/db
- http://localhost:8000/docs

Check PostGIS directly:

```powershell
docker compose exec db psql -U electoral_user -d electoral -c "SELECT PostGIS_Version();"
```

Change database name/user in this command if you changed them in `.env`.

## 5. Work on code

Edit `backend/app/main.py` in VS Code. The `api` development service runs with Uvicorn reload and mounts the source folder.

## 6. Useful commands

```powershell
docker compose logs -f api
docker compose logs -f db
docker compose ps
docker compose down
docker compose up -d --build
```

Do not use `docker compose down -v` unless you mean to delete the local PostgreSQL data volume.

## Notes

- `db` is reachable **from inside Docker** at hostname `db` on port `5432`. It is reachable **on the host** at `localhost` port `${POSTGRES_PORT}` (default `5432`).
- API is published only to `127.0.0.1:8000`.
- DB credentials in `.env` are appropriate for a local example, not production secret management.
- Docker image upgrades and PostgreSQL major upgrades require tested backups/migration procedures. PostgreSQL 18's persistent volume is mounted at `/var/lib/postgresql`.
- Step 3 of the project should add migrations, separate roles, test suites, and more complete environment configuration.
# Step 5 — MEDSL presidential county ingestion (Python 3.12 / PostgreSQL)

> **Integration update — reviewed project infrastructure (Nov 2026)**
>
> This revised overlay is tailored to the files you supplied. The original overlay required `DATABASE_URL`, expected migrations in `backend/alembic`, and omitted the ingestion package from the Docker image; those assumptions were incompatible with your files and have been corrected here.
>
> Files in this archive that intentionally update existing infrastructure: `backend/Dockerfile` (one additional `COPY ingestion`), `backend/migrations/env.py` (register Step 5 model), `backend/requirements.txt` (add Polars), plus `backend/requirements-dev.txt` (pytest). **Your `app/database.py`, `alembic.ini`, initial migration, existing core models, and Compose configuration are not replaced.**
>
> `docker-compose.yml` was not supplied. Because your earlier `docker compose` invocation worked, determine the actual file name by running `docker compose config --services` from the repository root. Verify the `api` image uses `backend/Dockerfile` with build context `./backend`, and that DB_USER / DB_PASSWORD / DB_NAME are set for `api`.
>
> **Integration status:** Python syntax checked; an end-to-end Compose/PostgreSQL/MEDSL full-data execution is still required. No claim is made that production Definition of Done is already met.


This overlay is designed for the existing ElectionDataMonorepo. **It is not an entire replacement repository.** It was built against the two files supplied (`core.py`, revision `2c9541d24f1e`) and assumes:

- `backend/app/database.py` defines `Base` and the shared `engine` (confirmed).
- `backend/app/models/core.py` contains the supplied model definitions.
- Alembic's script directory is `backend/migrations` (confirmed by uploaded `alembic.ini`).
- The Docker Compose service is named `api`, the service working directory is `/app`, and the backend code is mounted/built there (consistent with the user's working Alembic command).
- `app.database.engine` uses `DB_USER`, `DB_PASSWORD`, `DB_NAME`, and optional `DB_HOST`/`DB_PORT`, matching the uploaded `database.py`.

**Integration is partially verified:** uploaded `Dockerfile`, `database.py`, `migrations/env.py`, `alembic.ini`, and requirements were reviewed; Docker Compose configuration remains unavailable. This archive contains complete new source, migration, and tests; its runtime must be validated in the actual project. All Python files pass `compileall`; standalone acquisition/cache test passed. PostgreSQL and Polars integration tests could not be run in this authoring environment.

## Stage A — Files to add (do not overwrite current models)

Copy this archive's `backend/` contents into the existing `backend/` folder, preserving the folder tree:

```text
backend/
  app/models/ingestion.py             # new ORM tables only
  migrations/versions/75c2f4a1d9be_ingestion.py  # new additive migration
  ingestion/__init__.py
  ingestion/__main__.py                # generic CLI / execution reporting
  ingestion/source.py                  # official metadata, original download, immutable cache
  ingestion/medsl.py                   # Polars parser and normalization
  ingestion/validation.py              # Polars quality checks and rejections
  ingestion/loader.py                  # transactional PostgreSQL insertion and upserts
  ingestion/adapters/__init__.py
  ingestion/adapters/medsl_presidential_county.py # MEDSL adapter
  tests/fixtures/medsl_small.csv
  tests/test_parsing.py
  tests/test_acquisition.py
  tests/test_database.py
  Dockerfile                           # updated existing Dockerfile; copies ingestion package
  requirements.txt                    # existing requirements plus Polars
  requirements-dev.txt                # optional pytest dependency
  migrations/env.py                   # updated existing env.py; registers ingestion model
  pytest.ini                           # merge markers if pytest.ini already exists
```

**Preserved unchanged:** `app/database.py`, existing `app/models/core.py`, `alembic.ini`, existing migrations, and Compose files. The archive does contain modified versions of your uploaded Dockerfile, Alembic `migrations/env.py`, and `requirements.txt`: review the diffs before applying them. The new migration references exactly the existing core tables.

### Existing Alembic migration cleanup (optional but recommended)

In your existing `2c9541d24f1e_initial_election_schema.py`, find `def downgrade()` and delete the **standalone** `sa.Column(...)`, `sa.ForeignKeyConstraint(...)`, `sa.PrimaryKeyConstraint(...)`, and `sa.UniqueConstraint(...)` expressions referencing `topology`/`layer` before the first `op.drop_index(...)`. Leave all legitimate `op.drop_...` calls in order. No modification to `upgrade()` or existing tables is needed.

## Stage B — Dependency and DB setup

The updated `backend/requirements.txt` retains your FastAPI, Uvicorn, SQLAlchemy, psycopg v3, and Alembic dependencies and adds **`polars>=1.35,<2`**. `backend/requirements-dev.txt` adds pytest for testing and references the runtime requirements. No new PostgreSQL driver is needed.

The supplied `backend/migrations/env.py` already imports both model modules and registers them with `Base` before Alembic sets `target_metadata`:

```python
import app.models.core  # noqa: F401
import app.models.ingestion  # noqa: F401
```

The included `migrations/env.py` is your uploaded file with two explicit model registrations added. Compare it with your repository copy before replacing it. `alembic.ini` already points at `%(here)s/migrations`, so the new revision is in `migrations/versions/`. **Inspect** the generated migration before applying it.

From the repository root, in **Windows PowerShell**:

```powershell
# Ensure Compose is running and rebuild API image after adding requirements.
docker compose up -d db
docker compose build api

# Revision must be upgraded inside the existing application environment.
docker compose run --rm -v ./backend:/app api alembic current
docker compose run --rm -v ./backend:/app api alembic upgrade head
docker compose run --rm -v ./backend:/app api alembic current
```

If `alembic` is located elsewhere in your repository, adapt the directory to what is shown in `alembic.ini` and Docker `WORKDIR`. Running the container with `-v ./backend:/app` may replace built code, so ensure host dependencies and package paths are consistent.

For a host-side virtual environment, from the repository root:

```powershell
cd backend
python -m pip install -r requirements-dev.txt
# Supply the same DB_USER, DB_PASSWORD, DB_NAME, DB_HOST, and DB_PORT variables
# used by docker compose, but set DB_HOST to localhost and DB_PORT to the published port.
python -m alembic current
```

No credentials are hardcoded in the ingestion package. The database connection is provided by your existing `app.database.engine`, which reads the `DB_*` environment variables.

## Stage C — CLI commands

Run from `backend/` in PowerShell:

```powershell
python -m ingestion run medsl_presidential_county --validate-only
python -m ingestion run medsl_presidential_county --dry-run
python -m ingestion run medsl_presidential_county
python -m ingestion run medsl_presidential_county --years 2020 2024
python -m ingestion run medsl_presidential_county --refresh --verbose
```

Alternatively, **from the monorepo root** using the existing Compose `api` service. Bind-mount a durable data directory (the path is relative to `/app`):

```powershell
New-Item -ItemType Directory -Force .\data | Out-Null
docker compose run --rm -v ./backend:/app -v ./data:/app/data api python -m ingestion run medsl_presidential_county --validate-only
docker compose run --rm -v ./backend:/app -v ./data:/app/data api python -m ingestion run medsl_presidential_county --dry-run
docker compose run --rm -v ./backend:/app -v ./data:/app/data api python -m ingestion run medsl_presidential_county
```

**Flag behavior:**

| Flag | Network | Database writes | Meaning |
|---|---|---|---|
| No flags | metadata fetch, CSV fetch if uncached | Yes | All seven years; activate on successful transaction |
| `--refresh` | always re-fetch CSV | Yes unless combined with a read-only flag | Replace corrupt cache only after quarantining; preserve hash-addressed files |
| `--validate-only` | metadata + file retrieval as needed | **No** | Parse and validate, write local JSON report and rejection file; no DB connection required |
| `--dry-run` | metadata + file retrieval as needed | **No** | Validation plus read-only lookups for existing release / active years; requires DB schema |
| `--years 2020 2024` | metadata + full CSV | Yes for those years only | Imports selected years and switches their active pointers independently; full original file retained |
| `--verbose` | same | same | DEBUG logs for troubleshooting |
| `--state-totals-csv PATH` | same | same | Optionally compare county aggregates to independently obtained state-year totals |

Flags may be combined except `--validate-only` with `--dry-run`. The cache still contacts Dataverse to check the **latest released metadata** each run; it is not an offline mode. Set `INGESTION_DATA_DIR` to select durable storage (default: `data/ingestion` relative to the current working directory).

### Official acquisition and verification

Metadata endpoint:

`https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/VOQCHQ`

File endpoint discovered dynamically from the metadata:

`https://dataverse.harvard.edu/api/access/datafile/<file-id>?format=original`

As verified 2026-11-12, the released Dataverse version is **20.0** (publication timestamp **2026-02-25T19:00:32Z**), file ID **13573089**, original CSV named `countypres_2000-2024.csv`, and publication license is **CC0 1.0**. These are informational only; the importer always requests live release metadata. Source dataset DOI: https://doi.org/10.7910/DVN/VOQCHQ . It intentionally requests the **original CSV** rather than Dataverse's transformed `.tab` representation. The API-published MD5 in `dataFile.checksum` applies to its archival `.tab` format; do **not** compare it to the original CSV. The code checks original-file byte length (when available), calculates SHA-256, verifies the cached copy on every reuse, and records the original file metadata.

Raw files are immutable under:

`data/ingestion/raw/medsl_presidential_county/<version>/<sha256>.csv`

The manifest `file_<Dataverse-file-id>.json` stores source metadata, download URL, SHA-256, retrieval time, and relative file name. When cache corruption is detected, the run fails unless `--refresh` is used; with refresh, corrupted bytes are quarantined before replacement. Every execution produces `data/ingestion/reports/<run-id>.json` and validation failures additionally create `data/ingestion/rejections/<run-id>.json`.

## Stage D — Normalization and validation

Source raw fields remain unchanged under `raw_json`, including text `county_fips`, `candidate`, `party`, `mode` and `version` (if provided). The normalized fields are additive, not destructive. All DataFrame operations use Polars.

- `state_po`: uppercase USPS abbreviation; derive the two-digit Census state FIPS prefix from an explicit 50-state-plus-DC map.
- `county_fips`: a 1–5 digit source code is zero-padded to 5 digits; if missing/malformed or mismatched to its state prefix, do not assign normalized county FIPS. **This is a syntactic check, not proof the identifier existed in that election year.** Historical crosswalk data is needed for stronger checks.
- `candidate`: whitespace normalization + uppercase comparable label; no automatically invented `person` records.
- `party`: map a few unambiguous source labels (e.g., `DEMOCRAT` to `DEMOCRATIC`); unknown values are retained without guessed canonical party links.
- `candidate_kind`: `candidate`, `aggregate` (`OTHER`, etc.), `write_in`, or `unresolved`; preserve all of them in the source observations.
- `candidatevotes`, `totalvotes`: signed 64-bit integer conversion; negative or malformed nonblank amounts are fatal. Missing amount remains `NULL` (not zero).
- `mode`: preserved exactly. No assumption that `TOTAL`, absentee, mail, or election-day components can always be added without double counting.
- `year`: accepts 2000, 2004, ..., 2024. Other/malformed election years fail validation, including when a subset is requested.

**Stop ingestion** (no result writes) for missing schema fields, missing requested years, invalid year/state, invalid office, missing county name, malformed/negative nonblank vote totals, or an unexpected >20% per-year row count change compared with the currently active release.

**Flag for review** (without deleting rows) missing vote components, unresolved/incorrect FIPS, missing party/candidate/version labels, duplicate logical keys, aggregate vote discrepancies, fusion/multi-party candidacies, and county label/FIPS changes. New-release per-year row count change >5% is a warning, >20% blocks activation. These thresholds are conservative *engineering policies*, not MEDSL specifications.

When a reference file is supplied, the comparator expects exactly `year,state_po,totalvotes`, with one row per state-year and trusted totals; differences >0.5% warn. Only `TOTAL` mode, or a single unambiguous mode per county-year, is eligible. The pipeline **does not independently download official state totals**; do not call this an authoritative reconciliation without adding a separately sourced reference dataset. The optional file is a hook for the next ingestion source.

**Important limitation:** MEDSL county observations can contain geographic assignment errors. Syntactic FIPS and historical consistency checks are not enough to establish that a county's votes actually belong to that county. Cross-check critical county-level research against state-certified results and a historical Census jurisdiction crosswalk.

## Stage E — Loading / idempotency / version updates

The four new audit tables and one result table are added via Alembic. Existing tables and constraints remain untouched. The `election_result_snapshot` table is not populated automatically because it requires a non-null `candidacy_id` and cannot safely hold `OTHER` / unidentified write-ins. `jurisdiction_id` and `candidacy_id` intentionally remain nullable until authoritative entity resolution exists. If a matching `PoliticalParty.name` already exists, `party_id` is linked; the importer never creates fake canonical people or counties.

Rows have both:

1. `logical_key`: stable SHA-256 of (year, state, county code/name, source candidate, source party, source mode), for review/diffing; **not unique**, because legitimate or erroneous duplicate lines may exist.
2. DB uniqueness: `(release_id, source_row_number)` within the **exact immutable input file**; the source CSV record ordinal is unambiguous for reruns of the same bytes. This preserves duplicates rather than overwriting them.

A release is identified by `(source_id, version, SHA256)`. Bulk PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` loads one transaction. `source_active_year` switches atomically in that transaction, independently for each election year. Historical `source_release` and result rows remain in the database. Query the **active** version via the view `active_election_result_observation`; do not sum results across all historical releases.

`records_inserted` = newly inserted immutable observations; `records_already_present` = already stored observations for the same release/year set. `records_updated` = **number of active observations replaced by switching an active year to a newer immutable release**, not the number of literal SQL `UPDATE` statements or precisely changed vote values. Run failures are persisted separately; a failed load transaction cannot partially switch active data.

### SQL verification (run with psql or your PostgreSQL client)

```sql
SELECT status, records_read, records_inserted, records_updated, records_rejected,
       raw_sha256, started_at, completed_at, duration_ms
FROM ingestion_run ORDER BY started_at DESC LIMIT 10;

SELECT version, sha256, file_id, filename, retrieved_at, published_at
FROM source_release ORDER BY retrieved_at DESC;

SELECT year, count(*) AS active_rows, sum(candidate_votes) AS candidate_votes
FROM active_election_result_observation
GROUP BY year ORDER BY year;

SELECT year, state_code, county_fips, county_raw, candidate_raw,
       candidate_kind, party_raw, candidate_votes, total_votes, mode_raw
FROM active_election_result_observation
WHERE year = 2024 AND state_code = 'NY'
LIMIT 25;

SELECT run_id, source_row_number, reasons_json, raw_json
FROM ingestion_rejection ORDER BY source_row_number LIMIT 20;
```

The count of active rows for each year must remain unchanged across a rerun of identical source data. After a version update, old releases remain queryable by their `release_id`, but only the latest successfully activated release for each selected year appears in the active view.

## Stage F — Tests

From `backend/`:

```powershell
python -m pytest -q tests/test_parsing.py tests/test_acquisition.py
```

For PostgreSQL integration tests, supply a **disposable** PostgreSQL database whose name ends with `_test`, so the fixture cannot casually operate on the production DB:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://<TEST_USER>:<PASSWORD>@localhost:<PORT>/electoral_platform_test'
python -m pytest -q tests/test_database.py
python -m pytest -q
```

The integration tests create a randomly named schema inside the disposable database and clean it up. They cover idempotent reruns, new versions, immutable history, active-release switching, and transaction rollback. Other tests cover column/schema validation, parsing, categories, FIPS, negative votes, duplicate rows, cache SHA-256, and forced refresh. No full MEDSL download is needed to run fixtures.

## Stage G — Adding the second source

The CLI dynamically imports `ingestion.adapters.<name>.Job`, so a second source does not require changing `ingestion/__main__.py` or cache infrastructure.

Implement `class Job` in `backend/ingestion/adapters/<name>.py` exposing:

- `key`, `source_url`, `supported_years`, and `describe()` returning `SourceInfo` (the metadata describing one immutable download).
- `parse(path)` and `normalize(frame)` using Polars.
- `select(frame, years)` and `validate(frame, years, reference)` returning `ValidationOutcome`.
- `preview(engine, version, sha256, years)` and `load(engine, source_id, run_id, asset, frame, years, issues, started_at, completed_at, duration_ms, raw_count)`.

For another election-results source, reuse `ingestion.loader.load()` if the normalized fields match the existing observation schema; otherwise write a **new domain-specific loading function** and a justified Alembic migration, reusing `source_release`, `ingestion_run`, `ingestion_rejection` and `source_active_year` as appropriate. FEC transaction-level finance records and Census demographic data should **not** be coerced into `election_result_observation`. Acquisition, audit and reporting are shared.

## Common errors / troubleshooting

| Symptom | Check / corrective action |
|---|---|
| `ModuleNotFoundError: polars` | Merge requirements and rebuild the image, not just restart the old container |
| `ModuleNotFoundError: app.models.core` | Confirm supplied `core.py` really lives at `backend/app/models/core.py`; adjust one import if different |
| `relation source_release does not exist` | Run `alembic upgrade head` inside the same Compose `api` environment as the importer |
| `relation data_source does not exist` | Initial migration is not applied or DB/search_path differs |
| `duplicate constraint` / model drift | Inspect existing tables and original migration before applying the new migration |
| `connection refused`, `port 5432` | Use Compose service hostname (`db`) in container URL and confirm `docker compose ps`; host port mapping may differ |
| network/Dataverse 429/503 | CLI retries transient failures; re-run later without `--refresh` if a verified cache exists, but metadata still needs network |
| wrong download length / SHA-256 | Preserve cache as evidence; run with `--refresh` to re-fetch and quarantine corrupted bytes |
| `FAILED_VALIDATION` | Open JSON report and corresponding rejection file; fix schema mapping or investigate source; no partial result import |
| invalid/changed county identifiers | Preserve originals; require independent FIPS crosswalk before linking canonical jurisdictions |
| unexpectedly doubled vote totals | Query active view, not all releases; don't sum vote totals repeated on candidate rows; don't double count modes |
| rollback failure | Inspect `ingestion_run.errors_json`; active-year pointer is unchanged if load fails |

## Definition-of-done status

- **Implemented in code:** official metadata acquisition, original source caching and SHA-256, source/version provenance, Polars parser, normalizations, severity-classed quality checks, raw record retention, transaction-safe bulk loading, immutable releases and atomic active-year switching, structured run audit, CLI, unit and integration test suites, and adapter extensibility.
- **To verify in the actual repository:** PostgreSQL migration, working Docker Compose `DB_*` environment, actual full V20 data parsing, source-specific warnings and counts, second successful idempotent run, all pytest suites.
- **Not implemented:** authoritative statewide comparison without a supplied independent totals file, verified historical Census FIPS crosswalk, or canonical person/contest/candidacy resolution. These require additional source data and are intentionally not guessed.
