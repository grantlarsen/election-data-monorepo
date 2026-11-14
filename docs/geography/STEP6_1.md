# Step 6.1 — Geographic remediation (patch installation / operator runbook)

## Compatibility and scope

- Apply to the **uploaded Step 6.1 repository** at Alembic revision `c1f7a2b98d40`.
- Existing 94,151 MEDSL rows and their raw labels, identifiers and votes are not changed.
- Geographic reference rows are not rewritten. Legacy `geographic_resolution` rows are retained as the roots of new, append-only supersession chains.
- **No aliases or historical continuity links are automatically approved.** The CSVs in `ingestion/geography/catalog/` are proposals, not a verified county crosswalk.
- `geo resolve` defaults to read-only preview. `--publish --actor` is required for writes; previously published changed decisions also require `--approve-changes`.
- No spatial geometry is loaded. Historic source product year *ranges* are not assumed to be effective dates.

## Schema changes and reasons

Migration: `b3d62a17f8ac_geographic_remediation.py` (depends on `c1f7a2b98d40`).

| Change | Reason |
| --- | --- |
| `geographic_alias` | Reviewed, source-scoped aliases with year windows and evidence. |
| `geographic_change` | Dated, cited county code/name changes; evidence must be verified to influence matching. |
| `geographic_identity_link` | Explicitly approved linkage of historical jurisdiction UUIDs; does not merge/delete them. |
| `geographic_reporting_unit` | Identifies state/year/source-specific non-county reporting units and keeps county link null. |
| `geographic_resolution` supersession fields | Chain revisions, ruleset version, decision hash and approver without deleting earlier decisions. |
| Place reference GEOID/identifier width (`VARCHAR(10)`) and `kind='place'` | Add Census place geography without conflating it with county FIPS. |

### Safety and rollback

Back up PostgreSQL first; the migration intentionally **has no destructive downgrade** because reversing it would discard decision chains. On failure, stop; diagnose and restore a database backup if necessary. Do not use `alembic downgrade` on production election data.

Database lock: publication holds the MEDSL `data_source` row for the duration of a transaction, serializing geography resolution publishers. `geographic_resolution` supports one root per observation/reference and one successor per decision. Identical reruns do not insert decisions.

The existing `stable_jurisdiction_id()` still creates distinct UUIDs for changed FIPS/name combinations; continuity is established only by reviewed `geographic_identity_link` rows, not a database-wide merge. This is deliberate to avoid accidental identity joins.

## 1. Apply the patch in PowerShell

From the monorepo **root** (not `backend`):

```powershell
# Use the downloaded ZIP's actual location.
Expand-Archive -Path "$HOME\Downloads\election-step6.1-remediation-patch.zip" -DestinationPath . -Force

docker compose up -d --build
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic current
```

Expected migration head: `b3d62a17f8ac`. Rebuilding is necessary because migrations are copied into the API image rather than mounted.

## 2. Test non-destructively

```powershell
# Local venv should use Python 3.12 and backend requirements-dev.txt.
Push-Location .\backend
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/test_geography_remediation_rules.py
python -m pytest -q tests/test_geography_remediation.py tests/test_geography_quality.py -m "not integration"
Pop-Location
```

The Docker image currently has runtime requirements only (it does **not** include pytest or tests). To execute integration tests, use a *separate* disposable PostgreSQL database with a name ending in `_test`, configure `TEST_DATABASE_URL`, and run local pytest. Never point integration tests at your development election database.

To create the example database in the existing Compose DB container (requires authorization/permissions):

```powershell
docker compose exec -T db sh -lc 'createdb -U "$POSTGRES_USER" electoral_platform_test'
```

Set `TEST_DATABASE_URL` to the appropriate **local mapped port**, credentials, and database name, then:

```powershell
Push-Location .\backend
python -m pytest -q -m integration tests/test_geography.py
Pop-Location
```

The test fixture rejects URLs whose database name does not end in `_test`.

## 3. Import *proposals* only (safe and repeatable)

```powershell
docker compose run --rm api python -m ingestion geo alias-import --file ingestion/geography/catalog/candidate_aliases.csv
docker compose run --rm api python -m ingestion geo change-import --file ingestion/geography/catalog/candidate_county_changes.csv
docker compose run --rm api python -m ingestion geo evidence-list
```

The commands do not approve aliases or dated changes. Check the emitted `data/ingestion/geography/evidence-*.json` for assigned UUIDs. Review these records against the official evidence and the original MEDSL label.

### Manually approve a county alias

```powershell
docker compose run --rm api python -m ingestion geo alias-approve `
  --alias-id "<alias-uuid-from-evidence-report>" `
  --actor "your-reviewer-id" `
  --evidence-url "https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html"
```

Use the **actual specific evidence page** rather than the general example when approving. Approval requires matching state FIPS, an ingested county reference with the target code, an unambiguous target for overlapping periods, reviewer identity, and an HTTPS citation. A bare fuzzy name match is never enough.

### Verify dated change and optionally link canonical identities

```powershell
docker compose run --rm api python -m ingestion geo change-verify `
  --change-id "<change-uuid>" --actor "your-reviewer-id"

# Only after reviewing both UUIDs and the legal continuity:
docker compose run --rm api python -m ingestion geo identity-link `
  --change-id "<change-uuid>" `
  --old-jurisdiction-id "<old-uuid>" `
  --new-jurisdiction-id "<new-uuid>" `
  --relationship SAME_ENTITY_RECODED --actor "your-reviewer-id"
```

An `identity-link` does not automatically revise published observation matches. It provides continuity evidence for a future reviewed resolution.

## 4. Optional independent Census 2024 place reference

The new `census_2024_places_gazetteer` adapter uses the official Census national places ZIP, not a county dataset. It is independent of the existing 2024 Census CBP/NES reference. The existing source acquisition, SHA-256 cache, release provenance, audit run and idempotent SQL inserts are reused.

```powershell
docker compose run --rm api python -m ingestion run census_2024_places_gazetteer --vintage 2024 --validate-only
docker compose run --rm api python -m ingestion run census_2024_places_gazetteer --vintage 2024
docker compose run --rm api python -m ingestion geo validate --vintage 2024 --source census_2024_places_gazetteer
```

The state records from Step 6 must exist first, because each place has a parent-state relationship. This is 2024 place evidence only; it does not establish validity of Kansas City's GEOID in every earlier election year. **Do not** pass this source to the county-oriented `geo resolve` command.

## 5. Preview revised MEDSL decisions

```powershell
$referenceVintages = @(2000, 2004, 2012, 2020, 2024)
foreach ($year in $referenceVintages) {
    docker compose run --rm api python -m ingestion geo compare --vintage $year
    if ($LASTEXITCODE -ne 0) { throw "Comparison failed for $year" }
}
```

Every comparison outputs `data/ingestion/geography/resolution-*.json` (full coverage, differences and vote reconciliation) and `review-*.csv` (still-invalid, ambiguous or unresolved observations). **Review those files first.** `geo compare` and `geo resolve --dry-run` never write decisions.

### Publish explicitly

```powershell
foreach ($year in $referenceVintages) {
    docker compose run --rm api python -m ingestion geo resolve --vintage $year `
      --publish --approve-changes --actor "your-reviewer-id"
    if ($LASTEXITCODE -ne 0) { throw "Geographic publication failed for $year" }
}
```

`--approve-changes` approves **all changes in that vintage batch**. If you need selective publication, run with `--years` to narrow the election years; isolate further cases before approving a whole batch. This flag is intentionally explicit and cannot be inferred from `--publish` alone.

Confirm repeat runs yield `records_inserted: 0`; no election observation updates are issued.

## 6. Quality, unresolved, and change history

```powershell
foreach ($year in $referenceVintages) {
    docker compose run --rm api python -m ingestion geo validate --vintage $year
    docker compose run --rm api python -m ingestion geo quality --vintage $year
    docker compose run --rm api python -m ingestion geo unresolved --vintage $year
}
docker compose run --rm api python -m ingestion geo anomalies
docker compose run --rm api python -m ingestion geo changes
```

Resolution report contains `status_counts`, `coverage_by_year_state` (observations and distinct source units), `vote_totals_by_year_state`, `vote_totals_unchanged`, `differences`, and `review_count`. `quality` reports only the current leaves of the decision chain. `NON_COUNTY_CLASSIFIED` is not a canonical county match.

## Specific anomaly policies and unresolved work

- **Alaska:** Districts 1–98 are classified as state election reporting geography (source/year-scoped, null county); district 99 goes to `PENDING_REVIEW` until a documented source definition exists. District code 20 must never become Anchorage `02020`.
- **County alias candidates:** Eight label groups were imported as proposals. Virginia `CHARLES CITY` / `JAMES CITY` and Doña Ana normalization should improve without aliases; the remaining aliases require evidence and reviewer approval.
- **Connecticut 2024:** 8 historical counties may resolve against the last pre-planning-region Census reference, but are explicitly marked *legacy election reporting geography*. There is no manufactured county-to-planning-region mapping.
- **South Dakota:** The 2015 recoding is supplied as an evidence proposal. After verification, new `46102` may be linked using post-change Census evidence. Old `46113` observed in 2024 goes to review as a retired code.
- **Missouri:** `2938000` is a Census **place** identifier, not a county FIPS. `36000` in 2024 is still a conflict requiring primary-source adjudication.
- **Washington DC and Florida in 2000:** The currently ingested CBP references lack some historical entries. They remain unresolved; the loaded-reference quality report lists known coverage gaps rather than fabricating Census 2000 source rows.
- **Other missing FIPS:** CT statewide write-ins, ME UOCAVA and RI federal precincts are classified as non-county voting categories and retain null county jurisdiction IDs.

## Remaining limitations (not done by this patch)

1. No official Alaska district-by-district vintage catalog or boundary polygons have been ingested. District classification is **not** proof of a canonical district identity or a county allocation.
2. No comprehensive Census 2000 county enumeration supplement yet; DC and Miami-Dade require a separate, cached, source-versioned Census 2000 adapter and review.
3. The D.C./Florida and some other historical code/date gaps remain intentionally unresolved until reference data is ingested.
4. Geometry and legal boundary timelines are not implemented. No spatial join or redistricting plan attribution is implied.
5. Full PostgreSQL integration and all 94,151 observation resolutions must run in your Compose database; this package cannot certify their output from the attached CSVs alone.

## Failure recovery

- **Migration fails:** Stop. Inspect `alembic current`, inspect the SQL error, restore backup if needed. Don't modify existing MEDSL observation tables manually.
- **Incorrect alias approved:** Do not delete it or rewrite source observations; open a reviewed correction proposal, stop publication, and document which decisions require supersession. Alias revocation workflow is intentionally not automated in this release.
- **Unwanted changed decisions:** `geo compare` first. If `geo resolve` reports drift without `--approve-changes`, the transaction rolls back.
- **Duplicate publishing:** Existing roots and successor constraints prevent concurrent conflicting branches; the MEDSL data-source row is locked for publishing.
- **Census data not found / changed:** Source layer preserves SHA-256 for each release. Choose explicit `--release-id` if multiple source bytes exist.
- **Source zip has unexpected structure:** `--validate-only` fails before DB writes. Update parser with a regression fixture rather than skipping validation.
