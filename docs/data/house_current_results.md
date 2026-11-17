# Current House results and daily cache

The House header now opens `/house/2026/results`. Direct district pages use
`/house/2026/races/CA-01` or `/house/2026/races/WY-AL`. The page follows the Senate
title, seat bar, compact tables, source panel, timestamps and delayed-update
patterns. State/status/district filters live in the URL. National seat accounting
does not change when filtering.

Previously, the repository had MEDSL 2024 House observations, canonical
publication, and a 119th Congress district map. The 2026 House link was a
placeholder. The existing Senate provisional-results validator and durable
cache are now shared by both chambers; historical observations, publications,
identities and applied migrations remain compatible. No migration or new
dependency is required.

## Source and scope

[Call the Map's downloads](https://www.callthemap.com/results/data) provide
`https://www.callthemap.com/results/data/2026/races.csv`, the adjacent
`manifest.json`, and a [data dictionary](https://www.callthemap.com/results/data/2026/README.txt).
This is a third-party compilation of state and county election-office counts,
partly via [civicAPI](https://civicapi.org), with CC BY 4.0 attribution. Each
district retains the original evidence URL, count-update time, source-read time,
call time, candidate/party labels and original CSV row ordinals.

The feed supplies the November 3, 2026 election's 435 voting House districts.
The [Census 2020 apportionment table](https://www2.census.gov/programs-surveys/decennial/2020/data/apportionment/apportionment-2020-table01.pdf)
establishes the expected seat counts per state. Source IDs use `CA-01` and
`AK-AL`; the adapter exposes district code `00` for the six at-large states.
Unknown district identifiers fail validation. Delegates, resident commissioners,
separate special elections and runoffs are outside this source adapter's scope;
another election stage must receive a distinct scope rather than overwrite a
general-election contest.

The default view displays geographic district results. A **Map / Tile grid**
toggle switches to one tile per seat, with explicit source winners or uncalled
status; `?view=grid` selects the grid, while `?view=map` remains supported. Switching
views preserves state/district selections, and clearing filters preserves the
current view. Full district pages retain
every source row. Compact overview tables reuse the existing minor-candidate
display grouping without changing API/source votes or totals. Named candidates
link to registered source-scoped UUID profiles in tables and map/grid popovers.
Anonymous categories and synthesized Other rows remain unlinked. No canonical
people or financial identifiers are guessed.

## Geographic map and small-state inset

The map reuses `UnitedStatesMap` for Albers USA projection, hover/focus candidate
details, keyboard district selection, zoom and pan. Selecting a district fits
its state and opens its results below. Both views use explicit source winners;
uncalled districts remain gray on the map and striped in the tile grid.
`HousePopover` adapts the source rows to the same `ElectionTooltip` used by
Senate and presidential maps: shared header, candidate avatar fallbacks, party
colors, share bars, winner badges and source footer. Minor candidates follow
the shared grouping rule rather than a fixed five-row cutoff. Unavailable
counts remain unavailable in candidate cards; a call can still be displayed
for an unopposed candidate with no vote counts. Candidate profile IDs are
registered through existing election entities. Portraits use the reviewed,
source-scoped media catalog described in [candidate portraits](candidate_portraits.md).
The provisional House endpoint supplies no margin
summary, so the shared footer labels that metric unavailable.
The popover refactor passed the 269-test frontend suite, focused checks after
the final header adjustment, and the production build. Desktop/mobile browser
checks covered candidate cards, race links, keyboard dismissal, null-count
races and viewport bounds. Screenshots are retained under
`artifacts/house-current/popover-shared-*.png`.
State/status filters affect the result tables; the state filter also fits the
map. The national seat bar always retains national accounting.

The right-side inset lists VT, NH, MA, RI, CT, NJ, DE, MD and DC using the same
small-state list as the presidential Electoral College map. Each voting
district has its own tile (40 across those eight states). DC has a separate
nonvoting-delegate/out-of-scope tile, without a fabricated count or winner.
On narrow screens the inset wraps below the map. Missing boundaries provide a
retry while leaving the grid and result tables usable.

`GET /api/v1/house/2026/boundaries` reads the verified local package through the
existing boundary loader, checks all 435 expected district GEOIDs plus DC's
`1198`, and exposes election-scoped source race IDs. It never downloads or
rewrites canonical geography. The prepared package uses all 51 state/DC
[Census 2026 TIGER/Line CD120 archives](https://www2.census.gov/geo/tiger/TIGER2026/CD/).
The source URLs and SHA-256 pins are in
`backend/ingestion/catalog/election_boundaries.json`; original archives,
retrieval timestamps, validation counts and output checksums remain in the
existing acquisition cache and `data/boundaries/2026.json`.

The [Census November 10 correction notice](https://www.census.gov/programs-surveys/geography/technical-documentation/user-note/tiger-geo-line.html)
confirms the Missouri CD120 shapefile was corrected. The pinned Missouri
archive is `ad6d2f736622e0f3a7bc578737c424a9ec696419a49bde21877acc065fa11d1d`.
The [specific CD120 user note](https://www.census.gov/programs-surveys/geography/technical-documentation/user-note/120cd.html)
supersedes older release pages that still describe regeneration as pending.
No 2024 map is substituted for redrawn 2026 districts.

The existing preparation CLI validates polygons with PostGIS, transforms NAD83
to WGS84 and simplifies at 0.005 degrees with five-decimal precision. Preparation
produced 436 valid polygons with zero repairs and excluded three undefined
district areas; rerunning was unchanged. Full national display-object SHA-256:
`8a984aa3da3e7fc337df7fdb49947b461a4aea28533f6618b4fdf961c2a46cb8`.
These are generalized display boundaries, not measurement or vote reconstruction
geometry. New boundary preparation uses the existing optional `pyshp` dependency.

## Validation and result semantics

`ingestion/current_results.py` holds the shared Polars parser and source
contract; `current_senate.py` and `current_house.py` declare chamber scopes.
The Senate error alias and public cache functions remain compatible. Existing
Senate cache rulesets and archives can still be read without migration.

The parser rejects malformed/negative counts, unsafe evidence URLs, timestamps
without timezones, unknown statuses, duplicate candidate/party lines,
inconsistent metadata, incorrect contest totals and inconsistent winner flags.
Candidate sums must equal the source contest total. Supplied percentages must
agree within 0.02 percentage points. Vote corrections may decrease counts.
Other offices are counted as excluded, rather than ingested as House returns.

House counts and shares may be null when the entire source contest has no vote
counts. Partial missing counts block promotion; nulls never become zero. This
supports a source-called unopposed contest without inventing votes. A source
winner can earn a seat even when the vote count is unavailable. Zero votes
remain distinct from unavailable votes. Ranked-choice rounds are not identified
by the feed; no rounds, expected-vote percentages or winners are reconstructed.

`called` means a Call the Map media call; `final` means certification as reported
by that feed. Neither a lead nor a vote margin earns a seat. House control uses
explicit `won` outcomes in called/final races, accounts for all 435 voting seats,
leaves missing races uncalled and requires 218 seats for a party majority.
Independent/other winners receive their own count without a caucus assumption.

## Refresh and provenance

`app/services/current_results.py` shares the existing immutable archive,
checksum, writer lock, atomic last-good pointer and acquisition report policy.
`house_results.py` owns the House scheduler and seat accounting. The read-only
`GET /api/v1/house/2026/results` endpoint uses typed schemas, returns
`Cache-Control: no-store`, and never downloads data or writes PostgreSQL.
Provisional returns remain separate from canonical publications.

While the API runs, a cancellable lifespan task checks hourly and refreshes
after 24 hours. It also checks on startup. An unchanged upstream CSV checksum
avoids another CSV download, advances `checked_at`, and preserves `retrieved_at`.
An open browser checks the local snapshot every five minutes. No updates occur
while the API is stopped. Use the existing single API worker.

Durable default directory: `data/ingestion/current_house/`, relative to the
backend working directory; Compose's existing `./data:/app/data` mount persists
it. `HOUSE_RESULTS_CACHE_DIR` overrides the host-process location.

```text
raw/<sha256>.csv          Original full upstream CSV, including excluded offices
raw/<sha256>.json         Original source manifest
reports/<run-uuid>.json   Successful/failed validation and acquisition reports
latest.json              Atomic last-good pointer and parser version
last_attempt.json        Most recent upstream attempt
refresh.lock             Interprocess API/CLI writer lock
```

Reports distinguish accepted/excluded/rejected rows and inserted, updated,
unchanged and removed source candidate/party lines. Unknown failed-run counts
are not invented. Network, checksum, schema, license and reconciliation failures
retain the last good snapshot. Previously present contests disappearing or a
manifest moving backwards block promotion. Missing/corrupt local inputs produce
503; stale or failed updates show explicit warnings. All archived inputs are
verified again on reads and offline replay. Archives from rejected downloads
remain available for investigation. Back up this directory; retention/deletion
is not automated. Cached returns are intentionally outside Git.

`HOUSE_RESULTS_AUTO_REFRESH=1` is enabled by default and passed through Compose.
Set it to `0` in `.env` and recreate the API only if an external daily scheduler
will own the CLI. No additional scheduler or service is needed.

## PowerShell operation

From the repository root, with the existing stack available:

```powershell
docker compose up -d api frontend
docker compose exec -T api python -m ingestion.house_current
docker compose exec -T api python -m ingestion.house_current --force
docker compose exec -T api python -m ingestion.house_current --verify-only
# Prepare pinned map geometry once; repeat to verify deterministic replay.
docker compose run --rm --no-deps -v ./backend:/app api sh -c 'python -m pip install -q --root-user-action=ignore -r requirements-geography.txt && python -m ingestion.boundaries --year 2026 --office house'
$results = Invoke-RestMethod 'http://localhost:8000/api/v1/house/2026/results'
$results.races.Count
$results.control
$results | Select-Object checked_at, published_at, stale, refresh_failed, sha256
Start-Process 'http://localhost:5173/house/2026/results'
Start-Process 'http://localhost:5173/house/2026/results?view=map'
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
```

For Python 3.12 with existing development requirements installed, from `backend/`:

```powershell
python -m pytest tests/test_current_house.py tests/test_current_senate.py tests/test_senate_control.py -q
# Optional retained-input replay; unit tests otherwise remain offline.
$env:CURRENT_HOUSE_CACHE_DIR = '..\data\ingestion\current_house'
python -m pytest tests/test_current_house.py -q
```

## November 17, 2026 verification

The initial acquisition accepted 1,491 House rows across all 435 districts,
excluded 1,268 other-office rows from 2,759 input rows, and rejected zero rows.
The source manifest was generated at `2026-11-17T05:01:22Z`. Full CSV SHA-256:

`9056a058e6f0e3b9de37717bc0189efc455acca562efaa69cfe9b68e8863313a`

The feed marked 426 contests called, eight counting, and Wyoming final. FL-10
has a source winner with null counts. Seat accounting gives 256 Democratic,
171 Republican and eight uncalled seats. These are source calls, not a claim of
national certification. Wyoming's candidate votes independently match the
[official statewide summary](https://sos.wyo.gov/Elections/Docs/2026/Results/General/2026_General_Statewide_Candidates_Summary.pdf):
Chuck Gray 99,906; Lisa Kinney 61,689; Shawn Johnson 13,667; Jeffrey Haggit 7,961;
write-ins 1,031, totaling 184,254. That reference check does not independently
certify the other contests.

Offline replay succeeded. Forced refresh reported zero inserts/updates/removals
and 1,491 unchanged rows; daily reuse then avoided downloads. Backend source,
cache, API and related unit checks passed 181 tests (one optional Senate live
replay skipped). PostgreSQL/cache regressions passed 77 tests, with two optional
Senate retained-input tests skipped. The House retained-input replay was
included. All 249 frontend tests and the TypeScript/production build passed.
Headless Edge checks at 1440px and 375px verified the header, all 435 district
tiles and tables, keyboard selection, URL reloads, complete district rows,
missing-count presentation and national accounting. No page errors or document
or table overflow were observed. Ignored browser evidence is retained under
`artifacts/house-current/`. The API was recreated with the new Compose setting;
the frontend dev server was restarted to clear a stale Windows-mounted module.

Map follow-up verification: 142 backend tests passed, including the retained
Census package and House snapshot; the optional Senate snapshot replay was
skipped. All 259 frontend tests and the TypeScript/production build passed.
Browser checks verified all 436 source/geometry joins, all district
colors, 40 clickable inset districts plus DC, grid/map switching, keyboard
selection, URL reloads, zoom and desktop/mobile layout without overflow or page
errors. Evidence is under `artifacts/house-current/map-*`.

## Candidate profiles and incumbency

`app/services/house_entities.py` registers 435 source-scoped contests and 1,362
named candidacies using existing election tables. The 129 anonymous categories
receive no profile. Creation keys pin source/year/race/exact label/party, so vote
corrections preserve UUIDs and replay creates no duplicates. Election-scoped
logical district jurisdictions do not assert equivalence with historical
boundaries. DataSource, SourceRelease and IngestionRun records preserve the CSV
checksum, raw path, source row crosswalk, district scopes and incumbent evidence.
No canonical person, FEC identity, committee, finance total or vote publication
is inferred. No migration is required.

House read models now expose `contest_id`, `candidacy_id`, `kind`, `incumbent`
and evidence. Candidate profiles expose additive `provisional_house_election`
data with a complete district table and selected-candidate highlighting.
Named labels link to profiles in compact/full tables and map/tile popovers.
Anonymous and synthesized Other rows remain plain text.

`ingestion/catalog/house_incumbents.json` contains 360 reviewed source-row
annotations against the [House Clerk's member XML](https://clerk.house.gov/xml/lists/MemberData.xml),
published November 3, 2026. The archived roster and review proposals are under
`data/house-candidates/research/`; its SHA-256 is retained in the catalog.
Explicit aliases, state and party are reviewed separately from canonical person
matching. Changed election districts do not imply a member stopped being an
incumbent. Similar surnames, including Trever/Troy Nehls and Patty/Chuy Garcia,
are kept separate. Badges describe House members entering this election, not
projected winners. The same plain-text badge appears beside names in tables and
popovers; unknown annotations remain unknown.

The existing daily job registers source identities after refreshing/reusing the
cache. The CLI does the same; `--cache-only` skips registration and `--verify-only`
remains offline and read-only:

```powershell
docker compose exec -T api python -m ingestion.house_current
docker compose exec -T api python -m ingestion.house_current --verify-only
```

Profile follow-up validation: 271 frontend tests and strict production build
passed. Python 3.12/PostgreSQL checks passed 82 tests, with one optional House
retained-input replay skipped. They cover scoped keys, category exclusions,
incumbency aliases, idempotency, stable IDs, source audit and working API profiles.
Live registration inserted 1,362 candidacies; replay reported 1,362 unchanged.
Browser validation fetched all 1,362 candidate API profiles and verified their
race IDs, counts and incumbent annotations. Desktop/mobile checks at 1440px and
375px verified table/popover profile links, plain-text badges and highlighted
current-candidate rows without overflow or page errors. Person identities and
financial totals remained unresolved. Evidence is retained under
`artifacts/house-current/candidate-links-*`.

Remaining scope: direct per-state source adapters, independent nationwide
certification reconciliation, reviewed canonical person matching and canonical
House vote publication.

## Reviewed candidate headshots

The House catalog adds 529 checksum-pinned portraits across 428 districts and
all 50 states, using congressional public-domain images and individually
reviewed Commons files. Candidate pages show the portrait with linked credit
and reuse terms; results tables and shared map/grid popovers show thumbnails.
Missing or failed images retain their fallback, and anonymous categories never
receive a person's photo. Matching requires the exact source, year, race, name
and party, independently of canonical person matching.

The existing portrait replay CLI now handles House and Senate catalogs together.
No database migration, new dependency or daily image search is required. The
ordinary results refresh continues to update counts without reassigning photos.
See [candidate portrait operation and validation](candidate_portraits.md) for
PowerShell commands, source provenance, coverage limits and verification evidence.
