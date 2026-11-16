# Presidential returns file naming

Source modules, tests, documentation and source catalogs use functional names.
The complete old/new path mapping is in `presidential_returns_file_names.json`.

Examples:

| Purpose | Current name |
| --- | --- |
| Independent 2008 evidence parsers | `ingestion.presidential_returns_2008` |
| Archive raw authority evidence | `app.services.election_evidence_archive` |
| Extract archived evidence | `app.services.election_evidence_extract` |
| Snapshot source/canonical results | `app.services.presidential_returns_snapshot` |
| Reconcile official and source returns | `app.services.presidential_returns_reconciliation` |
| Validate/package reconciliation evidence | `app.services.presidential_returns_package` |
| Publication status | [county_corrections_publication_2008.md](county_corrections_publication_2008.md) |
| Remaining verification work | [county_verification_followup_2008.md](county_verification_followup_2008.md) |

Backlog task identifiers remain identifiers. Existing generated evidence folders,
released archives, serialized format/ruleset identifiers, migration revision IDs,
and deployed database function/trigger names retain their historical values.
Changing those would alter published lineage or digests rather than just names.
The reviewed transcription catalog also preserves its original filenames as
historical references; the correction loader resolves them to the descriptive
CSV paths without changing the publication manifest. Renamed migration files
retain their deployed revision IDs and SQL object names.

Older immutable delivery ZIPs include their original source tree. Their scripts
describe that archived version; current commands and imports use the names above.

Validation after renaming: all 166 offline/PostgreSQL tests passed, with no
failures or skips. The correction preview retained both published fingerprints,
and the live preservation audit found all 42 public tables unchanged. Alembic
reported the expected deployed head and no pending schema changes when run
against the current source. Validation outputs are in
`data/presidential-returns-maintenance/` (local, ignored).

Compose mounts application and ingestion code from the workspace, but migrations
come from the container image. Rebuild the API image after migration file renames,
or mount the current backend for a schema check:

```powershell
$currentBackend = (Resolve-Path .\backend).Path
docker compose run --rm --no-deps --volume "${currentBackend}:/app" api python -B -m alembic current
docker compose run --rm --no-deps --volume "${currentBackend}:/app" api python -B -m alembic check
```
