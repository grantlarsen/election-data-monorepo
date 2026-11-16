# FEC authority resolution — 2026-11-15

The FEC state publication below remains unchanged after the subsequent county
corrections. See [county publication status](county_corrections_publication_2008.md) and
[DATA-029](county_verification_followup_2008.md) for the current county batch and remaining coverage work.

**All 45 original state/candidate discrepancies are resolved by the user's
explicit FEC source-precedence instruction.** The live authoritative state
publication now equals FEC in all 153 buckets across the 50 states and DC.
The original MEDSL/county comparisons remain available as historical evidence.
DATA-005 itself remains Partially complete because county verification,
geographic holds and reporting-unit coverage are separate requirements.

## Published result

| Item | Verified value |
| --- | --- |
| Authoritative source | [FEC Federal Elections 2008 presidential results](https://www.fec.gov/documents/1660/2008pres.pdf) |
| Original PDF SHA-256 | `2557034646f1bdb949ce79a51ba9b2d7d5422b176cae89fd615c7dacf8392f92` |
| Source release | `8778d3b2-1942-4452-b6a6-c4c5f0e4ee4a` |
| Authority scope | `president:general:2008:state:TOTAL` |
| Live authority batch | `5fc06d5d-d58e-4ca4-93f5-62ed675b51f8` |
| Reviewed/published fingerprint | `1a9acd697b7def975dc0bffd11bf1462d8b8529ebc8624e8559301796da1f062` |
| Publisher | `codex`, executing the recorded user instruction |
| Authoritative state vote sum | **131,313,820** |
| Resolved source differences | **45 buckets in 20 states** |
| Remaining FEC/authority differences | **0** |
| Net adjustment relative to all MEDSL source rows | **+126,483** |
| Publication replay | **UNCHANGED**, same batch, no extra rows |
| Migration | `d005fec2008a`, additive; Alembic current/check pass |

The batch records the authorization verbatim: “Handle resolving the 45
discrepancies and treat the fec data as the source of truth where stored data is
different from it.” The existing GEO-002 actor is not used to imply new approval.

Each state return records its FEC vote count, MEDSL source and stored county
counts, signed source adjustment, original FEC candidate components and exact
PDF page/state locator. OTHER remains an aggregate of the publication's
remaining candidates and write-ins. Combined-party candidate totals are used
once; bracketed fusion components are not counted again.

`data/data005-fec/resolved-45.csv` contains exactly the original 45 discrepancies,
with old values, FEC replacements and signed corrections. The audit compares
its state/bucket/old/new tuples to the original `state-comparisons.csv`, so
unrelated source rows cannot quietly become part of the correction scope.
`authoritative-state-results.csv` contains all 153 published buckets.

This resolves the authority choice and stored state values. It does not establish
why each historical MEDSL value differed or where within a state those votes
belong. Source differences are explicitly **UNALLOCATED below state level**;
no proportional allocation, invented county observation or negative county
return was created.

## Source corrections versus county coverage

| Comparison | Votes |
| --- | ---: |
| Original stored partial MEDSL county batch | 130,546,351 |
| MEDSL excluded source rows | 640,986 |
| All MEDSL source rows, bookkeeping sum | 131,187,337 |
| Net FEC source-precedence correction | +126,483 |
| Authoritative FEC state sum | 131,313,820 |

The 640,986 excluded votes are a coverage difference, not part of the 45 source
corrections. Alaska districts, Kansas City and other excluded units were not
silently inserted into county results. The six Virginia county additions from
the earlier proposal and MN alias approvals were not published by this work.

Virginia's whole-state MEDSL totals already agree with FEC. FEC is now the
authoritative state value even though Virginia's historical export lists 17
fewer Nader votes. The Petersburg/Richmond county-report differences remain
visible; a whole-state authority choice does not independently prove their
county-level correction.

## Storage and consumption

The existing canonical county return requires county geography and one MEDSL
observation per row. A FEC whole-state result has a different grain and source.
The additive `state_result_batch`, `state_vote_return`, and
`state_result_publication` tables reuse the existing source-release catalog,
state jurisdictions, presidential office/term, election and contest models.
The Alaska 2008 state election/contest is the only newly needed event/contest.

Consumers requesting state totals should use:

```python
from app.services.canonical_results import state_totals

all_states = state_totals(session, year=2008)
new_york = state_totals(session, year=2008, state_code="NY")
```

This accessor reads the active FEC-backed publication and verifies stored rows
against its immutable manifest. It explicitly returns `reporting_level='state'`,
`additive_with_county_returns=False` and `county_coverage_verified=False`.
It rejects unsupported years/states or a missing/incomplete authority
publication. The existing `candidate_totals` county function retains its own
grain and partial-coverage contract. State and county returns must never be
added together. The project currently has no election-results HTTP endpoint;
the future results API should use this state accessor for its state totals.

Database protections prohibit updating/deleting authority batches/returns,
reject wrong state/contest targets, and prevent publishing a pointer until all
51 states/DC and three buckets exist. Vote counts are nonnegative; signed
adjustments are separate fields with `FEC = MEDSL source + adjustment` enforced.
Publication checks the exact source/input/baseline fingerprint before writes,
uses a transaction lock, and replaces only the state publication pointer.

## Validation and preservation

The full current-source PostgreSQL suite passes **138 tests, zero failures or
skips**. It covers FEC
increases/decreases, OTHER/write-ins, missing/tampered inputs, stale review
rejection, late rollback, source supersession, cached pointer refresh,
idempotence, immutable history, target scope and complete publication gates.
See `data/data005-fec/tests-final/pytest.xml` for the exact final count.
An initial test run caught a reserved SQL identifier in a check constraint;
it was corrected to `authorization_note` before the live migration.

The live before/after audit proves:

- All 32 original tables outside the authorized append/revision tables have
  identical complete fingerprints, including observations, geography, identity,
  offices/terms and all five county canonical batches/returns/issues/pointers.
- All existing rows in `data_source`, `source_release`, `election`, and `contest`
  remain identical by primary key/content hash. Each gained exactly one row.
- The schema revision advanced once, and the three new tables contain exactly
  one batch, 153 returns and one active pointer.
- The registered FEC release's archived original PDF hash is correct.
- The identical live publication replay returned UNCHANGED.

The current follow-up artifacts are in `data/data005-fec/`: fresh baseline,
preview, publication receipt, replay receipt, protected before/after hashes,
`resolution-audit.json`, correction/result CSVs, schema reports and tests.
The original `data/data005/final/` remains the historical raw-source comparison;
its 45 MISMATCH records are resolved by the new authority publication rather
than erased. The original ZIP delivery remains historical; updated follow-up
bundles are under `artifacts/data005-fec/`.

## Reproduction and verification

These commands read the published result without changing records:

```powershell
docker compose exec -T api python -c "from app.database import SessionLocal; from app.services.canonical_results import state_totals; import json; s=SessionLocal(); print(json.dumps(state_totals(s,year=2008),indent=2))"
```

For a fresh preview, choose an unused output file:

```powershell
docker compose exec -T api python -m app.services.fec_state_results --evidence-dir /app/data/data005/evidence --output /app/data/data005-fec/preview-recheck.json
if ($LASTEXITCODE -ne 0) { throw 'FEC preview verification failed' }
```

Replaying the authorized exact publication should return UNCHANGED:

```powershell
docker compose exec -T api python -m app.services.fec_state_results --evidence-dir /app/data/data005/evidence --output /app/data/data005-fec/replay-recheck.json --publish --expected-fingerprint 1a9acd697b7def975dc0bffd11bf1462d8b8529ebc8624e8559301796da1f062 --actor codex
if ($LASTEXITCODE -ne 0) { throw 'FEC replay failed' }
```

The recorded instruction authorizes this FEC precedence scope. A changed source,
comparison batch, jurisdiction selection or fingerprint requires fresh review;
the tool rejects the old fingerprint. Original county publication and geographic
approval workflows retain their separate requirements. Do not run the old
zero-change GEO-001 audit assertion as an expected post-migration result;
use the scope-aware `fec_state_audit` protected-row verification.
