# Senate contests and returns, 2000–2024

The Senate pipeline reuses source releases, immutable observations, ingestion runs,
state geographic references, canonical election entities, publication pointers,
candidate aggregation and read APIs. Previously those shared components existed,
but there was no Senate source adapter, seat-class identity or publication path.
No service or runtime dependency was added. Historical migrations are unchanged.

## Source and scope

[MEDSL U.S. Senate statewide 1976–2024](https://doi.org/10.7910/DVN/PEJ5QU),
Harvard Dataverse V8.0, released May 11, 2026, is CC0. The original CSV is file
`13887039`, `1976-2024-senate-state.csv`, 530,501 bytes, SHA-256
`6f745db1b4a0026ad837e74428f9ed6f3f77fa51eb6f858b58ebdbc186fdb3bd`.
The original has 3,945 rows; the supported calendar years select **2,314 rows**.
The archived `.tab` representation has a different checksum and size; use
`?format=original`. Existing Dataverse acquisition and configured guestbook
responses apply. No identity or contact information is invented for downloads.

The [MEDSL codebook](https://dataverse.harvard.edu/api/access/datafile/6708560)
defines party-line votes as additive and describes unofficial results and
uncontested vote placeholders. Original strings, ordinals and row hashes remain
in `election_result_observation`; decimal strings such as `123.0` normalize to
integers exactly. Fractional, negative, overflowing and malformed counts fail
validation. Missing values stay null; a genuine one-vote line stays one vote.
A contest total of one is withheld as the documented uncontested placeholder.

Supported source years are the even years 2000–2024 plus **2021**, which contains
the January 2021 Georgia runoffs for the 2020 cycle. This is the available MEDSL
source scope, not an exhaustive Senate election calendar. The source omits
off-cycle specials including Massachusetts 2010/2013, New Jersey 2013 and Alabama
2017, and Connecticut 2022. Illinois 2010 rows have a conflicting election-type
flag (see below). Imports cannot create
records absent from the source. Missing regular-state coverage is reported.
`COMPLETE` means reconciled within the selected source scope, not certification
or a claim that all historical election events are represented.

## Seat and event identities

`senate_seat` associates a canonical `office` with a state and class (1, 2 or 3).
The state/class pair is unique and survives election cycles. It represents a seat,
not an officeholder. The official Senate
[Class I](https://www.senate.gov/senators/Class_I.htm),
[Class II](https://www.senate.gov/senators/Class_II.htm) and
[Class III](https://www.senate.gov/senators/Class_III.htm) lists supply the
33/33/34 state memberships. Regular elections follow that six-year rotation.
Specials use explicit state/year class mappings with the corresponding official
state Senate succession page as evidence. An unknown mapping is withheld.

`senate_return_detail` preserves source stage, special, write-in and unofficial
indicators. `senate_contest` preserves the applied scope rule and citations.
The date rules are in `ingestion/senate_returns.py`; their output is fingerprinted
alongside observations and geographic references. Regular and special elections
for the same class on the same date remain separate contests (California 2022
and 2024). No winner, service term, swearing-in date or person match is inferred.
Runoff relationships are represented by distinct stage/date/cycle; parent-event
and preceding-contest links are not inferred by this adapter.

Explicit source conventions:

| Source scope | Canonical treatment | Evidence |
| --- | --- | --- |
| Georgia 2008 `pre` | General, November 4 | [House Clerk](https://clerk.house.gov/member_info/electionInfo/2008/2008Stat.htm) |
| Georgia 2008 `gen` | Runoff, December 2 | Same Clerk report |
| Mississippi 2018 special `gen` | Special runoff, November 27 | [FEC](https://www.fec.gov/updates/mississippi-special-election-reporting-senate-2018/) |
| Georgia 2021 `runoff` | January 5, 2021; cycle 2020; regular class 2, special class 3 | [FEC reporting calendar](https://www.fec.gov/help-candidates-and-committees/dates-and-deadlines/2020-reporting-dates/congressional-pre-election-reporting-dates-2020/) |
| Georgia 2022 `GEN RUNOFF` | Runoff, December 6 | [FEC reporting calendar](https://www.fec.gov/help-candidates-and-committees/dates-and-deadlines/2022-reporting-dates/congressional-pre-election-reporting-dates-2022/) |
| Louisiana 2002, 2014, 2016 | Mixed-round source rows retained and excluded; no invented single-date contest | [Clerk election statistics archive](https://history.house.gov/Institution/Election-Statistics/), [2016 report](https://clerk.house.gov/member_info/electionInfo/2016/statistics2016.pdf) |
| Illinois 2010 `special=True` | Full-term counts mislabeled as a special; all 13 rows withheld, without rewriting the source | [FEC 2010 Senate results](https://www.fec.gov/resources/cms-content/documents/2010senate.pdf), full-term and unexpired-term tables |

The independent Georgia 2008 reference checks are **3,752,485** general-election
votes and **2,137,956** runoff votes. They are separate elections and must never
be added as a single contest total. The full-source integration test checks both
against the Clerk's report. This is not an independent all-contest certification.

## Reconciliation and publication

`senate_contest_reconciliation` records every source group, original ordinals,
applied scope, repeated source total, category sum, accepted vote sum, equality
basis and exclusions. Unknown stages/classes, missing or conflicting totals,
duplicates, unresolved labels, non-total modes and unofficial rows withhold
the entire contest's vote categories. One candidate cannot remain published
when a competing candidate in that contest fails validation. Blank/void/overvote
and similar administrative categories are separately excluded. Reconciliation
accepts either all source categories or vote categories equaling the source total
and records which equality held. No vote value is corrected or imputed.

Named candidates get source-release/contest-scoped candidacies and party or
write-in ballot lines. Fusion lines aggregate once through the existing service.
Unnamed write-ins remain separate anonymous buckets, without person identities.
`SCATTER` is an anonymous write-in bucket. Nevada's “none of these candidates”
options and other unnamed candidate aggregates remain aggregate vote choices.
Singular/plural blank, void and over/under-vote labels are administrative categories;
combined blank/void/scattering buckets are excluded because their vote component
cannot be separated. Canonical category rules are applied independently of stored
ingestion hints, so refining those rules never requires rewriting observations.
Alaska 2022/2024 reconciliation records flag source-reported ranked-choice counts;
no round reconstruction or winner inference occurs.

Each year has its own `medsl_senate:{year}:state_total` publication scope. Reference
selection requires one compatible `census_state_county_georef` release; an explicit
release ID resolves multiple-release ambiguity. State FIPS and postal code must
agree. Reference vintages describe statistical products, not legal boundary dates.
Existing geography decisions and supersession chains are checked even before an
unchanged publication is reused. Conflicts require the established review workflow.

Preview is the default. Publication requires `--publish`; exclusions or missing
regular coverage also require `--allow-partial`. All selected years commit in
one repeatable-read transaction. Replays reuse observations and immutable batches;
superseded releases remain available. The fingerprint includes source/references,
normalized inputs and scope decisions. If all counts are withheld but supported
events exist (notably unofficial Georgia 2021), publication may model their
contests/candidates with zero accepted returns. Discovery exposes those contests
with empty publication lists; it never manufactures zero-vote results.

## Queries

`/api/v1/contests` and `/api/v1/results` expose nullable `seat_class`.
Election, contest and result filters accept `seat_class=1|2|3` alongside the
existing state, office, stage, year and UUID filters. `year` always means calendar
election year, so request `year=2021` for the January Georgia runoffs.

Use `/api/v1/results?office=U.S.%20Senate&reporting_level=state` for Senate votes.
`/api/v1/state-results` remains the separate FEC presidential authority contract.
Candidate profiles select state reporting by default for Senate candidacies;
unresolved identities and missing finance are disclosed as before. The existing
frontend explorer's Senate controls and maps are outside this data assignment.

## Operation and verification (PowerShell)

From the repository root, with Compose running:

```powershell
docker compose run --rm --no-deps -v ./backend:/app api alembic upgrade head

# Acquire, archive and validate without database changes.
docker compose exec api python -m ingestion run medsl_senate --validate-only

# Pin the reviewed original checksum for every load or replay.
$senateHash = '6f745db1b4a0026ad837e74428f9ed6f3f77fa51eb6f858b58ebdbc186fdb3bd'
docker compose exec api python -m ingestion run medsl_senate --expected-sha256 $senateHash
docker compose exec api python -m ingestion.senate
# Inspect data/senate-returns/publication.json before publishing partial coverage.
docker compose exec api python -m ingestion.senate --publish --allow-partial

# Repeat both commands to check observation and publication idempotency.
docker compose exec api python -m ingestion run medsl_senate --expected-sha256 $senateHash
docker compose exec api python -m ingestion.senate --publish --allow-partial

Invoke-RestMethod 'http://localhost:8000/api/v1/contests?office=U.S.%20Senate&year=2024&seat_class=1'
Invoke-RestMethod 'http://localhost:8000/api/v1/results?office=U.S.%20Senate&year=2008&state_code=GA&reporting_level=state'
```

For offline replay, retain the official metadata JSON and immutable cache manifest
and pass `--source-metadata-file /app/data/senate-returns/metadata.json` together
with `--expected-sha256`. The manifest's original retrieval timestamp is reused.
Never regenerate it to suggest a new historical retrieval.

Tests use randomly isolated schemas in the guarded `_test` database. The existing
runner requires the declared dev/research requirements. The pinned-file test
never downloads; enable it with `MEDSL_SENATE_FILE`:

```powershell
docker compose run --rm --no-deps -v ./backend:/app -e MEDSL_SENATE_FILE=/app/data/ingestion/raw/medsl_senate/8.0/6f745db1b4a0026ad837e74428f9ed6f3f77fa51eb6f858b58ebdbc186fdb3bd.csv api python -c "import subprocess,sys; subprocess.run([sys.executable,'-m','pip','install','-q','-r','requirements-dev.txt','-r','requirements-research.txt'],check=True); sys.exit(subprocess.call([sys.executable,'tests/run_candidate_tests.py','--create-test-db','-q']))"
```

Coverage includes source fidelity, decimal/missing/invalid counts, all 100 seat
identities, special/regular separation, cross-year runoffs, fusion aggregation,
anonymous write-ins, whole-contest exclusion, zero-return metadata, migration
roundtrip, ORM/schema agreement, transaction rollback, changed releases,
reactivation, geography supersession and HTTP/profile behavior.

## Verified local snapshot (November 16, 2026)

The additive `senate_return_evidence` migration was applied after a custom-format
database backup. The complete Python 3.12/PostgreSQL suite passed **454 tests,
zero failures or skips**, including the full pinned Senate and FEC file replays.
Alembic `check` found no schema drift. No frontend code changed.

| Measure | Verified count |
| --- | ---: |
| Original file rows / selected observations | 3,945 / 2,314 |
| State/class seat identities | 100 |
| Source groups / modeled contests | 454 / 450 |
| Reconciled contests | 441 |
| Source-scoped candidacies | 1,798 |
| Published returns / excluded observations | 2,182 / 132 |
| Result items after fusion aggregation | 2,146 |
| Annual publication batches, all PARTIAL | 14 |

An independent live HTTP check paged every year, reconciled all 2,182 distinct
observation links and vote sums to the publication reports, checked class filters,
candidate profiles, absent county/FEC Senate results and both health endpoints.
Observation replay inserted/updated zero rows and reused all 2,314 observations;
all 14 publication replays returned `UNCHANGED`.

All eight preexisting canonical publication pointers and their vote/row totals,
all seven FEC presidential state publication pointers, all 94,151 presidential
observations, the existing person and all geographic references were preserved.
No source labels were matched to people. Local backup, test XML, before/after
snapshots and HTTP evidence are under ignored `artifacts/`; source metadata,
preview, publication and replay reports are under ignored `data/senate-returns/`.
The source catalog records the pinned original and its coverage limitations.

Remaining data work: authoritative inputs for source-absent elections; separate
round reconstruction for Louisiana; verification of source-unofficial counts;
all-contest independent certification; evidence-backed canonical person matching.
