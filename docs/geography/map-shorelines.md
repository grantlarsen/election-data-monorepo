# Great Lakes display correction

The initial map filled complete 2008 TIGER jurisdiction polygons. These include
legal state/county water areas, so Michigan's peninsulas merged visually and
Wisconsin/Minnesota extended into Lake Superior/Michigan. Changing the projection
did not address that defect. A read-only PostGIS check confirms that the original
Michigan polygon covers longitude -86.5, latitude 44, a point in Lake Michigan.

Census distinguishes legal TIGER boundaries from shoreline-clipped cartographic
products: [TIGER product guide](https://www.census.gov/programs-surveys/geography/guidance/tiger-data-products-guide.html).

The correction retains all historical jurisdiction geometries, identifiers and
election results. A separate physical-water layer renders above the jurisdiction
fills in the same projection, suppressing water fills/borders and intercepting
pointer events so a lake cannot select an underlying jurisdiction. Islands and
holes are retained by the source polygons. The layer applies to national and
county views and has its own attribution. It is a generalized physical display
reference, not a certification of 2008 shoreline locations or a replacement
jurisdiction vintage. Ocean shorelines and other inland lakes are outside this fix.

Source: [Natural Earth 1:10m lakes](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-lakes/),
version 5.0.0; public-domain physical cartography. The six selected features are
Lakes Superior, Michigan, Huron, Erie, Ontario and Saint Clair. The tracked asset
`frontend/src/geography/data/great-lakes.json` records download URL, version,
retrieval timestamp, role and archive SHA-256:
`0803a06f9c3cb4671d89b68c48b142aad9366ba40f665245e12a913fbc61722a`.

Normal application startup uses the checked-in asset without downloading data.
To regenerate with the optional geography dependencies installed, from the root:

```powershell
docker compose exec -T api python -m ingestion.map_water --output /app/data/great-lakes.json
docker compose cp api:/app/data/great-lakes.json frontend/src/geography/data/great-lakes.json
```

Preparation uses the existing immutable acquisition cache, verifies the pinned
checksum and embedded version, requires exactly six named lakes, and produces
deterministic output for cached inputs. It does not access or modify election
tables. The generic map accepts an optional caller-provided water layer and
keeps election-specific responsibilities in its adapter.

Validation executed: 58 frontend tests and strict production build; pinned water
preparation/replay/checksum-failure test; Edge SVG hit-testing at a known Lake
Michigan coordinate, all 51 state identity checks, state/county drill-down and
mobile smoke tests. Regression assertions cover lake interiors, both Michigan
peninsulas, Wisconsin/Minnesota land and blocked water selection. The corrected
national screenshot was inspected under `artifacts/election-map/national.png`.
