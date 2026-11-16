# 2008 presidential returns — 2026-11-14

**Current follow-up:** the 283 supported county corrections have been published;
see [publication status](county_corrections_publication_2008.md). Remaining evidence and coverage
work is tracked as [DATA-029](county_verification_followup_2008.md). The original audit below is historical.

> **2026-11-15 update:** the 45 state/candidate discrepancies below have now been
> resolved through the user-authorized, live FEC state authority publication.
> See [fec_state_authority_2008.md](fec_state_authority_2008.md) for the current state totals, audit and
> source-precedence policy. This document preserves the initial delivery evidence;
> its no-publication statement and discrepancy blockers describe that earlier
> delivery. County verification and geographic holds remain outstanding.

**Status: Partially complete.** Independent reconciliation, coverage reporting,
all 144 original exclusion dispositions, tests, and a concrete canonical review
package are delivered. The acceptance requirement that state/county
reconciliations pass is not met. No live database records were changed by this
work, and no canonical publication was attempted.

## Verified live baseline

The active source is MEDSL V20.0, release
`5cc08608-a913-4ab6-a648-4a0a1e2814be`, with 9,474 observations for 2008.
Its archived original bytes match SHA-256
`9299583148f5f8264baf50b5d929c260699c46d915909b13ea3c3850918946f8`.
Alembic is at `d004a9c21e70`; read-only `alembic current` and `alembic check`
both exit 0 with no schema drift. No migration is required.

| Scope | Accepted rows | Excluded rows | Accepted votes |
| --- | ---: | ---: | ---: |
| Stored PARTIAL publication | 9,330 | 144 | 130,546,351 |
| Current read-only PARTIAL preview | 9,336 | 138 | 130,589,107 |

The stored batch remains `f44e7295-900f-47ec-9947-97d4c7c74ded`, fingerprint
`b0ff6b9c8c552810c16e1ea9e249a9e8c043a4db57c3db12477a91f1cbeaeee5`.
The current preview fingerprint is
`4e0d9ff4b150683fb48f34a55ed40b9bd54133222c265d3e1b0f5fc1ed1639b4`.
Neither accepted vote sum is a verified national total.

The repository's GEO-002 approval package records no authorization and its
documentation describes publication as pending. **The live database has since
advanced:** 95,920 decisions, 94,151 roots and heads, and five immutable contexts.
The 255 published 2008 successors were independently checked against their exact
GEO-002 subset manifests, predecessor IDs, full decision/evidence payloads,
context/publication digests and nonblank `published_by='glarsen'`. This is live
publication evidence, not an inference from the backlog's Done label. This task
does not certify all-year GEO-002 signoff or claim to have executed its live
publication/replay workflow.

## Independent results and their limits

[FEC Federal Elections 2008](https://www.fec.gov/documents/1660/2008pres.pdf)
provides all 50 states and DC. The parser verifies every state total against its
printed candidate components, uses combined-party totals rather than also adding
bracketed fusion ballot lines, and retains detailed component/page provenance.
MEDSL's three source buckets are compared as BARACK OBAMA, JOHN MCCAIN, and OTHER.
OTHER remains a residual containing minor candidates/write-ins where reported;
it does not create individual candidate identities or FEC person matches.

All source rows numerically match the three FEC buckets in **31 of 51 state/DC
scopes**. There are **45 nonzero bucket differences in 20 states**:
CO, CT, FL, GA, HI, IA, ID, IL, KY, LA, MA, MS, MT, NJ, NY, OH, PA, SD, TN, WY.
These comparisons include excluded MEDSL rows; geography approval alone cannot
explain or repair them. Exact differences, authoritative references, and
unverified causes are retained in `state-comparisons.csv`. No tolerance or source
correction was applied. The FEC's printed state totals sum to 131,313,820; the
MEDSL row-wise source bookkeeping sum is 131,187,337. Do not treat their net
difference as a list of missing votes: positive/negative candidate differences
and uncertain source-category semantics can offset each other.

Independent unit checks cover:

| Authority | Units | Result |
| --- | ---: | --- |
| [Alaska district reports](https://www.elections.alaska.gov/Core/Archive/08GENR/data/sovc/hd8.pdf) | 40 | All 120 candidate-bucket comparisons exactly match. Each final presidential district Total reconciles to its preceding precinct/mode rows; only the district Total is compared. Their statewide sum matches FEC. These are state House reporting districts, not counties. |
| [Missouri official manual](https://www.sos.mo.gov/cmsimages/BlueBook/2009-2010/7_Elec.pdf), PDF page 4, printed pp. 600–601 | 116 | All 348 candidate-bucket comparisons exactly match at the source election-authority/county reporting level. No county allocation is inferred for Kansas City. |
| [Minnesota archived county export](https://electionresults.sos.mn.gov/Results/MediaFile_Archive/Index?erselectionId=63&mediafileid=51) | 87 | All 261 candidate-bucket comparisons exactly match, including the excluded SAINT LOUIS rows. The archive index labels these results unofficial; the aggregate independently agrees with FEC. |
| [Virginia historical CSV](https://va2.elstats.civera.com/api/download_contest/39050_table.csv?split_party=false) | 134 | 400 of 402 bucket comparisons exactly match. MEDSL OTHER exceeds this export by 4 in Petersburg city and 13 in Richmond city. The export's Nader total is 11,466 versus FEC 11,483, explaining the 17-vote document difference but not its underlying cause. Both versions remain intact. |

These are source-scope comparisons. A county label match or a state total match
does not independently establish legal boundaries, complete county coverage,
non-overlap of special units, or canonical eligibility. Every other source unit
gets `EVIDENCE_UNAVAILABLE`, not a zero expected total or an invented pass.
Source, stored and preview comparisons are separate rows; summary comparison
counts therefore include three scopes rather than distinct independent checks.

The [Minnesota legislative manual](https://www.leg.mn.gov/archive/sessions/electionresults/2008-11-04-g-man.pdf),
PDF page 22 / printed page 494, omits 33 named write-in votes present in the
archived export. The 87-county cross-check proves every difference equals those
additional named write-ins. Raw export, manual, parsed components, and
`minnesota-manual-export-comparisons.csv` preserve that explanation.

The Minnesota archive uses its own county IDs, not Census county FIPS.
`docs/sources/minnesota_county_lookup_2008.csv` is an explicit transcription of the
[official lookup](https://electionresults.sos.mn.gov/Results/MediaFile_Archive/Index?erselectionId=63&mediafileid=6)
as returned by the web tool. Every name/order was independently checked against
the archived manual's 87 county rows. Direct subsequent lookup/layout requests
returned a CAPTCHA; the transcription is identified as an extraction, not an
archive of original lookup bytes. No lookup retrieval timestamp is invented.
The earlier successfully archived county results bytes are retained and verified.

## Every original exclusion

`original-144-dispositions.csv` preserves all original observation IDs, source
row numbers/hashes/releases, candidate votes, current decisions/actors,
preview eligibility, official comparisons where available, evidence and owners.
The original set is checked against the stored 144 exclusions and fixed partition
counts; it is not silently replaced by the preview's 138 exclusions.

| Partition | Rows | Disposition |
| --- | ---: | --- |
| AK districts 1–40 | 120 | Official district totals exactly reconcile; published non-county classifications; no county eligibility or allocation. |
| AK District 99 | 3 | All zero; year-specific definition remains unverified. GEO-002 owns the hold. |
| CT statewide write-in / ME UOCAVA / RI federal precinct | 9 | Published classifications, zero votes; placeholder/additive/overlap semantics remain unverified under DATA-005. |
| MO Kansas City | 3 | Exactly matches the official separate authority row: Obama 120,102; McCain 31,854; OTHER 1,263. Remains outside county canonical scope. |
| MN SAINT LOUIS | 3 | Official votes match: Obama 77,351; McCain 38,742; OTHER 2,721. GEO-002 must review/publish the source/year-specific alias and geographic decision before canonical eligibility. |
| VA Charles City / James City counties | 6 | Published exact county decisions are verified. All six source values match the official locality rows and enter only the preview. |

The already accepted Jackson rows exactly match the manual's separate Jackson
authority segment: Obama 90,722; McCain 92,833; OTHER 2,492. Together with Kansas
City they explain the state's omitted source segment, but neither exact numeric
match authorizes a whole-Jackson-county boundary claim or automatic aggregation.
The comparison report labels both as election-authority segments. Historical
coverage/non-overlap and any county aggregation policy remain DATA-005/QA-001.

RI's official results explicitly include limited precincts in town/state totals;
the MEDSL federal-precinct category is not separately added. Maine's archived PDF
includes OCR from its original scanning process, and CT's statement is scanned.
Their extracted text is retained as research, not verified evidence for special
row meanings. Later-year Alaska definitions are not projected into 2008.

## Canonical review and remaining work

`canonical-preview-changes.csv` contains six additions totaling **42,756** votes
and **117 lineage-only changes** among existing accepted rows, with no removals.
All original rows/decisions/batches remain immutable. A superseding publication
would have 9,336 accepted / 138 excluded rows and retain PARTIAL status.

`canonical-publication-review.json` binds source checksums, old batch,
current preview fingerprint/counts/votes, all changed observation IDs and
geographic heads, and the official evidence. Its exact review SHA-256 is
`fe3e75c048c3ed4b895831848b41f2c7ffcc608d562baeda97b7af074032c41b`.
It explicitly records no approving actor, no canonical supersession authorization,
and no publication attempt. Existing GEO-002 actor/digest evidence does not grant
canonical publication approval. A later publisher must recheck the current source,
predecessor and exact fingerprint and obtain approval for any changed scope.

| Owner | Requirement still preventing Done |
| --- | --- |
| DATA-005, coordinated with QA-001 | Investigate and resolve or explicitly adjudicate all 45 bucket discrepancies in 20 states using authoritative compatible sources; preserve versioned source corrections and their lineage. |
| DATA-005 | Extend independent county evidence beyond the checked states; obtain verified special-unit semantics; investigate the Virginia historical/FEC 17-vote conflict. |
| GEO-002 | Reviewed MN alias/geographic publication and 2008 District 99 evidence or explicit held disposition. Do not infer alias approval from numeric agreement. |
| DATA-005 / QA-001 | Historical Jackson/Kansas City reporting-area coverage and an evidenced non-overlapping county policy if county aggregation is requested. |
| Accountable canonical reviewer | Separate approval of the exact partial supersession package, followed by live publication, before/after audits and zero-new-batch replay. These live publication checks were not executed. |

Remaining effort is provisionally **24 engineering hours, low confidence**;
source availability may require re-estimation. The original eight-hour assumption
did not include the now-demonstrated 20-state source discrepancies. This is a
planning estimate, not a promise that historical evidence can be recovered on a
fixed schedule. DATA-005 remains Partially complete; other backlog rows are not
rewritten by this delivery.

## Implementation and validation

- `backend/ingestion/presidential_returns_2008.py`: strict source parsers, grouping, exact differences,
  evidence integrity and fixed exclusion accounting; no database writes.
- `backend/app/services/data005_{sources,extract,snapshot,reconcile}.py`:
  content-addressed raw archives, PDF extractions, REPEATABLE READ / READ ONLY
  snapshot, and offline coverage/reconciliation/publication-review reports.
- `backend/tests/test_data005_{offline,postgres}.py`: meaningful grouping,
  fusion/overlap/hierarchy, changed/missing evidence, alias-scope accounting,
  manifest/actor/payload integrity, real PostgreSQL snapshot and idempotence tests.
- Full current-source PostgreSQL suite: **132 passed, zero failures/skips** in
  the isolated `_test` database. Ten final offline tests also pass after the
  last test cleanup. The existing DATA-003 publication tests exercise test-schema
  publication; they do not stand in for live canonical supersession evidence.
- All **37 public-table fingerprints are unchanged** between fresh before/after
  inventories and independent DATA-005 snapshots. All five canonical stored
  batches/pointers, 94,151 observations, raw hashes, historical references and
  geographic decisions are preserved. DATA-004 archived files are unchanged.

Initial research attempts lacked PDF extraction dependencies, and host-only
Alaska requests failed certificate verification. Both are retained as failed
attempts; the final archive contains all 50 successfully retrieved original
documents/files using the container's normal certificate trust. No TLS validation
was disabled. A preliminary Minnesota lookup request selected a school-candidate
file; it was rejected as a lookup and is not used. Later CAPTCHA responses are
not election evidence even when HTTP status is 200. Parsers/checksums fail closed
on incomplete, changed or structurally invalid required inputs.

Current artifacts are under `data/data005/`: `evidence/`, `mn-additional/`,
`snapshot.json`, `snapshot-after.json`, `full-before.json`, `full-after.json`,
`full-preservation.json`, schema results, `tests/pytest.xml`, and `final/` reports.
These generated files are gitignored; source code, source requests, transcription,
documentation and backlog edits remain reviewable in Git. Delivery ZIPs under
`artifacts/data005/` include checksum manifests for portability.
