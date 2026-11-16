# Modular election map: 2024 House base case

Open [2024 House districts](http://localhost:5173/map?year=2024&office=U.S.+House&stage=general&reporting_level=congressional_district).
The page uses the existing election map route, shared SVG geography renderer,
tooltip, results table, URL filters, and contest detail pages. The two example
links switch between House 2024 and President 2008 without retaining incompatible
district/county selections. No new database migration or results publication is needed.

Previously the map components supported district selections, but only 2008
state/county display shapes were prepared. The House result publication was
available, with 436 modeled contests and two missing-vote races. A national
candidate-name legend was impractical for the House's many separate contests.

## Boundaries and provenance

The preparation command now accepts `--year 2024` and creates national and
state-scoped congressional district objects using the
[Census 2024 119th Congress cartographic file, 1:500,000](https://www.census.gov/geographies/mapping-files/2024/geo/carto-boundary-file.html).
Its source ZIP is
`https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_cd119_500k.zip`,
SHA-256 `2b4238aed7e865df75d0c9cfcd8dffa1b79007b24519ecc4b213e683078b031a`.
The pinned archive is cached through the existing acquisition code. PostGIS
checks validity, transforms NAD83 to WGS84, simplifies polygons and reduces
coordinate precision using the existing display policy. The source and generated
object hashes, retrieval time, explicit Congress/vintage and repair counts are
retained in `data/boundaries/2024.json`. Identical replay leaves it unchanged.

The package contains 435 voting districts plus DC; out-of-scope territories and
undefined district areas are excluded. It declares its supported reporting level,
so a House package cannot substitute for state or county shapes. No canonical
geography or vote records are rewritten. General PostGIS geometry persistence,
tiles and additional historical boundary vintages remain separate data work.

## Display semantics

`UnitedStatesMap` remains independent of elections. `GeographyMap` supplies the
election data, identity checks, colors and tooltip. House colors use explicit
source-backed party labels, including fusion nominations, rather than guessing
party from candidate names. The existing candidate-label colors remain in use
for presidential maps. Multiple major-party labels and other/independent labels
have separate legend entries. Candidate labels and every ballot line's votes
remain available in the underlying results API.

The map displays **reported leaders**, not certified winners. Its inherited margin
definition is the difference between the top two named candidates divided by all
published vote categories. Ties, zero totals, missing counts, and cases where an
anonymous bucket could conceal the runner-up remain distinct. A single named
candidate without a supported runner-up has an undetermined comparison; a margin
is not fabricated. Ranked-choice returns preserve MEDSL's source conventions;
the import does not supply uniform rounds or certified outcome fields.

FL-20 and OK-03 keep null counts. Their polygons receive exact canonical district
IDs and modeled contest links despite having no published returns. Selecting a
district shows its source-backed candidates, shares, margin where supported, and
a **View contest returns** link. Reader-facing source notes are collapsed;
internal identifiers and unit lineage are omitted from the map display.
Selecting a district replaces the overview table with its candidate details
to avoid repeating results. Keyboard Enter/Space,
URL selection, reload, breadcrumbs, zoom and the accessible table remain shared
with the presidential page. Albers USA clips some distant islands; their units
remain in the table. See [the House data contract](data/house_returns_2024.md).

## PowerShell preparation and verification

Run from the repository root with the existing Compose stack running:

```powershell
docker compose run --rm --no-deps -v ./backend:/app api sh -c 'python -m pip install -q --root-user-action=ignore -r requirements-geography.txt && python -m ingestion.boundaries --year 2024'
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
$map = Invoke-RestMethod 'http://localhost:8000/api/v1/election-map?year=2024&office=U.S.%20House&reporting_level=congressional_district'
$map.coverage
```

Expect 436 boundary units, 434 with returns, two missing counts and zero result
units without geometry. The sum of the map's source-native vote categories is
148,310,611; it includes DC and is not a national two-party or turnout metric.
The existing published House batch and all presidential publications are reused.

For backend tests, the established runner creates isolated schemas in a disposable
database whose name ends with `_test`:

```powershell
$testOutput = '/app/data/house-map-tests-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
docker compose run --rm --no-deps -v ./backend:/app -e GEO002_TEST_OUTPUT=$testOutput api sh -c 'python -m pip install -q --root-user-action=ignore -r requirements-dev.txt -r requirements-research.txt && python tests/run_county2008_tests.py tests --tb=short'
```

Verification on November 16, 2026: 75 frontend tests and strict TypeScript/production
build passed. The Python/PostgreSQL suite passed 292 tests. The pinned package
prepared 436 polygons with zero repairs and replayed unchanged. Headless Edge
verified all 436 SVG identities against the live API, national/state selection,
keyboard district selection, reload, modeled race links including missing-vote
FL-20, and a 375px layout without document overflow or page errors. Screenshots
were inspected. Ignored local evidence is under `artifacts/house-map/` and
`data/house-map-final-tests/`. Broader browser/screen-reader/performance QA remains
separate acceptance work.
