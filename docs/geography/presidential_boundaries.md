# Presidential map display packages

Presidential maps now load for all seven supported election years. Previously the
boundary preparer accepted only 2008 presidential geography and 2024 House
districts. The results already existed, but other years lacked display packages.

The fix extends the existing pinned acquisition, PostGIS preparation and verified
JSON lookup. It adds no database tables, migrations, dependencies or services and
does not change election returns or canonical geography.

## Sources and historical scope

The six additional configurations and SHA-256 pins are tracked in
`backend/ingestion/catalog/election_boundaries.json`. Existing 2008 and House pins
remain in `ingestion.boundaries`. Original URLs, retrieval timestamps and checksums
are retained in the acquisition cache and generated manifests.

| Election | State/county display source | County/equivalent shapes, 50 states/DC |
| --- | --- | ---: |
| 2000 | Census 2000 geography (`state00` / `county00`) in TIGER 2008 | 3,141 |
| 2004 | Explicit display approximation described below | 3,141 |
| 2008 | Existing TIGER 2008 current geography | 3,142 |
| 2012 | TIGER 2012 | 3,143 |
| 2016 | Census 2016 cartographic boundaries, 1:500,000 | 3,142 |
| 2020 | Census 2020 cartographic boundaries, 1:500,000 | 3,143 |
| 2024 | Census 2024 cartographic boundaries, 1:500,000 | 3,144 |

Official archives:
[TIGER 2008](https://www2.census.gov/geo/tiger/TIGER2008/),
[2012 counties](https://www2.census.gov/geo/tiger/TIGER2012/COUNTY/),
[2012 states](https://www2.census.gov/geo/tiger/TIGER2012/STATE/),
[2016](https://www2.census.gov/geo/tiger/GENZ2016/shp/),
[2020](https://www2.census.gov/geo/tiger/GENZ2020/shp/), and
[2024](https://www2.census.gov/geo/tiger/GENZ2024/shp/).
These are generalized display polygons, not election-day certifications,
measurement geometries or reconstructed vote allocations.

The 2004 package combines Census 2000 state outlines, Census 2008 county outlines
outside Alaska and Census 2000 Alaska county outlines. The older Alaska layer
avoids showing post-2004 county splits as 2004 geography; see the
[Census county-change record](https://www.census.gov/programs-surveys/geography/technical-documentation/county-changes.2000.html).
This remains an approximation, including intervening boundary adjustments, and
the map prominently discloses it. Exact 2004 boundary reconstruction remains
future geography work. Original votes are never redistributed.

All joins retain the reference-year, canonical jurisdiction, state, grain and exact
GEOID checks. Statistical reference ranges do not certify legal boundary continuity.
Replaced or renamed counties can remain unmatched if their published reference
differs from the selected display vintage. Their returns remain in tables and
`results_without_geometry`; successor codes are not inferred. Boundary-only areas
remain missing rather than receiving zero votes. County publications remain partial.

## Preparation and same-year layers

From the repository root with the existing Compose stack running:

```powershell
# Install the existing optional preparation requirements if absent.
docker compose exec -T api python -m pip install -r requirements-geography.txt
docker compose exec -T api python -m ingestion.boundaries --all-presidential

# Or prepare a single presidential election explicitly.
docker compose exec -T api python -m ingestion.boundaries --year 2020 --office president
docker compose exec -T api python -m ingestion.boundaries --year 2024 --office president

# The original House command remains compatible.
docker compose exec -T api python -m ingestion.boundaries --year 2024
```

Each manifest is replaced atomically only after its sources, geometries, national
counts and unique identifiers pass validation. The all-year command is restartable;
earlier successful years remain usable if a later one fails. Changed source hashes
fail closed, and replays verify cached source and generated content.

The same 2024 manifest now holds presidential states/counties and House districts.
A `layers` map retains each grain's own vintage, sources and transformation settings.
Preparing one set preserves the other grains' objects and provenance in either order.
The API returns metadata from the selected layer. Legacy manifests remain supported.

The supplied national URL with `reporting_level=county` opens the state overview
and asks the user to choose a state for county returns. Direct county URLs include
`state_code`, for example:

```text
/map?year=2020&office=U.S.+President&stage=general&state_code=NY&reporting_level=county
```

Attribution shows the actual boundary vintage. Missing packages still retain
tabular results; no automatic fallback to another year is introduced.

## Validation

The selected backend run passed 27 tests, including isolated PostgreSQL map,
House and candidate integrations. Fixtures cover all six added years, historical
field names, composite Alaska selection, count checks, deterministic replay,
checksum/corruption failures and preserving same-year House metadata. All 146
frontend tests and the TypeScript/production build passed.

Live preparation used pinned Census archives and actual PostGIS validation.
Every one of the 357 state-scoped county packages passed checksum, scope and
count checks. All original 2008 objects/provenance and all 436 House district
objects/provenance were preserved; the legacy 2008 manifest gained an explicit
supported-grain list. Live 2020 and House replays returned `unchanged`.
Headless Edge verified the supplied URL, all seven national/NY county maps,
county selection/refresh/history, candidate and House maps, and layouts at
320/375/768/1440px with no page errors or overflow. Screenshots were inspected.
Local receipts, before/after manifests, replay and browser evidence are under
ignored `data/election-boundaries/` and `artifacts/election-boundaries/`.

```powershell
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
Invoke-RestMethod 'http://localhost:8000/api/v1/election-map?year=2020'
Invoke-RestMethod 'http://localhost:8000/api/v1/election-map?year=2020&state_code=NY&reporting_level=county'
```
