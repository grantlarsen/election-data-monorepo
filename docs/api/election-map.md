# Election map display API

`GET /api/v1/election-map` supplies the map page's read-only display contract.
It reuses existing published result queries, candidate-total/ballot-line
precedence and FEC authority integrity checks. All internal pages share the
request's repeatable-read, read-only database transaction. No migration,
canonical writes or publication changes are required.

## Selection and response

| Parameter | Default / meaning |
| --- | --- |
| `year` | `2008`; election calendar year |
| `office` | `U.S. President`; exact supported federal contest/office name, case insensitive |
| `stage` | `general` |
| `state_code` | Optional state/DC scope |
| `reporting_level` | Optional `state`, `county`, `congressional_district`. Default: presidential nation→state/county, House→district, Senate→state |
| `jurisdiction_id` | Optional published reporting-unit selection |

Year, supported federal office and stage are passed to existing result accessors
without resetting to the base case. Supported names are `U.S. President`, its
canonical `President of the United States` alias, `U.S. House` and `U.S. Senate`.
Other offices and a county request without state scope return
`unsupported_selection`. Invalid query values return 422. Unknown jurisdiction
UUIDs return `no_matching_published_results`, without silently falling back.
Selection retains the surrounding map/coverage context.

Boundary lookup uses the selected year and grain. The current prepared package
supports only 2008 states/counties. Missing district/year packages return
`boundaries_unavailable`; they never reuse county polygons or another vintage.
The query path supports congressional-district results already represented by
the existing result API, but does not ingest unpublished House returns or create
district boundaries. State queries retain the existing state-authority accessor;
no county/district aggregation manufactures missing Senate/state publications.

The response contains:

- `features`: simplified GeoJSON boundaries, including units without returns.
  Feature IDs are zero-padded Census GEOIDs.
- `units`: summaries keyed by the same `id`, including result units without
  matching polygons. Canonical jurisdiction, contest and publication identifiers
  are retained when available. `geometry_match` distinguishes matched units,
  boundary-only units, missing references and missing geometry.
- `drill_down_level`: county drill-down for presidential state maps, otherwise null.
- `publications`: existing release/checksum/coverage/correction provenance.
- `boundary`: archive URLs/hashes, retrieval timestamps, display hash, CRS,
  vintage, transformation parameters and repair counts.
- `coverage`: `boundary_units`, `units_with_results`, `missing_results` (boundary
  units without returns), and `results_without_geometry` (result units without
  an exact display GEOID). Counts apply to the full map scope.
- `metric_note` and `source_note`: the definitions and non-additivity caveat
  displayed by the frontend.

County/district joins use the published result's exact `GeographicReference`,
checking canonical jurisdiction, kind, state/FIPS prefix, GEOID length and vintage.
State joins require the actual published canonical jurisdiction's compatible
state reference, not only its postal code. Missing state references retain the
result as unmatched without painting another polygon. Boundary GEOID/state/grain
validation and feature-level canonical IDs support independent presentation
checks. Names, row positions and successor codes never authorize a match.
Conflicting scopes/identities fail closed with 503. Raw errors are not exposed.

## Metrics and missing data

State results use the existing FEC publication; counties use the separate
canonical county publication. County totals are never substituted for an absent
state authority or added to it. State source buckets do not acquire invented
candidacy or party identities.

```text
reported votes = sum(published candidate and anonymous bucket votes in the unit)
candidate share (%) = candidate votes / reported votes * 100
margin (votes) = leading named candidate votes - runner-up named candidate votes
margin (pp) = margin votes / reported votes * 100
```

These are shares of reported votes, not turnout. Publication-level PARTIAL
coverage does not certify completeness of individual counties. Missing records
have null totals; stored zeros remain zero with null shares. A tie has zero
margin and no single leader. Fewer than two named candidates, or an anonymous
bucket large enough to conceal the runner-up, produces an indeterminate margin.
No turnout or electoral-vote metric is returned.

## Preparing boundaries in PowerShell

After the normal database/migration setup, from the repository root:

```powershell
docker compose up -d --build
docker compose exec -T api pip install -r requirements-geography.txt
docker compose exec -T api python -m ingestion.boundaries
Invoke-RestMethod 'http://localhost:5173/api/v1/election-map?year=2008'
Invoke-RestMethod 'http://localhost:5173/api/v1/election-map?year=2008&state_code=NY'
```

The optional `pyshp` reader is needed only during preparation. The runtime API
reads JSON using the standard library. The Docker image includes the optional
requirements file, without installing the reader by default. Reinstall it after
recreating the API container if another preparation run is needed.

Preparation uses the existing acquisition cache and pins two official archives:

| Archive | SHA-256 |
| --- | --- |
| `tl_2008_us_state.zip` | `7e384585322cf39de8bfac2723c5cbba709da65050cee51ebe16460bcb007a8e` |
| `tl_2008_us_county.zip` | `956511da5ad39ca31ed3134c7beb0d26092ab647995a5db75920234a19eeba21` |

Sources: [Census 2008 TIGER archive](https://www2.census.gov/geo/tiger/TIGER2008/)
and [official technical documentation](https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2008/TGRSHP08.pdf).
These are current-geography files, not the similarly named `county00`/`state00`
files. Census describes this vintage as generally January 1, 2008; it is not an
election-day boundary certification. Later 2008 Alaska changes are not retrofitted.

Preparation reads NAD83/Latin-1 shapefiles, excludes territories outside the
50-state-plus-DC presidential scope, transforms EPSG:4269 to 4326, simplifies
each polygon at 0.005 degrees with topology preservation, and reduces precision
to 0.00001 degrees. Invalid inputs are explicitly repaired with PostGIS
`ST_MakeValid` and counted; invalid/empty outputs reject the build. Per-polygon
simplification does not guarantee shared-edge topology. These shapes are for
display, not measurements or spatial redistribution of votes.

The current package contains 51 state/DC and 3,142 county/equivalent features. Generated
objects and `data/boundaries/2008.json` are ignored local data, persisted through
the existing Compose data mount. Every object is checksum-verified on read.
The manifest is replaced atomically after validation. Identical cached inputs
report `unchanged` and preserve its timestamp. Raw files remain under
`data/ingestion/raw/census_tiger_boundaries/2008/`. Preparation accepts
`--data-dir` and `--output`; a custom API path uses `BOUNDARY_DATA_DIR`.

With no package, `boundaries_unavailable` retains results for tabular use. A
damaged package returns 503. API requests never download or change data.
The display adapter supports year/grain lookup and generic federal election
selection; only the pinned 2008 state/county package is prepared. Full PostGIS
boundary persistence, multi-vintage cataloging, 119th district ingestion, tiles
and a general geometry API remain separate DATA-007/API-002 work.
