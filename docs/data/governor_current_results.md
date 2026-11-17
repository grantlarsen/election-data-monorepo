# Current Governor results and daily cache

The Governor header opens `/governor/2026/results`. Direct state pages such as
`/governor/2026/races/FL` retain every source candidate line. The overview follows
the Senate page's title, state map, compact tables, source panel, timestamps,
URL state/status filters and delayed-update warnings. Its outcome bar counts
the 36 races in this election and stays national when filtering. It does not
claim to describe all 50 sitting governors or national political control.

## Existing architecture and implementation

Previously the Governor link was a planned-page placeholder. Senate and House
already supplied the provisional-results Polars validator, content-addressed
cache, source manifest validation and daily refresh policy. Existing canonical
election/person/geography models and observation tables were inspected; this
feature uses the provisional cache separately from canonical publications.
No schema migration or new dependency is required, and historical migrations
are unchanged. Source-scoped candidacy profiles are registered using the existing
election entities; Governor person identities and finance links are not inferred.

- `backend/ingestion/current_governor.py`: office scope and shared validation.
- `backend/app/services/governor_results.py`: shared cache binding and scheduler.
- `backend/app/services/governor_entities.py`: idempotent profile registration,
  reviewed incumbent annotations and prior-election party comparisons.
- `backend/ingestion/catalog/governor_context.json`: reviewed NGA evidence,
  exact source labels and previous-election winners for all 36 states.
- `backend/ingestion/governor_current.py`: acquisition/offline replay CLI.
- `backend/app/api/governor.py`, `governor_schemas.py`: typed read-only endpoint.
- `frontend/src/governor.ts`, `GovernorPage.tsx`, `GovernorMap.tsx`: API contract,
  overview, full state tables and shared election popovers.
- `frontend/src/StateResultsMap.tsx`: the existing Senate state map extracted for
  both offices; `SenateMap.tsx` preserves its existing interface and popovers.
- `App.tsx`, `navigation.ts`, API lifespan, Compose and example environment:
  routes, working header link and daily job wiring.

## Source, scope and interpretation

[Call the Map's downloads](https://www.callthemap.com/results/data) publish
`https://www.callthemap.com/results/data/2026/races.csv` with an adjacent
`manifest.json` and [data dictionary](https://www.callthemap.com/results/data/2026/README.txt).
This is a third-party compilation of state/county election-office records,
partly via [civicAPI](https://civicapi.org), licensed CC BY 4.0. The page credits
both providers and retains each race's original evidence URL and read/count/call
timestamps. Primary source verification is distinct from trusting feed labels.

The [NGA calendar](https://www.nga.org/governors/elections/) lists 39 elections:
36 states plus Guam, Northern Mariana Islands and the U.S. Virgin Islands.
This feed covers the 36 states only, explicitly disclosed on the page. Other
offices are reported as excluded. Unexpected Governor contest IDs fail
validation. Primaries, runoffs, territorial and separate special elections need
their own explicit scope; they must not overwrite these general-election races.

`counting` means uncalled, `called` means a Call the Map media call, and `final`
means state certification as reported by the feed. Only a unique explicit
`won` outcome in a called/final contest earns a win in the outcome bar. Leads
and missing races remain uncalled. Independent/other winners get their own
category without a party/caucus assumption. Map colors describe the party
ahead in the source vote count; calls are separately labeled.

Candidate sums must equal the reported race total. Source percentages, when
present, must agree within 0.02 percentage points. Negative/malformed counts,
duplicates, inconsistent metadata, unsafe evidence URLs, timezone-free dates,
unknown statuses and inconsistent winners block promotion. Corrections may
decrease votes. Entirely missing contest counts remain null, not zero; partly
missing counts fail validation. Zero totals have no shares or determined leader.
Shares describe reported votes, not the percentage of expected ballots counted.
Ranked-choice rounds and reporting completeness are not supplied or reconstructed.
Source party labels are preserved, including simplified `O` categories.

The overview uses the existing minor-candidate presentation rule and links to
full state tables; aggregation does not change API votes or archived rows.
The map reuses pinned Census 2024 state outlines, labeled as display geography,
and existing keyboard selection, zoom, pan and popovers. Failed map loads leave
tables available with a map retry. Missing races and states without an election
have distinct colors and labels.

## Incumbents, candidate profiles and party flips

The reviewed NGA 2026 roster identifies 17 incumbents on this feed's general
election ballots. Exact state, source candidate label and party must match the
reviewed catalog before an incumbent badge is shown. Unlisted candidates stay
unknown, not confirmed challengers. Incumbency refers to the Governor entering
November 3, including appointed incumbent Larry Rhoden in South Dakota; it is
independent of who won in 2022. A senator running for Governor does not receive
a Governor incumbent badge. Both tables and map popovers use the same annotation.

Named candidates link to `/candidates/<candidacy-uuid>` in tables and popovers.
The registration uses stable creation keys scoped to source, year, contest,
exact name and party. It reuses canonical state jurisdictions, creates election
and contest entities, registers 250 named source candidacies, and excludes 13
anonymous source categories. Synthesized Other rows also remain unlinked.
Profiles show this race's provisional counts and retain unresolved person/finance
states. No canonical votes, guessed person matches or FEC links are created.
Available reviewed headshots replace table dots and popover initials and also
appear on linked profiles, with attribution. See
[candidate portrait coverage, sources and replay](candidate_portraits.md) for the
68 cached Governor portraits, missing-image fallbacks and remaining source-access
gaps. The ordinary daily count refresh does not search for or reassign images.
An advisory transaction lock and uniqueness constraints keep registration
idempotent. Source-release and ingestion-run records preserve source row ordinals,
catalog checksum, incumbent evidence and previous-election comparisons.

Diagonal white hatching overlays the existing party color for a **called or
certified** winner of a different party than the previous Governor election's
winner. The comparison uses **2024 for New Hampshire and Vermont**, and **2022
for every other state**, based on the NGA archived starred winners. A lead,
missing/ambiguous winner or unknown party does not establish a flip. Changing
the person within the same party does not establish a flip either. Hatching has
a map legend and accessible state description; tables and popover footers identify
the prior party/year and distinguish media calls from source certification.

The pinned NGA page is retained under
`data/ingestion/governor_context/nga-elections.html`, SHA-256
`d6448d648121a00e2c7b1aa3a2043b1a3834fccd1dcf9c52b2d42ab674cf12cc`.
The catalog includes the source URL, hash, retrieval and review timestamps,
annotation method and election effective date. Changes to reviewed context
require rerunning the registration CLI and restarting the API to reload the
in-memory catalog.

## Cache and operation

`GET /api/v1/governor/2026/results` reads and verifies local archives, returns
`Cache-Control: no-store`, and never contacts the upstream source or writes the
database. A read-only database session supplies registered candidacy IDs and
reviewed context. Missing
or corrupt caches produce 503 with no internal filesystem details.

The API lifespan job checks on startup and hourly, refreshing after 24 hours,
then synchronizes source-scoped profiles;
failures retry hourly when due. An unchanged CSV hash avoids downloading the
CSV, advances `checked_at` and preserves `retrieved_at`. The open page reads
the local API every five minutes and retains its last loaded data on errors.
Updates require the API to be running; use the existing single-worker setup.

The Compose frontend enables Vite file polling for Windows bind mounts, where
filesystem events may not reach the container and transformed routes can remain
cached. After changing Compose's frontend environment, recreate it with
`docker compose up -d --no-deps frontend`, then reload the browser. Host Vite
processes retain native filesystem watching unless `VITE_USE_POLLING=1` is set.

The shared cache retains SHA-256-addressed raw CSV/manifests, run reports, a
writer lock, an atomic `latest.json` pointer and `last_attempt.json`. Hash/size,
license/schema, vote validation, backwards manifests and disappearing-contest
checks all precede promotion. Failed updates retain the last valid snapshot
and surface stale/failure warnings. Reports distinguish accepted, excluded,
rejected, inserted, updated, unchanged and removed rows. Offline replay
rechecks source bytes and parsing. Retention/deletion is not automated.

Default directory: `data/ingestion/current_governor`, relative to the backend
working directory. Compose persists this under its existing `./data:/app/data`
mount; raw inputs stay outside Git. `GOVERNOR_RESULTS_CACHE_DIR` overrides the
directory for host processes. `GOVERNOR_RESULTS_AUTO_REFRESH=1` is the default;
set it to `0` in `.env` and recreate the API if an external scheduler owns the
CLI instead. No additional scheduler service is needed.

From the repository root in PowerShell:

```powershell
docker compose up -d api frontend
docker compose exec -T api python -m ingestion.governor_current
docker compose exec -T api python -m ingestion.governor_current --force
docker compose exec -T api python -m ingestion.governor_current --verify-only
# Optional count-cache refresh without database entity registration:
docker compose exec -T api python -m ingestion.governor_current --cache-only
$results = Invoke-RestMethod 'http://localhost:8000/api/v1/governor/2026/results'
$results.races.Count
$results | Select-Object checked_at, published_at, stale, refresh_failed, sha256
Start-Process 'http://localhost:5173/governor/2026/results'
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
# Disposable test container with existing development requirements:
docker compose run --rm --no-deps -v ./backend:/app -e CURRENT_GOVERNOR_CACHE_DIR=/app/data/ingestion/current_governor api sh -c 'python -m pip install -q --root-user-action=ignore -r requirements-dev.txt && python -m pytest tests/test_governor_entities.py tests/test_current_governor.py tests/test_current_house.py tests/test_current_senate.py -q'
```

## November 17, 2026 verification

Initial acquisition accepted 263 Governor candidate rows from 2,759 input rows,
excluded 2,496 other-office rows and rejected zero rows. All 36 states were
present. The manifest was generated at `2026-11-17T05:01:22Z`; CSV SHA-256:

`55605f0c86fca12e76bc6be938b639607470bd62119422f20ac24971cb0a7c33`

At verification the feed marked 35 races called and Wyoming final; no races
were marked counting. Calls can coexist with continuing canvassing and count
corrections, so the daily refresh remains enabled. Forced repeat acquisition
reported 263 unchanged rows and zero inserts, updates or removals. Offline
replay passed; API and frontend routes returned HTTP 200, with no stale/failure
flag and no missing states.

Wyoming counts independently matched page 4 of the
[official statewide candidate summary](https://sos.wyo.gov/Elections/Docs/2026/Results/General/2026_General_Statewide_Candidates_Summary.pdf):
Eric Barlow 128,496; Kenneth R. Casner 27,472; Rebecca Bextel 31,444; write-ins
1,212, totaling 188,624 candidate votes. Overvotes and undervotes are excluded
from this total. This check does not independently certify the other states.

The focused backend suite passed 94 tests, with two optional Senate/House live
replays skipped; the Governor retained-input test ran. Six PostgreSQL integration
tests passed against the existing isolated test database, covering Governor,
Senate/House profile registration, replay, audit and candidate APIs. The full frontend suite
passed 294 tests, and the TypeScript/production build passed. UI validation
initially used DOM interaction tests. The portrait update additionally verifies
all 68 served image checksums, all 68 linked profiles, decoded review sheets and
desktop/mobile result/profile rendering with the installed Edge browser.

Live verification found 17 incumbent annotations, 250 registered profile links,
and six party flips: Alaska, Georgia, Iowa, Nevada, Ohio and Texas. All six
compare with Republican winners in 2022 and are source media calls, not claims
of certification. Profile requests for Joe Lombardo, Greg Abbott and Larry
Rhoden returned Governor provisional results with unresolved person/finance
states. Repeating registration returned 250 unchanged candidacies and no inserts.
