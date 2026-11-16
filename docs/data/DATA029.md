# DATA-029: close 2008 county verification and reporting-unit coverage gaps

This task owns the work remaining after publication of DATA-005's 283 supported
county corrections. The active PARTIAL county batch is
`5d21c419-327d-4327-8251-c7bdd672448e`: 9,336 accepted rows, 138 exclusions and
130,679,051 votes. FEC state authority remains unchanged at 131,313,820 votes.
See [publication evidence](DATA005-APPLY-STATUS.md) and the historical
[county verification report](DATA005-COUNTY.md).

Priority: P0. Status: Not started. Remaining engineering estimate: **24 hours,
low confidence**, transferred from DATA-005 rather than counted twice. Waiting
for records or approvals is separate from that engineering estimate.

## Required work and owners

| Work | Exact remaining requirement | Owner |
| --- | --- | --- |
| Authority evidence | 263 county/candidate differences: GA 12, IA 83, KY 26, LA 22, MS 80, OH 40. Obtain comparable certified 2008 candidate/write-in returns with archived raw files, URLs, retrieval dates, checksums and precise locators. | Respective state records custodians; data maintainer |
| Official coverage | Extend parsed election-authority coverage beyond the 22 reviewed state/unit sets. 4,753 observations match the independent published reference but lack parsed authority evidence. Matching FEC state sums alone is insufficient county proof. | Data maintainer |
| Pennsylvania | Adjudicate 18,135 FEC write-in votes without county attribution in the certified county API. Retain the conflicting/incomplete precinct extract separately. Of the original reference differences, 58 involve incompatible OTHER coverage; all 67 PA OTHER groups need an explicit coverage disposition. | Pennsylvania election authority; data maintainer |
| Idaho | Resolve Bannock's six-vote difference between printed candidate sum and ballot total. The withheld OTHER proposal was not published. | Idaho election authority; data maintainer |
| Virginia | Resolve Petersburg OTHER four lower and Richmond OTHER 13 lower in the historical export. Preserve FEC state precedence; both county proposals remain withheld. | Virginia election authority; data maintainer |
| Minnesota | Review source/year-specific SAINT LOUIS alias evidence and publish an approved geographic decision before canonical inclusion. Numerical agreement does not grant eligibility. | Geography reviewer / GEO-002 |
| Missouri | Establish historical Jackson/Kansas City election-authority coverage and overlap before aggregation or a complete Jackson County claim. Review the three accepted Jackson segment observations alongside the excluded Kansas City rows (153,219 votes). | Missouri/local election authorities; geography reviewer |
| Connecticut | Validate the intervening historical town/county assignments used by the 2000/2010 comparison crosswalk. | Geography reviewer |
| Alaska and special units | Preserve district 1–40 returns at district grain. Establish District 99 semantics and the meaning of the zero-vote CT/ME/RI special units. Do not allocate Alaska districts to counties or infer meanings from zero votes/later elections. | State election authorities; geography reviewer |
| Hawaii | Establish overseas/Kalawao coverage and the 826-vote state/county-report residual without manufacturing county attribution. | Hawaii election authority; geography reviewer |
| Reconciliation | Make continuing county comparisons use the active corrected canonical values while preserving raw MEDSL comparisons and the fixed original 144-row exclusion ledger. Report accepted/excluded votes by state/reason, unresolved evidence and unallocated residuals. | Backend/data maintainer |
| Publication | Prepare any newly justified append-only source/geographic/canonical changes; obtain explicit actor/digest and separate canonical authorization where required; verify expected changes, historical preservation and identical replay. | Authorized reviewers/publisher |

## Acceptance

Every remaining observation-level question has an independently supported
resolution or an explicit reviewed coverage restriction. Distinguish missing
evidence, demonstrated mismatches, incomplete candidate groups, authority
segments, district results and state-only votes. Preserve grouped OTHER without
assigning inferred individual candidate identities.

Maintain a county/reporting-unit and state candidate coverage matrix with source
lineage, comparable scope, expected/observed counts and exact differences. A
reported zero, an unavailable value and an unknown unit meaning are distinct.
Preserve immutable observations, released references, identities, historical
decisions and all canonical/FEC history. Do not relax eligibility to increase
coverage or absorb unrelated 2020/2024, candidate matching or geometry work.

Additional publication must have a concrete reviewed preview, meaningful tests,
PostgreSQL validation, expected append-only changes and no extra rows on replay.
Retain PARTIAL status and explicit unallocated residuals whenever complete
county/state/national county-derived coverage is not established. Completion
must state whether the supported product is complete at a reporting grain or
a reconciled partial dataset; task status alone cannot stand in for approval.

## Starting evidence

- `data/data005-county/final/authority-evidence-requests.csv`
- `data/data005-county/final/discrepancy-566-dispositions.csv`
- `data/data005-county/final/original-144-dispositions.csv`
- `data/data005-county/final/state-coverage.csv` and `reference-hierarchy.csv`
- `data/data005-county-apply/applied-283.csv` and `verification.json`
- `docs/sources/DATA005-county-sources.json` and the archived raw evidence

The 566 ledger is a frozen comparison of original source values. Of those
differences, 245 are supported by applied corrections, 58 concern incomplete PA
OTHER grouping and 263 still require comparable authority evidence. The 283
applied changes also include 38 differences discovered beyond that reference
screening. Do not mistake the frozen ledger for a claim that corrected current
canonical values still have all 566 original differences.
