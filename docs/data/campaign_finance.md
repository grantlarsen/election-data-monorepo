# Campaign committee and financial snapshot contract

DATA-008 extends the identity and provenance foundations. Canonical committees
already exist as `organization(kind='committee')`, FEC IDs as
`external_identifier`, and reviewed committee/person/candidacy associations as
`committee_relationship`. Candidate matching also provides immutable
`fec_candidate_record` and `candidate_finance_summary` rows. These are reused;
existing candidate profile responses and financial definitions remain compatible.

## Source specifications and design

Official references checked November 16, 2026:

- [Committee master](https://www.fec.gov/campaign-finance-data/committee-master-file-description/)
  identifies each committee and supplies its name, type, designation and other
  registration attributes. These attributes can change between releases/cycles.
- [Candidate–committee linkage](https://www.fec.gov/campaign-finance-data/candidate-committee-linkage-file-description/)
  distinguishes the candidate election year from the active two-year FEC period.
  The committee ID is nullable. Principal/authorized designations are distinct
  from leadership PACs, joint fundraisers and unauthorized committees.
- [Committee summary](https://www.fec.gov/campaign-finance-data/committee-summary-file-description/)
  contains cumulative two-year activity and actual coverage dates. Different
  committees can have different coverage endpoints. Cash and debts are balances.
- [Report summary metadata](https://www.fec.gov/campaign-finance-data/committee-report-summary-file-metadata/)
  describes individual reporting periods, whose summaries reflect amendments.
- [OpenFEC documentation source](https://github.com/fecgov/openFEC/blob/develop/webservices/docs.py)
  defines two-year cycles, filing identifiers, amendment chains and
  `is_amended`: false means the report has not been superseded; null is unknown.
  Receipt dates can be later than the year/cycle being reported.
- [All-candidate summaries](https://www.fec.gov/campaign-finance-data/all-candidates-file-description/)
  combine authorized committees and describe transfer adjustments. Existing
  candidate profile calculations already implement that source's rule.

A financial cycle is the even ending year of a two-year period, January 1 of
the preceding odd year through December 31 of the even year. Senate and
presidential election years do not redefine this period. Odd-year special
elections remain valid election years; `cycle_for_date` returns the following
even financial cycle. A committee and candidate ID can participate in several
financial cycles while retaining a different candidate election year.

## Persistence

The additive `campaign_finance` revision follows `candidate_identity_review`.
Historical migrations are unchanged. It adds:

| Table | Grain and purpose |
| --- | --- |
| `fec_committee_record` | One committee ID per release and financial cycle; versioned name, type, designation, filing frequency, organization type and original record. Canonical organization identity is obtained through the existing external identifier. |
| `fec_candidate_committee_link` | One FEC linkage ID per release; candidate ID, nullable committee ID, candidate election year, financial cycle, source designation/type and original record. Unresolved IDs remain usable without invented people or candidacies. |
| `committee_filing` | One source record key per release; committee, financial cycle, file number if available, form/report codes, original amendment flag, nullable source amendment status, receipt and coverage dates, raw record and optional predecessor. |
| `committee_finance_snapshot` | One source record key per release; committee, cycle, exact coverage, report/cycle grain, optional filing, official USD amounts, raw record and optional correction predecessor. |

All four tables require `source_release`, which supplies source, version, hash,
retrieval/publication dates and immutable raw artifact location. Existing
`ingestion_run.release_id` records importing runs. Importers must create/finalize
their run using the shared ingestion infrastructure; the persistence service does
not acquire data, invent retrieval times, or own transaction/run lifecycles.

Report snapshots have exactly one filing and match its committee, release,
cycle **and coverage dates**, enforced by a composite foreign key. There is at
most one snapshot per filing observation. Filing predecessors must belong to the
same committee/cycle. Snapshot correction predecessors must have the same
committee, cycle, grain and coverage. A filing can amend coverage dates; its
predecessor is retained, and its new snapshot uses the corrected dates.

Paper filings may have no electronic file number. Use the source's stable
record/image/submission identifier as `source_record_key`; do not substitute a
hash of dates or a generated row number without a documented source contract.
Non-null file numbers are unique within a release, even when supplied under
different source record keys.
`previous_file_number` preserves unresolved amendment references when the
predecessor has not been imported. Do not infer a predecessor from equal dates.
Source flags and raw amendment codes remain available when lineage is incomplete.

`committee_relationship` gains an even-cycle constraint for non-null cycles;
null still represents a historical association with unknown cycle. The existing
identity service rejects invalid cycles before writing. Source linkages do not
automatically create canonical associations: resolve identities and establish
authorization with evidence using the existing matching/review workflow.

## Writes, corrections and reads

`app.services.campaign_finance.store_finance_record(session, transient_record)`
validates FEC identifier types, release existence, cycle/period rules, lineage,
timezone-aware receipt dates and exact Decimal amounts. It returns
`(stored_record, inserted)`:

- New observation: `inserted=True`.
- Identical replay: same stored ID, `inserted=False`.
- Different payload at the same release/source key: `IdentityConflictError`;
  it does not overwrite or silently ignore a correction.

The caller owns the transaction. Rollback removes the entire uncommitted batch.
For a corrected download, register a new hash-addressed release and append
records. Optionally reference the prior observation using `supersedes_id`.
Unchanged file bytes should resolve to the existing release. Importers count
`inserted=True` as inserted and `False` as unchanged; append-only corrections
are new observations, not in-place updates. These are persistence operations,
so excluded/rejected counts and durable failed-run reporting belong to the
source adapter. No FEC acquisition or production import is added by DATA-008.

Money uses `NUMERIC(18,2)` and Python `Decimal`. Missing stays null; zero and
negative corrections remain distinct. Floats, nonfinite values, excess precision
and out-of-range amounts are rejected before PostgreSQL can round them. Snapshot
fields include receipts, disbursements, beginning/ending cash, debts owed by/to,
authorized transfers and independent expenditures. Other source fields remain
in `raw_json` pending a defined ingestion/classification use case.

`committee_finance` requires committee ID, pinned release, financial cycle,
coverage start/end and report/cycle grain. It returns one eligible snapshot or
an explicit `missing`, `unverified`, `partial` or `ambiguous` status:

- Both **Total Raised** and **Total Spent** are always present. At committee
  grain they are reported receipts/disbursements, labeled
  `reported_committee_totals`, with no invented transfer adjustment.
- No summation occurs across releases, overlapping reports, cumulative cycle
  summaries, committees, candidacies or candidate summaries.
- Explicit predecessors in the pinned release are excluded. Report snapshots
  additionally require source `is_amended=False`; unknown finality is unverified.
  Multiple surviving rows are ambiguous, even if their totals happen to agree.
- A historical pinned release describes what that source asserted at retrieval;
  a later amendment in another release does not rewrite the historical result.
- Balances are never added across reporting dates. Different committee coverage
  endpoints must be reconciled before candidate aggregation can be implemented.
- Committee independent expenditures remain separate source fields. A committee
  linkage does not assign those expenditures to a candidate's direct financing.

The existing candidate profile continues selecting its candidate-level source
summary. It must not add committee snapshots to those totals. Donor thresholds,
itemized/unitemized classifications and candidate committee aggregation are
outside this schema task.

The service is the supported write boundary. Database constraints protect keys,
periods and referential scope; namespace/type semantics and append-only payload
comparison are service validations. Direct SQL updates bypass the append-only
contract and are not supported ingestion operations.

## Verification and local rollout (PowerShell)

From the repository root, run the relevant tests in a temporary Python 3.12
container using a guarded disposable database ending `_test`. The shared runner
accepts arbitrary pytest arguments despite its candidate-oriented default list.

```powershell
docker compose run --rm -v ./backend:/app api sh -c 'python -m pip install -q -r requirements-dev.txt && python tests/run_candidate_tests.py --create-test-db -q tests/test_campaign_finance.py tests/test_candidate_identity.py tests/test_candidate_migration.py tests/test_identity.py tests/test_identity_migration.py'
```

Before upgrading a development/shared database, inspect existing non-null
`committee_relationship.cycle` values for odd years or values outside
1788–9998. The migration deliberately fails on invalid existing values; correct
them from source evidence rather than silently reinterpreting election years.
Back up the database using the established local backup procedure, then apply:

```powershell
docker compose run --rm -v ./backend:/app api alembic current
docker compose run --rm -v ./backend:/app api alembic upgrade head
docker compose run --rm -v ./backend:/app api alembic check
```

The host mount is needed because migrations are baked into the API image.
Rebuild that image when distributing the revision without the source mount.

Coverage includes offline DDL, real PostgreSQL upgrade/downgrade and metadata
comparison, identity/profile regressions, unchanged replay, source-key conflicts,
overlapping financial cycles, odd-year elections, paper filings, amendments with
corrected coverage, signed/null/zero amounts, exact-period selection, ambiguous
observations, rollback and database-enforced report/filing scope.

DATA-009 remains responsible for pinned FEC committee/linkage/filing/summary
adapters, operational imports, failed-run/rejection reporting, and same-period
reconciliation against at least 25 selected House campaigns. Synthetic tests
here establish schema and persistence behavior; they do not verify live totals.

## Verified local state, November 16, 2026

- All 356 backend tests passed in the Python 3.12 API image against the
  PostgreSQL 18 disposable database, with no skips. This includes the full
  pinned candidate master/summary import and unchanged replay, enabled by
  `FEC_CANDIDATE_MASTER_ZIP=/app/data/fec-candidates/cn24.zip` and
  `FEC_CANDIDATE_SUMMARY_ZIP=/app/data/fec-candidates/weball24.zip` on the test
  container. Optional research dependencies were installed for the full suite.
- The local development database was upgraded from `candidate_identity_review`
  to `campaign_finance` after a full custom-format `pg_dump` backup. The archive
  manifest was read successfully; its SHA-256 and before/after row-count audits
  are stored alongside
  `data/backups/campaign-finance-20261116-cbb93c87.dump`.
- All 47 pre-existing table row counts were unchanged. The four new tables are
  empty; no committee or filing import was performed. `alembic check` found no
  schema drift. Other environments still require the additive revision.
