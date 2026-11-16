# Election research frontend

## Scope and existing architecture

UI-001 adds the application shell to the previously empty `frontend/` directory.
The existing election API, models and migration chain already supply discovery,
published candidate totals and source/reference/correction lineage. They are
reused without schema changes, new API endpoints, ingestion or publication writes.
The inspected migration head remains `d005county01`.

The React/TypeScript application uses Vite and React Router in declarative mode.
No state service, frontend database, map library or external hosting is needed.
The package lock pins dependencies; the Docker image uses Node 24. Official
references: [Vite setup](https://vite.dev/guide/) and
[React Router URL values](https://reactrouter.com/start/declarative/url-values).

## Run and verify in PowerShell

From the repository root with the existing `.env` configured and Docker running:

```powershell
docker compose config --quiet
docker compose up -d --build
Start-Process 'http://localhost:5173'
```

The frontend listens on loopback port 5173. Its development server proxies
`/api` to `http://api:8000` within Compose. Browser requests stay on the same
origin; backend CORS changes and database credentials in browser code are
unnecessary. API/database startup and migrations retain the existing setup.

```powershell
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
Invoke-RestMethod 'http://localhost:5173/api/v1/contests?year=2008&limit=1'
```

Source, index and Vite configuration edits are mounted for development. Rebuild
the frontend image after changing `package.json`, the lockfile or TypeScript
configuration. No host Node installation is required for Compose.

For development with Node 24 installed on Windows, use a fresh host dependency
installation; a Linux `node_modules` directory is not portable to Windows:

```powershell
Set-Location frontend
npm ci
npm test
npm run build
npm run dev
```

The host development proxy defaults to `http://127.0.0.1:8000`. Set
`$env:API_PROXY_TARGET` before starting Vite if that address differs.
`dist/` is a build artifact. Vite development and preview servers are local
verification tools, not a production deployment. A future production server
must proxy `/api` and return `index.html` for client routes while preserving
real API errors; external publication is outside this repository assignment.

## Routes and filters

| Route | Current behavior |
| --- | --- |
| `/` | Opens `/map?year=2008`, preserving supplied shared filters |
| `/map` | Explorer entry and explicit unavailable-boundaries state |
| `/contests` | Paginated modeled contests, with publication/source labels |
| `/contests/:contestId` | Published returns scoped by canonical contest UUID |
| `/candidates` | Published result rows, including separately labeled anonymous buckets |
| `/candidates/:candidacyId` | Candidacy selection shell and link back to its contest; explicitly unavailable full profile |
| Other paths | Accessible page-not-found state |

Shared query parameters are `year`, `office`, `stage`, `state_code`,
`jurisdiction_id` and `reporting_level`. Applied filters live in the URL, so
links, reloads, new tabs and browser back/forward preserve selection without
local storage. Unsubmitted form edits are drafts. Changing or clearing filters
returns to the section overview and removes the selected entity and page offset.
Section links preserve filters and reset pagination. `offset` persists only
within a paginated view. A selected candidacy link also carries `contest_id`
as navigation context; it is not a person identifier.

Year means election calendar year. Office is an exact, case-insensitive name
accepted by the existing API; suggestions are examples, not a complete office
catalog. The current presidential contest label is `U.S. President`. Any exact
canonical office name can be entered. State/DC selection scopes discovery;
an optional jurisdiction UUID selects an exact reporting unit. A human-readable
geographic search awaits a geography catalog API. Choosing a reporting level
does not claim that data or geometries exist for that level.

Discovery requests omit result-only parameters. Result requests specify one
reporting level and `TOTAL` mode, with 25 records per page. Unsupported years,
offices and geographies remain missing data. State authority totals are not
queried as a fallback and never added to county returns. There are no derived
national totals, shares, margins or turnout figures.

## Coverage, provenance and accessibility

Source labels include source name/version, download link, release ID/checksum,
retrieval/publication timestamps, batch/scope, reporting level/mode, geographic
reference release and correction lineage where supplied. Coverage counts retain
their **whole-publication** scope. PARTIAL remains visibly partial after filters;
county verification is not inferred. A COMPLETE publication label does not imply
that its counties have been independently verified.

Return rows preserve source candidate labels, candidacy IDs, anonymous buckets,
individual reporting units, observation/correction IDs and statistical reference
vintages. A reference vintage is not presented as a legal boundary date range.
Only named candidacies link to the selection shell; OTHER/write-in buckets do
not create person or candidacy identities. Stored zero votes remain visible.

The responsive shell includes semantic landmarks, associated form labels,
keyboard focus indicators, a skip link, route focus management, table headers
and captions, polite loading/missing-data status, assertive errors and retry.
Invalid deep links are explained without sending unsupported requests. Failed
requests expose friendly messages rather than raw response bodies. Requests are
aborted on selection changes, and late responses cannot overwrite the current
selection. Source metadata only creates HTTP(S) links.

## Validation evidence

Executed for this implementation:

- 42 Vitest/Testing Library checks passed: navigation, URL/history persistence,
  entity context, filters, pagination, zero/missing data, source/correction labels,
  stale-response cancellation, invalid URLs, malformed responses and retry.
- Strict TypeScript checking and the Vite production build passed, including
  inside the configured frontend image. A clean `npm ci` in the image passed;
  npm reported zero known vulnerabilities at installation time.
- All 50 existing API contract tests passed in the supported Python 3.12 image.
  One existing upstream Starlette/httpx deprecation warning remains. The same
  tests also passed in the host's Python 3.10 environment; the container result
  is the supported-runtime evidence.
- Headless Microsoft Edge smoke checks passed against the live read-only API:
  NY 2008 contest/returns, partial source labels, map → contest → candidacy,
  reload/back/forward, keyboard skip link and route focus, missing 2024 House
  returns, simulated 503/retry, and a 375px viewport without document overflow.
  No uncaught page errors occurred. Desktop and mobile screenshots were inspected.
- Compose configuration, frontend route HTTP 200 and the same-origin API proxy
  were verified. These checks did not mutate published data.

Local supplemental browser evidence and screenshots are under ignored
`artifacts/frontend/`; temporary Playwright tooling is under
`artifacts/browser-tools/`. These are diagnostic artifacts, not runtime
dependencies or part of the permanent frontend test command. Full cross-browser,
screen-reader and performance acceptance remains a separate QA task.

## Remaining dependencies

UI-001's shell/navigation/filter/source-label scope is implemented. Map geometry
and joins remain API-002/UI-002/UI-003 work; no illustrative polygons stand in
for authoritative historical boundaries. Full race details, person/candidate
profiles and campaign finance remain API-003/UI-004/UI-005 work. The candidate
selection shell does not fetch or verify a profile, and does not assert that an
arbitrary UUID identifies an existing candidacy. DATA-006 supplies 2024 House
returns. No migration or ingestion run is required for the shell itself.
