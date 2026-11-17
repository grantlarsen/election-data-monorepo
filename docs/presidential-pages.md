# Presidential election pages

Open [presidential election discovery](http://localhost:5173/presidential), or
load `/presidential/2000`, `/presidential/2004`, `/presidential/2008`,
`/presidential/2012`, `/presidential/2016`, `/presidential/2020` or
`/presidential/2024` directly. Refresh and browser history preserve the selection.
The primary navigation links discovery; every election page links all seven years.

## Existing architecture and implementation

The frontend already supplied election discovery, paginated canonical returns,
candidate links, provenance, shared filters and a modular election map. The
[presidential data coverage work](data/presidential_coverage.md) supplied all seven
years' FEC state summaries, partial MEDSL county publications and the coverage API.
The missing layer was discoverable year-specific presentation of those contracts.

`frontend/src/PresidentialPage.tsx` adds discovery, shared year pages, state totals
and a separately loading coverage panel. `presidential.ts` centralizes the supported
years and URL context. `ResultsPage.tsx` extracts the existing canonical results
browser for reuse by presidential county pages and existing contest/candidate
routes. Common loading, empty, error, pagination and provenance components remain
shared. `presidential.css` adds the year navigation and coverage presentation.

No backend, database, migration, ingestion, publication or dependency changes are
needed. Existing sources, identifiers, metric definitions and boundary checks are
reused. A separate hosted deployment was not part of this repository task.

## Selection and API contracts

The path determines the election year and fixes `office=U.S. President` and
`stage=general` before any request. Conflicting inherited year/office/stage query
values are replaced in the URL. State, exact reporting unit, reporting level and
page offset remain shareable. Unsupported years and invalid selections receive
accessible explanations without data requests.

State totals are the default. The state view requests `/api/v1/state-results`
with year/office/stage and optional state/jurisdiction filters, 25 rows per page,
and no county-only reporting parameters. Source nominee labels and `OTHER` remain
source buckets, without inferred person or party identities. State links open
that state's county returns. The county view reuses `/api/v1/results` with
`reporting_level=county` and `reporting_mode=TOTAL`.

Election pages use local year links, State totals/County returns links, state
result links and map drill-down. There is no global filter panel or applied-filter
strip. Year links preserve the local state and reporting view while clearing
exact-unit and page-offset context. Header navigation opens a fresh section with
no inherited year, office, state or reporting-level selection.

`/api/v1/presidential-coverage` supplies election dates, publication availability,
county status/verification, exclusions, missing states, active-source mismatch
warnings and signed official-minus-county differences. Some SQL aggregate values
arrive as integer strings; the frontend accepts only safe integers before
converting for display. Null county votes remain unavailable, stored zero remains
zero and negative differences retain their sign. Exclusion counts describe the
whole publication or explicitly selected state; they are observation counts.
Coverage and result requests may observe different publication timestamps;
each result page retains its own source release and publication lineage.

Coverage errors and retries are independent of result loading. Empty returns do
not establish zero votes, and a complete state publication does not establish
complete county coverage. State totals and county returns must never be added.

## Maps and remaining data dependencies

The election map link carries the selected year, office, stage and state to the
existing map explorer. National maps show state totals; selected states open county
drill-down. The map API owns geographic compatibility and returns tables plus an
explicit unavailable-boundaries state when shapes are absent. No fallback to another
year or office is introduced.

All seven presidential state/county display packages are now prepared. The 2004
package explicitly discloses a historical display approximation; other years use
their pinned Census geography. The 2024 presidential layers coexist with House
districts. See the [boundary guide](geography/presidential_boundaries.md) for
sources, preparation, layer preservation and historical limitations.
All county publications remain partial and not independently verified; source
mode, duplicate, missing-value and geographic remediation remain data tasks.

## PowerShell verification

With the existing Compose services running and the presidential backend/data
prerequisites already prepared:

```powershell
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
Start-Process 'http://localhost:5173/presidential'
Start-Process 'http://localhost:5173/presidential/2024'
```

If Docker Desktop misses a Windows source change, run
`docker compose restart frontend`. External production hosting must preserve the
existing `/api` proxy and serve `index.html` for client routes; Vite already supports
direct routes and refresh in the local stack.

The new frontend tests exercise every year, direct URL remounts, pinned filters,
state/county navigation, contextual filters, history, pagination, map selection,
sources, partial/missing/zero coverage, signed integer-string aggregates,
sanitized failures/retries and late responses. Existing frontend suites also run.
Initial page validation on 2026-11-16 passed 139 frontend tests. The subsequent
boundary-loading fix passed **146 frontend tests**, 27 selected backend tests,
strict TypeScript and the production build; see the boundary guide.
Live headless Edge checks exercise all seven URLs and refreshes, NY county
drill-down, year-specific map availability, responsive layouts at
320/375/768/1440px, coverage retry and existing presidential/House/candidate flows.
Local browser evidence and screenshots are under ignored
`artifacts/presidential-pages/`; full screen-reader and cross-browser QA remain
separate acceptance work.
The live checks passed with no page errors or document overflow; desktop and
mobile screenshots were inspected.
