# Candidate identity matching and profiles

The existing identity foundation already separated people, candidacies, organizations,
external identifiers and committee relationships. Canonical MEDSL returns and frontend
candidacy links existed, but candidate matching, review operations, finance storage
and the profile endpoint/page did not. This implementation extends those components;
it does not rewrite observations, election publications, historical migrations or IDs.

## Data and decisions

`fec_candidate_record` retains a candidate-master observation per pinned source
release and FEC identifier. Imports use the existing `source_release`,
`external_identifier`, immutable raw cache and `ingestion_run` audit conventions.
Candidate master import registers unresolved external IDs; it creates no people.
`candidate_finance_summary` retains one all-candidates summary per release, candidate
identifier and two-year FEC file cycle. Original field strings are in `raw_json` and
the original ZIP is retained with its SHA-256. DataFrame work uses Polars.

`candidate_identity_review` stores proposals, unmatched cases and completed decisions
with ruleset, context, confidence score, source record, reviewer evidence and time.
The review queue is an operator CLI, not a public write endpoint.

Matching policies:

- An existing FEC candidate identifier explicitly attached to a candidacy takes
  precedence over names. Automatic acceptance also requires one ID, one source
  record, and agreement on election year, FEC cycle, office, state and district.
  Conflicting or missing authoritative evidence stays unresolved.
- Exact normalized names plus the same scope generate **pending proposals**, even
  when there is only one match. Comma-separated names are reordered, punctuation
  and accents normalized; initials, nicknames, suffixes and former names are not
  guessed. Scores are rule strengths, not calibrated probabilities.
- Geography comes from canonical contest jurisdictions and year-compatible
  congressional references. Multiple conflicting references or missing House
  districts prevent scope matches. FEC uses `00` for at-large, Senate and
  presidential records. Blank Senate/presidential districts normalize to `00`;
  missing House districts remain null. Census DC delegate `98` maps explicitly
  to FEC `00` only for DC. ID/office contradictions remain in the source record
  and prevent acceptance.
- Reviewers can propose an alias using an explicit source record ID. Acceptance
  requires the same scope, reviewer and citation/evidence. It resolves a stable
  FEC ID through the existing identity service and links the candidacy to that
  person. Existing conflicting person assignments cannot be overwritten.
- Rejection is an explicit non-merge assertion for that candidacy/FEC-ID pair,
  including future releases. New releases retain separate pending evidence.
  An accepted decision is unique per candidacy. Completed decisions cannot be
  reversed by this workflow; correcting a decision requires a separately designed,
  audited reassignment workflow rather than silently mutating identity history.
- The principal campaign committee comes from FEC `CAND_PCC`, not a name match.
  Relationships include candidacy, person, cycle, source and release. Until a
  committee-name source is integrated, the organization is transparently labeled
  `FEC committee <ID>`. Other committee roles can use existing reviewed relationships;
  this importer does not infer authorization from leadership PACs, joint fundraisers
  or independent expenditures.

Duplicate source candidate IDs, malformed schema, invalid IDs, scope values,
money or dates stop the entire import. Row validation failures are recorded in
`ingestion_rejection`; no records from that release are promoted. Successful runs
report read/inserted/unchanged/updated/excluded/rejected counts; missing or
contradictory retained scope fields generate explicit audit warnings. Rerunning
identical inputs preserves release IDs and inserts no duplicate records.

## Finance definitions and limits

The candidate profile uses the **accepted match's FEC ID**, or an official ID
directly attached to the candidacy, for the selected election's cycle. It never
sums a person's identifiers, committee summaries or historical source releases.
For an ID/cycle it selects the snapshot with the newest source retrieval timestamp;
conflicting snapshots at that timestamp or multiple eligible IDs produce `ambiguous`.
The exact release, checksum, retrieval time and coverage end date are exposed.
There is no inferred start date when the source does not supply one.

Both **Total Raised** and **Total Spent** are always prominent. The all-candidates
file supplies reported receipts and disbursements. Following the FEC's guidance,
when transfers from **and** to authorized committees are positive, the displayed
totals subtract the respective transfers and are labeled derived. Reported gross
totals and both transfer amounts remain visible alongside them. When both transfer
fields are known and this condition does not apply, reported totals are shown.
Missing transfer or total fields produce `partial` and unavailable display totals;
null never becomes zero. All money is stored as decimal USD and serialized as strings.

These are candidate/authorized-committee summaries, not a sum of itemized donations,
not net contributions and not independent expenditures. Reporting coverage differs
between candidates; the file can contain amendments and less precise summaries.
Detailed donor categories, cumulative donor classifications, committee master and
candidate-committee linkage ingestion, transaction/amendment reconciliation and the
broader finance API remain separate finance work. This narrow summary dependency
does not claim to complete DATA-008, DATA-009 or all of API-003.

Official specifications checked for this implementation:

- [FEC candidate master](https://www.fec.gov/campaign-finance-data/candidate-master-file-description/)
- [FEC candidate-committee linkage](https://www.fec.gov/campaign-finance-data/candidate-committee-linkage-file-description/)
- [FEC all-candidates summaries, timing and transfer guidance](https://www.fec.gov/campaign-finance-data/all-candidates-file-description/)

## API and frontend

`GET /api/v1/candidates/{candidacy_uuid}` returns person identity (or an explicit
unresolved/pending state), source label, review evidence, identifiers, contest,
cycle-specific committee relationships, finance and published result records.
The UUID identifies a candidacy in one contest; a person can have several such
profiles. A profile survives source publication changes, but only current published
returns are shown; superseded returns are not silently reused.

Optional `reporting_level`, `limit` (1–200, default 50) and `offset` (nonnegative)
page results. Without a level, House district contests use congressional districts
and other contests use counties. Reporting mode is `TOTAL`. Existing candidate
aggregation validates fusion lines and rejects overlapping representations. The
profile does not combine different reporting units or batches into a purported
contest-wide result or winner. Each result retains publication coverage, source,
observation/correction identifiers and geographic reference vintage.

Responses: `404` for a nonexistent candidacy, `422` for invalid path/pagination/grain,
`503` for database unavailability or published-return integrity failures. There is
no public mutation endpoint. Read requests use the existing PostgreSQL repeatable
read, read-only session dependency.

The React route `/candidates/{candidacy_uuid}` supports direct navigation/reload,
source disclosure, loading, retry, 404, zero/missing/partial/ambiguous finance and
result pagination. Explorer year/office/state filters remain navigation context;
they cannot change the identity or finance cycle of the candidacy in the address.

## PowerShell operation

From the repository root, apply the new additive migration (the API image does
not mount migrations by default, hence the explicit whole-backend mount):

```powershell
docker compose run --rm --no-deps -v ./backend:/app api alembic current
docker compose run --rm --no-deps -v ./backend:/app api alembic upgrade head
```

Download and pin official inputs. Preserve the printed retrieval timestamp and
hashes for replay; do not substitute a current timestamp for historical retrieval.
The FEC replaces files at stable URLs, so cycle alone is not a version pin.

```powershell
New-Item -ItemType Directory -Force ./data/fec-candidates | Out-Null
Invoke-WebRequest 'https://www.fec.gov/files/bulk-downloads/2024/cn24.zip' -OutFile ./data/fec-candidates/cn24.zip
$masterRetrieved = (Get-Date).ToUniversalTime().ToString('o')
Invoke-WebRequest 'https://www.fec.gov/files/bulk-downloads/2024/weball24.zip' -OutFile ./data/fec-candidates/weball24.zip
$summaryRetrieved = (Get-Date).ToUniversalTime().ToString('o')
$masterHash = (Get-FileHash ./data/fec-candidates/cn24.zip -Algorithm SHA256).Hash.ToLowerInvariant()
$summaryHash = (Get-FileHash ./data/fec-candidates/weball24.zip -Algorithm SHA256).Hash.ToLowerInvariant()
$masterRetrieved; $masterHash; $summaryRetrieved; $summaryHash

docker compose exec api python -m ingestion.candidate_identity import-fec --kind master --path /app/data/fec-candidates/cn24.zip --cycle 2024 --sha256 $masterHash --retrieved-at $masterRetrieved --validate-only
docker compose exec api python -m ingestion.candidate_identity import-fec --kind master --path /app/data/fec-candidates/cn24.zip --cycle 2024 --sha256 $masterHash --retrieved-at $masterRetrieved
docker compose exec api python -m ingestion.candidate_identity import-fec --kind summary --path /app/data/fec-candidates/weball24.zip --cycle 2024 --sha256 $summaryHash --retrieved-at $summaryRetrieved
```

Use the **master** release ID from the import result. Matching commits its cases
atomically and must finish before review. Repeat the import and matching commands
to verify unchanged counts.

```powershell
$releaseId = '<master release UUID>'
docker compose exec api python -m ingestion.candidate_identity match --release-id $releaseId --year 2024
docker compose exec api python -m ingestion.candidate_identity queue --status pending --limit 100
docker compose exec api python -m ingestion.candidate_identity queue --status unmatched --limit 100

$reviewId = '<review UUID>'
docker compose exec api python -m ingestion.candidate_identity decide --review-id $reviewId --decision accept --actor 'reviewer-name' --evidence 'Official registration and ballot citations, including identifiers and scope'
# Use --decision reject for an explicit non-merge assertion.

# Find an official record, propose an independently evidenced alias, then review:
docker compose exec api python -m ingestion.candidate_identity records --release-id $releaseId --fec-id '<FEC candidate ID>'
docker compose exec api python -m ingestion.candidate_identity propose --candidacy-id '<candidacy UUID>' --record-id '<record UUID>' --actor 'reviewer-name' --evidence 'Authoritative alias citation'
```

Do not accept a proposal solely because its score is high. Review the original
source record and contest context and cite the evidence for the identity decision.
Never edit person IDs or completed review statuses directly to bypass a conflict.

## Verification

Inside an API test environment with `requirements-dev.txt` installed:

```powershell
docker compose run --rm --no-deps -v ./backend:/app api python tests/run_candidate_tests.py --create-test-db
docker compose exec frontend npm test
docker compose exec frontend npm run build
```

The runner only uses the configured database name plus `_test`, creates it only
with `--create-test-db`, and tests use randomly isolated schemas. It supplies the
test URL in process memory without printing credentials. Optional full-file replay
uses `FEC_CANDIDATE_MASTER_ZIP` and `FEC_CANDIDATE_SUMMARY_ZIP`; tests never download.

```powershell
docker compose run --rm --no-deps -v ./backend:/app -e FEC_CANDIDATE_MASTER_ZIP=/app/data/fec-candidates/cn24.zip -e FEC_CANDIDATE_SUMMARY_ZIP=/app/data/fec-candidates/weball24.zip api python tests/run_candidate_tests.py -q tests/test_fec_candidate_replay.py
```

2026-11-16 official input validation: candidate master 9,796 rows, SHA-256
`a9adf1ac1ffcd6d6fb93a4c6beabd9cac6e4baca547bd7f03d411409a28ecd8d`;
all-candidates summary 3,857 rows, SHA-256
`c50ec53096328242fb9618babe4cecffe43326736ead750cbe074bdfb7bc2a50`.
The master has eight missing House districts and three ID/office conflicts.
These are source observations, not verified links to MEDSL people.

## Local validation and current review state (2026-11-16)

- Full Python 3.12/PostgreSQL suite: 314 passed; one preexisting PDF extraction
  test initially lacked optional PyMuPDF. Installing the existing research
  dependency and rerunning that test passed. The final focused candidate,
  migration, official-file replay and PDF set passed all 24 tests.
- Frontend: 82 tests passed; strict TypeScript and production build passed.
- Headless Edge: real profile, finance, fusion-line result, committee, direct
  reload, history, correct House contest navigation, 375px layout, 503/retry and
  404 checks passed. Screenshots were inspected. No page errors or document overflow.
- Migration `candidate_identity_review` was applied locally after a custom-format
  database backup. Preexisting counts were unchanged: 1,680 candidacies, 686 contests,
  95,504 observations, 60,363 canonical returns and 11 source releases; publication
  pointers were identical. No existing vote values were changed.
- Local import: 9,796 candidate records and 3,857 finance summaries. Replays inserted
  zero records, reporting all records unchanged. Matching covered 1,133 2024
  candidacies and initially created 601 proposals plus 543 unmatched cases;
  multiple alternatives account for proposal counts exceeding candidacy counts.
  Matching replay left all 1,144 cases unchanged.
- One proposal was independently reviewed by the agent with explicit actor
  `codex:source-review`, not human approval: FEC `H8NY15148` and 2024 NY-14
  candidacy `7ed35b29-df5b-4ba7-848f-0e4e6966d2a6`. The evidence records both
  the [official FEC candidate page](https://www.fec.gov/data/candidate/H8NY15148/?cycle=2024&election_full=false)
  and [New York's official 2024 contest](https://results.elections.ny.gov/contest/5612).
  Its 132,714 published fusion-line votes and sourced principal committee were
  checked in the live profile. Reported receipts $15,299,235.57 and disbursements
  $16,716,492.89 agree with the FEC's displayed 2024 totals through December 31.
  Current state: **1 accepted, 600 pending, 543 unmatched**, no rejected cases.

Open the local example at
`http://localhost:5173/candidates/7ed35b29-df5b-4ba7-848f-0e4e6966d2a6`.
Ignored backup, screenshots, response and browser evidence are under
`artifacts/candidate-profiles/`; pinned inputs and local import reports are under
`data/fec-candidates/`. Other proposals still require evidence-based review.
Unmatched records may need authoritative aliases, corrected scope or additional
source records. Profiles intentionally show missing finance until their identities
are linked. Committee names, broader finance classifications and full cross-browser
acceptance remain separate dependencies.
