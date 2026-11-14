# Geographic remediation evidence inventory

| Source | Official URL / machine download | Coverage and role | Caveat |
|---|---|---|---|
| U.S. Census 2024 Gazetteer | https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2024.html | 2024 place, county, legislative district identifiers. National ZIP, tab-delimited files. | 2024 reference only, not proof of historical validity. U.S. government public-domain data. |
| 2024 places ZIP | https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip | Optional programmatically ingested Census place GEOIDs, including Kansas City `2938000`. | Does not equate places to counties; ZIP content and SHA-256 recorded by ingestion framework. |
| Census county name/code change log | https://www.census.gov/programs-surveys/geography/technical-documentation/county-changes.2010.html | Dated historic county-equivalent changes. | Must distinguish legal effective date from CBP source product period. |
| Census ACS 2015 geography changes | https://www.census.gov/programs-surveys/acs/technical-documentation/table-and-geography-changes/2015/geography-changes.html | Shannon `46113` → Oglala Lakota `46102` and Wade Hampton `02270` → Kusilvak `02158`. | A code-change event is not a complete time-varying boundary history. |
| Federal Register Connecticut county-equivalent change | https://www.federalregister.gov/documents/2022/06/06/2022-12063/change-to-county-equivalents-in-the-state-of-connecticut | Eight historical counties replaced by nine planning regions. | No one-to-one county-to-planning-region allocation. |
| Official Alaska election results | https://www.elections.alaska.gov/election-results/ | Election district reporting and historical Alaska election returns. | Individual source-year district boundaries, notably District 99, must be verified separately. |
| Census Missouri incorporated places | https://tigerweb.geo.census.gov/tigerwebmain/Files/bas26/tigerweb_bas26_incplace_mo.html | Confirms present-day Kansas City place GEOID `2938000`. | 2026 web reference does not establish every earlier election-year place code. |

All U.S. Census Bureau reference datasets used here are federal government works ordinarily in the U.S. public domain. Other source documents retain their own publication notices. The standalone CSV candidate catalogs are locally compiled editorial **review queues**, not official government datasets or approved mappings.

To add a second independent reference source, implement `ingestion.adapters.<source_name>.Job` using `SourceInfo`, the existing acquisition/cache and raw-hash layer, Polars parsing, source validation, and a transactional, idempotent loader with `SourceRelease`/`IngestionRun`; then add a vintage-aware resolver rule requiring identifier *namespace* agreement. Do not use a name-only join.
