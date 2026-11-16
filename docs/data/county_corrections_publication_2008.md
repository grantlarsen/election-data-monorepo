# County corrections publication ? 2008

The authorized **283 county corrections are applied**. The active canonical
batch is `5d21c419-327d-4327-8251-c7bdd672448e`, fingerprint
`d96eaf9e15d05b9664f290e6e8df47a33f1b25cfb38eb343480ce2266d36b3bf`. Correction batch:
`46e321e9-b98f-4db5-a87c-ffc578cc3b51`. Review digest:
`596801cc989380199a7511b305c480f6aaa27b838b815102658d0eaa8432c9e5`.

| Result | Published value |
| --- | ---: |
| Corrected observations | 283 |
| Net correction votes | +89,944 |
| Previously resolved Virginia additions | 6 rows / 42,756 votes |
| Accepted rows | 9,336 |
| Exclusions | 138 |
| County votes | 130,679,051 |
| Coverage status | PARTIAL |

The original 9,330-row / 130,546,351-vote batch and all earlier batches remain
unchanged. The six additions and 117 existing geographic lineage changes use
already-published decisions; no geographic decisions or candidate identities
were created by this publication. The 283 old/new values and official-source
lineage are exported in `data/data005-county-apply/applied-283.csv`.

FEC state authority remains batch `5fc06d5d-d58e-4ca4-93f5-62ed675b51f8` with 131,313,820
votes. State and county figures are separate and non-additive. County totals
are a reconciled partial dataset, not a verified complete national county total.

## Validation

The final full offline/PostgreSQL suite passes **165 tests**, with zero failures,
errors or skips. The final run is `data/data005-county-apply/tests-release/`.
The earlier 163-test run preceded two regression cases. The first focused run
found a release-version length error, fixed before live migration; an intermediate
165-case run had one invalid synthetic geography fixture (164 passed), corrected
without changing production eligibility rules. The earlier automatic-review usage
hold is resolved; it did not result in an unreviewed execution path.

Migration `d005county01` is live; Alembic current/check pass. Original observations,
raw values, geographic decisions, identities and historical canonical rows were
verified unchanged. Only the expected source catalog records, correction records,
new 2008 canonical batch/returns/issues, and its active pointer were added/advanced.
Unrelated years and all FEC tables/pointers are preserved.

The dedicated correction publisher, default canonical publisher and FEC publisher
all replay **UNCHANGED**. All 42 public tables have identical fingerprints across
those replay checks. Publication, replay, schema and preservation evidence are in
`data/data005-county-apply/`. Source and evidence ZIPs are in
`artifacts/data005-county-apply/`, with SHA-256 manifests.

## Remaining work

The correction rollout is complete. Remaining evidence, conflict adjudication,
geography and coverage work now belongs to [DATA-029](county_verification_followup_2008.md). DATA-005 retains
its broader incomplete acceptance status; its remaining engineering estimate is
zero because the previous 24-hour low-confidence estimate is transferred to
DATA-029. Original acceptance criteria and historical verification reports are
preserved. No claim of full county/state/national county-derived coverage is made.
