# Current Senate results and daily cache

The House results page now shares the source validation and durable cache
implementation through `ingestion/current_results.py` and
`app/services/current_results.py`. Senate scope, cache directory, parser version,
API shape and profile registration remain compatible. See the
[House results runbook](house_current_results.md).

The React page at `/senate/2026/results` replaces the Senate header's planned
2026 link. Historical MEDSL Senate ingestion, seat identities, migrations and
canonical publications already cover 2000–2024; they are reused unchanged for
historical research. There was no current-results acquisition or daily updater.

## Source and scope

[Call the Map downloads](https://www.callthemap.com/results/data) supply
`https://www.callthemap.com/results/data/2026/races.csv`, with the checksums,
sizes and row counts in the adjacent `manifest.json`. Its
[data dictionary](https://www.callthemap.com/results/data/2026/README.txt)
defines each field. This is a third-party compilation of state election office
counts, partly via [civicAPI](https://civicapi.org), rather than a direct national
government feed. The page credits both services and links each race's original
source. Downloads are CC BY 4.0; counts are public election records.

The [FEC calendar](https://www.fec.gov/resources/cms-content/documents/2026pdates.pdf)
sets the general election date to November 3, 2026. The
[Senate Class II list](https://www.senate.gov/senators/Class_II.htm) identifies
the 33 regular seats. Florida and Ohio fill Class III vacancies in special
elections; see the calendar's special-election notes and
[Ohio's writ](https://www.ohiosos.gov/globalassets/elections/directives/2025/directive-2025-54---writ-of-special-election-for-united-states-senate-election.pdf).
The source uses `SEN-FL` and `SEN-OH`; the adapter explicitly maps those two
2026 identifiers to specials. It does not infer class from a candidate's name.
Unknown identifiers fail validation instead of merging contests. This feed's
one-contest-per-state identifiers must be reviewed before adding other years,
runoffs, or a year with simultaneous regular and special races in one state.

The initial November 17, 2026 acquisition contains 35 contests and 257 Senate
candidate/ballot-line/bucket rows. The full source has 2,752 rows; 2,495 other-office
rows are explicitly excluded. All candidate sums reconcile exactly to their
contest totals. Raw CSV SHA-256:

`57b5b6389675882c101774741fda6803df1687453ad41d4e16d95947850628fc`

The manifest was generated November 16 at 23:21:56 UTC. Its Senate statuses
were 34 media calls and one `final` race (Wyoming). Independently checked
[Wyoming's official statewide summary](https://sos.wyo.gov/Elections/Docs/2026/Results/General/2026_General_Statewide_Candidates_Summary.pdf):
Harriet Hageman 122,174; James Byrd 65,105; write-ins 1,039, totaling 188,318.
This reference check does not certify the other 34 contests.

## Architecture and update behavior

- `ingestion/current_senate.py`: fixed source URLs, scope, manifest contract,
  Polars CSV parsing and validation. No new dependencies.
- `app/services/senate_results.py`: immutable source archives, audit reports,
  atomic last-good pointer, interprocess writer lock and daily updater.
- `ingestion/senate_current.py`: operator refresh, source-profile registration
  and offline verification CLI. `--cache-only` skips database registration.
- `app/services/senate_entities.py`: idempotent source-scoped election/candidacy
  registration, source-row audit crosswalk and read-only profile enrichment.
- `app/api/senate.py` and `senate_schemas.py`: typed read-only snapshot API.
- `frontend/src/SenatePage.tsx`, `SenateMap.tsx`, `senate.ts`, `senate.css`: results,
  interactive state selection, source labels, URL-backed state/status filters,
  compact candidate/bucket rows, retry and freshness.
- `app/main.py`: one cancellable lifespan task, enabled by default.

On API startup, the background task refreshes a missing or expired cache without
blocking API startup. It checks hourly and downloads a new manifest once the
last successful check is at least 24 hours old. An unchanged CSV checksum avoids
another CSV download, advances `checked_at`, and preserves `retrieved_at`.
An open page rereads the local API every five minutes. Browser requests never
trigger upstream downloads. The cache survives container/process restarts through
the existing `./data:/app/data` volume. The updater continues without page visits
while the API is running; no updates happen while the stack is stopped.

Network, checksum, license, schema and reconciliation failures retain the last
valid snapshot and retry hourly. The page flags stale/failed refreshes. Missing
or corrupt local archives return an explicit 503 rather than fabricated zeroes.
Previously available contests disappearing from an update block promotion;
partial first acquisitions explicitly list missing states. A correction can
reduce votes and still pass if the totals reconcile. A manifest older than the
active manifest cannot replace it.

Default durable directory: `data/ingestion/current_senate/`, relative to the
backend's working directory (`/app` in Compose):

```text
raw/<sha256>.csv          Original unmodified full CSV
raw/<sha256>.json         Original unmodified source manifest
reports/<run-uuid>.json   Successful and failed acquisition/validation reports
latest.json              Atomic pointer to the last validated inputs
last_attempt.json        Most recent attempt, including failure status
refresh.lock             OS lock shared by API and CLI writers
```

Every reuse verifies both archives and manifest checksum/size/row count. Inputs
downloaded during failed validation are retained for investigation. Successful
reports distinguish inserted, updated, unchanged and removed candidate/party
lines, accepted Senate rows, excluded other-office rows and rejected rows (zero
for successful promotions). Failed runs are marked `failed`; unknown row counts
are not invented. The report includes a validation reason when available.
Parser versions are checked on replay. Temporary archive files are never used
as published inputs. Back up this directory to retain the full source history;
there is no automated retention/deletion policy.

Provisional totals remain separate from canonical SQL vote publications. No
schema changes or migrations are needed. Profile registration reuses the existing
state jurisdictions, Senate seats and election/candidacy services to register
35 source-scoped contests and 244 named candidacies. The 13 anonymous write-in
buckets receive no candidacy or person profile. Existing people are never matched
by label, and no FEC identifier or financial total is guessed. Named write-in
labels can have source-scoped candidacies without asserting a verified person.

Registration persists `DataSource`, `SourceRelease` and `IngestionRun` records.
The release pins the full CSV checksum, path, retrieval/publication times and
license. Its required numeric `file_id=1` is explicitly an adapter-local ordinal
for `races.csv`, not an invented upstream identifier. Run audit JSON maps source
row ordinals to candidacy UUIDs and retains incumbent evidence. Keys include
source, year, contest and exact candidate/party line; vote corrections preserve
those IDs. Replay creates no duplicates. PostgreSQL transaction/advisory locking
protects registration. Missing or ambiguous state/seat prerequisites roll back
the transaction. Back up both the cache and PostgreSQL for profile continuity.

Canonical contest discovery now finds these events, with no published vote batch.
`/results` and the canonical `/election-map` remain unchanged. `/candidates/<uuid>`
exposes an additive `provisional_election` field for these source candidacies;
the existing profile page shows their current race while keeping identity and
finance explicitly unresolved. Certified canonical 2026 vote publication and
reviewed cross-source person matching remain future work. The daily job and CLI
register new source candidacies after successful cache refresh/reuse; verification
and `--cache-only` still support operation without database writes.

`SENATE_RESULTS_AUTO_REFRESH=1` is passed through Compose and is the default.
Use a single API worker as in the existing Compose service. If another scheduler
owns refreshes, set it to `0` in `.env`, recreate the API service, and schedule the
CLI below daily. The writer lock also serializes manual CLI refreshes with the
API timer. `SENATE_RESULTS_CACHE_DIR` can override the directory in a host process;
the CLI also accepts `--cache-dir`. No new scheduler or service is required.

## API and presentation semantics

`GET /api/v1/senate/2026/results` has `Cache-Control: no-store` and reads only
verified local inputs, enriched through a read-only PostgreSQL session. The
response includes the date/year, expected contest
count, missing states, per-contest source party labels, votes, source outcomes,
source row ordinals, class and special status. It retains source-read,
count-update and call/certification timestamps separately from local retrieval,
local check and source manifest publication timestamps. It includes input row
counts, CSV checksum, manifest/source URLs and parser version. No person IDs are
invented from source names. Source URLs become links only for web schemes.

Status `counting` means no source call; `called` is Call the Map's media call;
`final` is certification **as reported by the feed**, not an independently
verified national certification. Outcomes are copied, never inferred from vote
order. Neither a lead nor precinct reporting implies a winner. The source does
not identify ranked-choice rounds, so the page discloses that limitation instead
of combining rounds or reconstructing a winner. Race vote shares do not imply
chamber control. Blank shares on zero-vote totals remain unknown.
Candidate and ballot-line labels (including write-in aggregates) are preserved;
fusion lines are not automatically matched to people or added twice.

The page title is **2026 Senate Election Results**, without the shared research
workspace eyebrow. An interactive state map appears before the state results.
The introductory notes, coverage counters and cache timestamps have moved into
the lower source panel. A projected Senate-control bar now sits directly below
the title. `app/services/senate_control.py` combines 65 retained seats (32 Democrats,
31 Republicans and 2 independents) with only explicit source winner outcomes in
called/certified contests. The Class I/III rosters, excluding Florida/Ohio special
seats, establish the retained cohort; Class II and those specials establish the
35 election seats. The Daily Press lineup documents King/Sanders caucusing with
Democrats. The baseline is scoped to November 3, 2026 and cites all four sources
in the API and source panel. No new independent is automatically assigned a caucus.

The indicator labels Democratic-aligned seats separately from Democratic party
identity and shows the independent count, a majority check only at 51 seats,
retained/election segments, uncalled/other segments and flips/net changes against
each seat's entering party. All 100 seats must reconcile; missing or uncalled
races never become seats for a vote leader. Counts remain national during state
or status filtering. The retained-seat assumption and current call status describe
projected post-election control rather than the current seated Senate. Initial
cached outcomes give 54 Democrats + 2 retained independents, 44 Republicans and
9 Democratic flips; this differs from older images that still left a race uncalled.
Control tests cover missing races, absent calls, flips, independents, certification,
invalid scopes and exact 100-seat accounting. Frontend tests and desktop/mobile
browser checks cover the bar, majority markers and filter-independent totals.
Control follow-up verification: 36 backend tests passed in Python 3.12 with the
retained live cache, 212 frontend tests passed, and TypeScript/production build
passed. Browser checks at 1440px and 375px confirmed 100-seat bar accounting,
no horizontal overflow and unchanged national totals when filtering Alaska.
Each state card has one table containing candidates and write-in buckets,
without class/election headings, repeated captions or a separate candidate
expander. The status badge sits beside the state name, with the vote total at
the top right of the card. A compact footer divides source and
call/certification details on the left from count-update and source-read times
on the right. Both columns wrap on narrow screens without hiding source details.
It reuses `UnitedStatesMap` for hover/focus details, keyboard selection, zoom and
pan. Selecting a state updates `state_code` and clears a conflicting status
filter; Show all states clears both selections. Colors represent the party ahead
in the current count, independently of calls/certification. Ties, zero counts,
missing returns and states with no election have explicit labels. The table
remains usable if map outlines cannot load.

Senate map popovers now use the presidential map's `ElectionTooltip` component,
including candidate avatars, party colors, share bars, margin and the existing
hover/focus/keyboard behavior. The adapter supplies provisional source labels
and [reviewed cached portraits](candidate_portraits.md) for matching candidate
UUIDs. Portraits also appear on profiles and as table thumbnails, with initial/dot
fallbacks where unavailable. Media assignments do not resolve canonical people
or financial identities. The adapter labels provisional counts
instead of claiming canonical publication. The Senate popover omits the separate
Leading here row and groups small third-party candidates into Other under the
shared [popover threshold rule](../map-popovers.md). Results-page state tables
use the same grouping and combined shares through `candidateAggregation.ts`.
The state link opens the detailed race table with every source candidate and
bucket; candidate profiles also retain all rows and their selected candidate's
highlight. Source/API rows and totals are unchanged. Candidate badges
show Projected winner only for a source `won` outcome in a `called` race, or Winner
for a `won` outcome in a `final` race. An uncalled lead gets no winner badge.
Margins/leader status reuse the backend
`election_map.summarize` definition, including anonymous-bucket and tie safeguards.
Candidate names link to actual source-scoped UUID profiles; anonymous buckets stay
plain text. State headings in popovers and cards link to independently loadable
`/senate/2026/races/<state>` pages. The profile's current-election panel reuses
the same source result card and highlights its selected candidacy.

Individual race pages use a compact title without the research-workspace eyebrow
or date/class subtitle. Above the complete candidate table, `SenateMap` fits only
that race's Census state outline and reuses zoom, keyboard focus and candidate
popovers. These are statewide counts; no county results are inferred. Selecting
the state scrolls to its table. The provisional-counts note follows the result
card, and the race-page snapshot provenance panel is removed. Candidate/source
links, timestamps in the result card and API provenance remain available.

`ingestion/catalog/senate_incumbents.json` records 22 reviewed incumbent source
labels, party/state/class scope, effective date November 3, 2026, review date,
official Senate Class II/III citations, roster checksums and explicit name aliases.
The archived roster HTML is retained under `data/senate-current/research/`.
The incumbent marker is plain text, with its evidence retained in the API and
registration audit; unknown labels remain unknown rather
than automatically becoming challengers. This is an election/office-specific
annotation, not a person match, a winner inference or an assertion about another
office. The registration audit retains the catalog hash and matched evidence.

`frontend/src/geography/data/states.json` retains the 51 state/DC features from
the existing verified Census 2024 display package. Its metadata preserves the
original source archive SHA-256
`3e81cbb6cf5f60d9b01ef3e730afa14d61ce5f784252a0b33a696135e71447bc`,
archive URL, retrieval time, display-object checksum, 0.005-degree simplification,
and five-decimal precision. This is a minified copy of the package's state object
with provenance added. The existing `ingestion.boundaries --year 2024 --office president`
preparation reproduces that state object. These outlines are labeled as Census
2024 display geography rather than 2026 election-day certification; the join uses
exact state codes and does not redistribute or reconstruct votes. The static
JSON asset and map module load separately from the main page bundle.

Shares are calculated from each reconciled source contest total, including all
reported candidates and buckets. Supplied source percentages must agree within
0.02 percentage points, accommodating rounding. Non-finite, malformed or negative
votes, duplicate candidate/party lines, unknown statuses, inconsistent metadata,
unsafe evidence URLs and timezone-free timestamps block promotion. No percent
of expected vote or turnout is estimated. The page formats timestamps in Eastern
time with an ET label and distinguishes missing results from zero votes.

## PowerShell operation and verification

With the existing local stack running, from the repository root:

```powershell
# Main/ingestion/frontend code uses existing source mounts.
# Recreate API after changes to Compose environment settings.
docker compose up -d api frontend

# Daily-cache-aware refresh, explicit forced check, then offline replay.
# The first two commands also register source-scoped profile entities in PostgreSQL.
docker compose exec -T api python -m ingestion.senate_current
docker compose exec -T api python -m ingestion.senate_current --force
docker compose exec -T api python -m ingestion.senate_current --verify-only
# Optional: counts only, without profile registration/database writes.
docker compose exec -T api python -m ingestion.senate_current --cache-only

$results = Invoke-RestMethod 'http://localhost:8000/api/v1/senate/2026/results'
$results.races.Count
$results | Select-Object checked_at, published_at, stale, refresh_failed, sha256
Start-Process 'http://localhost:5173/senate/2026/results'

docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
```

For backend tests in a Python 3.12 environment with the existing development
requirements installed, from `backend/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest tests/test_current_senate.py tests/test_senate_entities.py tests/test_senate_entities_postgres.py tests/test_election_api_contract.py tests/test_senate_returns.py -q
```

The tests are offline by default. To include the optional **pinned** live-input
replay with the above CSV checksum, set `CURRENT_SENATE_CACHE_DIR` to the retained
snapshot directory before pytest. Fixture tests cover source scope, special
seats, sums/shares/zeroes, vote corrections, daily reuse, restart, unchanged
refresh, missing contests, invalid/corrupt inputs, retained last-good results,
API 503s, scheduler retry and lifecycle cleanup. UI tests cover the header route,
state/status filtering, missing coverage, source attribution, all buckets,
status distinctions, errors/retry, polling, abort and response validation.

Initial cache/page validation on November 17, 2026: 126 backend checks in Python 3.12
(including the retained live snapshot), 202 frontend tests, strict TypeScript
and a Vite production build. Headless Edge checked all 35 contest totals and
257 rows against the API, the header link, special seats, filters/back/reload,
API error/retry, map colors/hover/click/keyboard selection/zoom/reset, and 375px
mobile layout. Screenshots were inspected and the
tables adjusted so vote/share columns fit without horizontal scrolling. Browser
evidence is under ignored `artifacts/senate-results/`. API and PostGIS health
checks passed. These checks do not independently reconcile every state to its
certified returns or replace broader cross-browser/accessibility QA.

Profile/popover follow-up: 116 backend tests passed in Python 3.12, including
isolated PostgreSQL registration, audit/replay, stable IDs, rollback, anonymous
bucket exclusion and profile regressions. One optional full historical MEDSL
fixture replay was skipped because `MEDSL_SENATE_FILE` was not configured.
The final frontend suite passed 205 tests and a strict production build.
All 244 named candidate API profiles were fetched and checked against their
source race; no person or finance identity was inferred. Browser checks verified
all 35 state links, 244 profile links, 22 incumbent badges, presidential-style
popover shares/margins, keyboard navigation to race/profile pages, reload,
mobile bounds and Escape. The shared URL validator now accepts the backend's
existing `state` reporting level, fixing statewide candidate deep links.
Screenshots and reports are under `artifacts/senate-results/`.

For a local archive corruption, preserve a copy of the directory for investigation,
then point a forced refresh at a new empty directory using `--cache-dir` and verify
it offline before selecting it for the API. Do not edit archived bytes or the
checksum manifest in place. Ordinary upstream failures need no manual intervention.
