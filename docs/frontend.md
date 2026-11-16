# Election research frontend

## Architecture and scope

The React/TypeScript/Vite application preserves UI-001's navigation, filters,
published record browsing, source labels and accessible loading/error states.
UI-002 supplies a modular federal election map using the 2008 presidential
general election as its base case. Existing result services,
models and migrations are reused; the migration head remains `d005county01`.

`frontend/src/geography/UnitedStatesMap.tsx` is a reusable SVG choropleth with
D3's standard Albers USA projection. Its inputs are GeoJSON, matched data,
color/tooltip accessors and selection callbacks; it has no election year or
candidate assumptions. `frontend/src/map/` adapts published election data and
separates page/URL coordination, cancellation/retry, results and lineage.
The API owns vote totals, shares and margins. D3 replaces the former Mercator
cameras and WebGL dependency: no worker, external basemap, tile service, API key,
frontend database or new hosting is needed. The map bundle loads separately.

## Run and verify in PowerShell

With the existing `.env`, Docker and normal database/migration setup:

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose exec -T api pip install -r requirements-geography.txt
docker compose exec -T api python -m ingestion.boundaries
Start-Process 'http://localhost:5173/map?year=2008'
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
```

Boundary preparation downloads two pinned Census archives, validates/simplifies
them with read-only PostGIS operations, and atomically publishes an ignored
local display package. Replays use verified cached inputs and report `unchanged`.
See the [map API and preparation guide](api/election-map.md) for hashes, vintage
limitations and paths. Tables remain available when boundaries are unprepared.

The frontend uses loopback port 5173 and proxies `/api` to `http://api:8000` in
Compose. Requests stay on the same origin, without browser database credentials
or backend CORS changes. If Docker Desktop misses a Windows source change, run
`docker compose restart frontend`. Rebuild its image after package/lockfile or
TypeScript configuration changes. Host `node_modules` is not portable to Linux.

For host development with Node 24:

```powershell
Set-Location frontend
npm ci
npm test
npm run build
npm run dev
```

For backend map checks in a Python 3.12 environment, install
`backend/requirements-dev.txt` and run the following from `backend/`. Set
`TEST_DATABASE_URL` to an existing disposable PostgreSQL database whose name
ends in `_test` to include migrated integration tests; without it those tests
are explicitly skipped.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_election_map.py tests/test_election_map_postgres.py tests/test_boundaries.py -q
```

The host proxy defaults to `http://127.0.0.1:8000`; set `$env:API_PROXY_TARGET`
before Vite if needed. Development/preview servers are local verification
tools. Production hosting must proxy `/api` and serve `index.html` for client
routes while preserving API errors. External publication is outside this task.

## Routes and map interactions

| Route | Behavior |
| --- | --- |
| `/` | Opens `/map?year=2008`, preserving supplied shared filters |
| `/map` | Federal election map; presidential states drill into counties, reporting units open details |
| `/contests` | Paginated modeled contests with source/publication labels |
| `/contests/:contestId` | Published returns scoped by canonical contest UUID |
| `/candidates` | Published result rows, with separately labeled anonymous buckets |
| `/candidates/:candidacyId` | Candidacy selection shell; full profile remains unavailable |
| Other paths | Accessible page-not-found state |

Shared filters remain `year`, `office`, `stage`, `state_code`, `jurisdiction_id`
and `reporting_level`. URLs preserve reload/back/forward without local storage.
Applying filters returns to the section overview and removes page/entity context.
Record pages use 25 rows per page and TOTAL mode; discovery omits result-only
parameters. Office names are exact, case-insensitive API names; suggestions are
not a complete catalog. Year refers to election calendar year.

The map defaults omitted year/office/stage to 2008 / `U.S. President` / general.
For that election the national view uses FEC states and state selection uses
the separate canonical county publication. Selection preserves the requested
office, year and stage. House requests use congressional-district reporting;
Senate requests use state reporting. The API supplies the supported drill-down
level. Missing releases/boundaries remain explicitly unavailable: other years
and offices never inherit 2008 geometries or votes. Only the 2008 state/county
display package is currently prepared. House/Senate data acquisition remains
separate work; this refactor does not supply missing results or district shapes.

Reporting-unit selection uses canonical `jurisdiction_id` plus map-only
`map_unit` (a two-digit state, four-digit district or five-digit county GEOID).
The latter also selects boundaries with no published returns.
Breadcrumbs restore state/nation context. Candidate links retain county/contest
context; anonymous buckets never become profile links. Table sorting is local
presentation state. Albers USA places the contiguous states, Alaska and Hawaii
in one standard composite view; Alaska is scaled down. D3 handles projection
clipping and antimeridian rendering. Outlying islands may be clipped, with all
reporting units retained in tables. RFC 7946 rings are normalized to D3's
spherical winding convention in a render-only copy; source geometry is unchanged.
Hover/focus shows vote/share/margin tooltips. SVG paths and table buttons support
pointer/keyboard selection. Selected reporting units are framed automatically.

## Metrics, coverage and sources

Shares include all published candidate/anonymous buckets in the unit denominator.
Margins show the top two named candidates' vote difference and that difference
as a percentage of the same denominator, displayed with `%`. The existing
`margin_pp` API field and arithmetic are retained. Missing, zero, tied and indeterminate results
remain distinct. No turnout or electoral-vote metric is calculated. Colors
identify source candidate labels through stable label colors without inventing
party affiliations. The legend is derived from the returned candidates. See the
[API metric definitions](api/election-map.md).

County maps include a statewide overview above the map, with candidate
votes/shares, reported votes, leader, margin and state publication provenance.
It uses the existing map API with `reporting_level=state` and the same
year/office/stage/state filters, excluding selected-county UUIDs. It remains
statewide during county selection and does not substitute county sums when
state authority is missing. Loading/errors/retry are isolated from the county
map. Separate requests can observe different publication timestamps; each source
retains its own provenance.

State and county publications are prominently labeled as separate, non-additive
sources. PARTIAL remains visible even when every polygon in a state has returns;
county verification is not inferred. Source labels retain release/version/hash,
retrieval/publication timestamps, publication scope/counts, geographic reference
and correction lineage. County details expose reference IDs/vintages, observation
and correction IDs. Statistical reference vintages do not imply legal dates.

The shared filters start collapsed, can be shown or hidden with a keyboard-accessible
button, and close after navigation (including applying filters and browser history).
Closing the desktop sidebar gives the map the full content width. Applied-filter
tags appear below the page content. The map uses a compact title and breadcrumb;
source separation notes appear in the lower source panel instead of above the results.

The map precedes the independent statewide summary. Branding, navigation and the
filter toggle share one compact header; map controls overlay the map. Projection
notes expand from its attribution footer. Summary metrics share a row with the
heading, the leading candidate is marked on its candidate result, and cards,
tables and panels use tighter spacing. Election context appears once beside the
page title. Coverage counts and publication warnings remain visible.

Boundary vintage is available in the source panel; expanded provenance includes archive
URLs/hashes and display checksum. State joins require the published canonical
jurisdiction's compatible state reference. County/district joins check reference
identity, state, GEOID, grain and vintage. The API stamps matched canonical IDs
onto features; the frontend independently checks GEOID/state/canonical identity
and rejects ambiguous matches. Joins retain
unmatched result units in tables. The live audit found all 3,112 published county
units matched geometry; 30 polygons lacked published returns: 28 Alaska units,
Kalawao (HI), and St. Louis (MN). These are publication gaps, not zero votes.

Semantic landmarks, form labels, focus indicators, skip navigation, route focus,
table headers/captions, status announcements and retry remain in place. Source
links permit HTTP(S) only; React renders source text without HTML. Selection
changes abort stale requests and late responses cannot replace current data.
Invalid deep links and malformed responses are explained.

## Validation and remaining dependencies

Executed with Python 3.12, Node 24 and PostgreSQL 18:

- 73 frontend tests covering shell behavior, collapsible filters, map/summary ordering, metrics, federal selection/legend,
  Albers projection/winding, exact identity joins, SVG interaction, drill-down,
  history, missing/zero/unmatched units, sorting, retry and stale responses.
- Strict TypeScript and production build: separate geographic bundle about
  217 kB (87 kB gzip) including the physical-water asset and popovers, with no large-chunk warning. Full dependency audit
  reported no known vulnerabilities.
- 256 Python tests, including migrated PostgreSQL map/API integration, pinned
  boundary replay/corruption failures, scope rejection and existing regressions.
  One upstream Starlette/httpx deprecation warning remains.
- Headless Edge: all 51 state SVG canonical identity matches, actual state/county
  clicks and tooltips, county reload/history, missing-data keyboard selection,
  an unavailable 2024 House selection, and 375px mobile layout. Screenshots were
  inspected; no uncaught page errors or document overflow occurred.
- All 51 state drill-down responses audited: 9,336 county rows / 130,679,051 votes
  preserved; FEC state totals remain 131,313,820. Shares, margins, publication
  consistency and geographic coverage checked.
- Official boundary preparation/replay: 51 state/DC and 3,142 county polygons,
  valid PostGIS output, zero repairs, second run `unchanged`.

Ignored evidence is under `artifacts/election-map/`; temporary Playwright tooling
remains under `artifacts/browser-tools/`. These are not runtime dependencies.
Full cross-browser/screen-reader/performance acceptance remains QA-003. General
PostGIS boundary persistence, multiple vintages, tiles and 119th House geometry
remain DATA-007/API-002/UI-003; full race/person/finance profiles remain
API-003/UI-004/UI-005. County publication gaps/verification remain data work.
No migrations or publication writes were made.

Official references: [D3 Albers USA](https://d3js.org/d3-geo/conic#geoAlbersUsa),
[D3 spherical winding convention](https://d3js.org/d3-geo),
[Census 2008 TIGER documentation](https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2008/TGRSHP08.pdf).

# 2024 House map update

The modular map page now supports the published 2024 House data with pinned
119th Congress display geometry, a source-party legend, district details and
modeled race links including missing-vote contests. See the
[House map guide](house-map.md) for preparation, display semantics and validation.
