# DATA-005 county verification — 2026-11-15

**Subsequent publication:** all 283 supported proposals below are now applied in
batch `5d21c419-327d-4327-8251-c7bdd672448e` (130,679,051 votes; PARTIAL).
See [publication status](DATA005-APPLY-STATUS.md) and [DATA-029](DATA029.md) for
remaining work. The verification-stage account below is retained as historical
evidence; its statements about unpublished proposals describe that earlier stage.

County verification now runs nationwide, with observation-level evidence and
explicit remaining holds. **It does not support a complete national county
dataset.** DATA-005 remains **Partially complete**. No county values, geographic
decisions or canonical pointers were published by this work.

The earlier FEC state publication remains authoritative: 51 states/DC, 153
candidate buckets, **131,313,820 votes**, batch
`5fc06d5d-d58e-4ca4-93f5-62ed675b51f8`. See [DATA005-FEC.md](DATA005-FEC.md).
State results and county returns are different reporting levels and are never
added together.

## Measured results

| Check | Result |
| --- | ---: |
| MEDSL V20 observations inventoried | 9,474 |
| Original source reporting units | 3,158 |
| County-labelled observations, including the Jackson authority segment | 9,339 |
| Comparable Census/CQ county/bucket cells | 9,262 |
| Exact MEDSL/reference cells | 8,696 |
| Reference differences, each with its own disposition | 566 |
| Reference differences supported by election-authority correction proposals | 245 |
| Reference differences involving incomplete PA OTHER coverage | 58 |
| Reference differences still requiring comparable election-authority evidence | 263 |
| Source buckets with parsed election-authority values | 4,446 |
| Supported value proposals, including differences missed by the reference | 283 |
| Net votes in supported proposals | +89,944 |
| Original exclusion dispositions | 144 distinct observations |

There are **22 reviewed election-authority state/reporting-unit sets**. This
includes Alaska districts and Missouri segments; it does not mean 22 complete
county datasets. Only **California, Maryland, Oklahoma and Texas** pass the
current complete-*stored*-county checks: exhaustive county inventory, three
comparable buckets, exact official values, published/accepted geography and
exact FEC state rollups. Together these contain 413 counties/county equivalents.
Another 4,753 observations match the published reference but lack parsed
election-authority evidence. Such agreement is not labelled official verification.

The full current-source suite passes **158 tests, zero failures/errors/skips**,
including 20 county-specific cases. The runner records implementation hashes
before and after testing; packaging rejects later implementation changes. An
identical offline replay reproduces every report other than its generation
timestamp. Live read-only verification preserves all **40 public table
fingerprints**, all five historical county batches/pointers, source observations,
geographic decisions and the FEC authority. The first full run passed 157 tests;
the final run includes the additional accounting-relationship regression case.

## Evidence and comparison methods

[Census USA Counties 2011](https://www.census.gov/library/publications/2011/compendia/usa-counties-2011.html)
provides a nationwide independent published comparison in
[ELE01.xls](https://www2.census.gov/library/publications/2011/compendia/usa-counties/excel/ELE01.xls).
Its metadata identifies **CQ Press/SAGE**, not MEDSL, as the source. It is a
published compilation, **not an election authority**. Its metadata also retains
the original copyright notice; no different licence is asserted.

The parser locates the four absolute-count 2008 items by ID, validates their
year/unit/source declarations, and retains every availability flag, footnote,
worksheet and cell locator. Items are `ELE010208D` (total), `ELE020208D`
(Democratic), `ELE030208D` (Republican), and `ELE060208D` (other). Flag 3 means
unavailable, not zero. In particular, the 29 Alaska county-equivalent entries
cannot supply county returns; Oklahoma's 77 unavailable OTHER cells require
its official two-candidate county table to establish zero remaining candidate
votes. Retired/not-applicable entries are not treated as zero-vote counties.

`reference-hierarchy.csv` preserves differences between the publication's
national, state and county-labelled figures. Footnote 6529 states that the
state total includes overseas ballots. A footnote, state sum or county FIPS
label is not a substitute for matching reporting coverage.

Parsed election-authority sets are AK, CA, CO, CT, FL, HI, ID, IL, MA, MD, MN,
MO, MT, NJ, NY, OK, PA, SD, TN, TX, VA and WY. Extraction uses CSV/TSV/HTML,
PDF text or PDF word coordinates as appropriate. Coordinate extraction preserves
adjacent numeric cells that plain/layout extraction can concatenate. Scanned
Montana and Wyoming tables have checked numeric transcriptions with source
checksums and printed-column controls in
[DATA005-county-reviewed.json](../sources/DATA005-county-reviewed.json).
The review is numeric evidence, not geographic publication approval.

All raw responses retain URL, retrieval timestamp, checksum and transport
status. The source inventory distinguishes numeric evidence, controls,
crosswalks, alternative extracts and unused research responses. HTTP 200 alone
does not establish valid election data. Failed requests remain recorded rather
than becoming zero votes or mismatches. Host Iowa retrieval additionally
reported an expired TLS certificate; TLS verification was not disabled.

## Findings and holds

| Evidence | Finding and treatment |
| --- | --- |
| Wyoming official canvass, PDF p1 | All 23 OTHER excesses exactly equal printed under- plus over-votes: 1,377 ballots. Exclude those ballot-accounting categories from candidate OTHER. |
| New Jersey official tallies, PDF pp1–10 | All 21 OTHER shortfalls exactly equal official Nader plus Barr counts: 29,739 votes. Preserve raw OTHER as an unidentified aggregate. |
| South Dakota county table | All 66 OTHER shortfalls exactly equal official Nader counts. The official table supplies the proposed totals; no identity is assigned to the raw OTHER group. |
| Montana canvass p1 and write-in pp1–4 | Add only the 193 presidential write-ins. Legislative columns on pp4–5 account exactly for 18 county OTHER excesses (4,144 votes); they never enter presidential totals. Broadwater's remaining three differences use its printed presidential counts and are separate. |
| Colorado general-election abstract, PDF pp93–95 | Official county values locate all 101 votes separating the older MEDSL/reference totals from FEC; 19 bucket proposals. Primary and general sections are never combined. |
| Illinois `GE2008Cty.txt` and state controls | Williamson County accounts for all three differences: Obama 12,589, McCain 17,039, OTHER 513. No election-authority segments are added to county totals. |
| New York official county CSV | Include scattering as OTHER; exclude blank and void ballots. Preserve combined-party candidate columns once. Scattering alone explains 48 shortfalls; other changes retain exact official comparisons. |
| Connecticut official 169-town CSV | Use only town rows, excluding state and polling-place subtotals and both ballot-total columns. A checked 2000/2010 Census crosswalk produces eight county comparisons matching FEC statewide. It is comparison evidence; intervening legal boundary dates remain unverified. |
| Idaho official county CSV | The newer export supplies 90 named write-ins absent from the old five-candidate table. Identical repeated total rows are not counted as counties. Bannock's candidates sum to 35,111 while the printed total is 35,105; the site warns of preserved data-entry errors. Its six-vote OTHER proposal is withheld for adjudication. |
| Pennsylvania certified API | Election catalog and metadata prove ID 17, general election 2008-11-04, Official. ID 27 is 2012 and is rejected. The county API includes Obama, McCain, Nader and Barr only. FEC has 18,135 additional write-in votes; county OTHER is therefore an incomplete comparison, not a supported replacement. Two Delaware major-candidate corrections are independently evidenced. |
| Pennsylvania precinct file | Preserve this alternative official extract and its 2009 schema separately. It contains 12,621 write-ins but does not reconcile to the certified API/FEC; incomplete precinct and certified county totals are not combined. |
| Virginia historical export | Petersburg OTHER is four lower and Richmond OTHER is 13 lower than MEDSL/reference; its state sum is also 17 below FEC. Both changes are withheld. FEC remains authoritative at state level. |
| Hawaii final county reports | Four election-authority reports match MEDSL/reference but omit 826 votes relative to FEC state totals. Retain overseas-ballot footnote and missing Kalawao reporting coverage; do not allocate state-only votes or manufacture a Kalawao return. |
| Missouri manual, PDF p4 | Jackson and Kansas City have separately reported authority segments. Their numbers can be checked individually, but neither the Census Jackson label nor matching arithmetic proves historical coverage/nonoverlap. State aggregation is withheld; Kansas City remains excluded from canonical counties. |
| Minnesota actual county export/lookup | All 87 county comparisons include named and scattered write-ins. The original archived lookup replaces the earlier manual lookup for this comparison. SAINT LOUIS numerical agreement does not publish its source/year-specific geographic alias. |

Exact arithmetic accounting is distinguished from proof of the historical
extraction process. The ledger does not infer which individual candidates
comprised raw grouped OTHER. Where a certified county value differs but the
historical cause is not established, that limitation remains explicit.

The **263 authority-evidence holds** are GA 12, IA 83, KY 26, LA 22, MS 80 and
OH 40. Their exact observations, signed differences and required evidence appear
in `authority-evidence-requests.csv` and `discrepancy-566-dispositions.csv`.
Owners are the respective election authority's records custodian and the
DATA-005 data maintainer. Public downloads that returned 403/520, incomplete
tables and scanned material without a checked extraction are documented;
they are not marked verified. Authority coverage outside the reviewed sets also
remains necessary before an exhaustive official-source claim.

## Original exclusions and publication

The original 144-row ledger is checked against the handoff IDs, row checksums
and vote counts. It retains AK district 1–40 (120), AK District 99 (3),
CT/ME/MO/RI special units (12), MN SAINT LOUIS (3), and VA county-label rows (6).
The 120 Alaska district values have official district evidence but no county
eligibility. District 99 and the nine zero CT/ME/RI rows retain semantics holds.
Jackson's three already-accepted observations are reviewed alongside the
three excluded Kansas City observations (153,219 votes). No segment allocation
or aggregation is approved here.

The live MEDSL county batch remains PARTIAL with **9,330 accepted, 144 excluded,
130,546,351 votes**, fingerprint
`b0ff6b9c8c552810c16e1ea9e249a9e8c043a4db57c3db12477a91f1cbeaeee5`.
Verified current geographic decisions produce the existing unpublished preview
of **9,336 accepted, 138 excluded, 130,589,107 votes**, fingerprint
`4e0d9ff4b150683fb48f34a55ed40b9bd54133222c265d3e1b0f5fc1ed1639b4`.
All historical geography and explicit actor/digest requirements remain intact.

The 283 supported numeric proposals would add **89,944** votes. Applying them
to the current geography preview gives an **arithmetic scenario** of
**130,679,051 votes**, still PARTIAL with 138 exclusions. The 634,769-vote
difference from FEC consists of 598,230 excluded source votes plus 36,539
remaining source/coverage difference. No residual is allocated to counties.

`correction-manifest.json` is a reviewable verification proposal, **not an
executable canonical publication**. Its correction digest is
`596801cc989380199a7511b305c480f6aaa27b838b815102658d0eaa8432c9e5`.
The existing canonical adapter requires immutable MEDSL observations; changing
its votes would violate that contract. The backend/data maintainer must first
implement reviewed append-only source corrections, retain supported grain and
geographic decisions, and obtain any required actor/digest and separate canonical
publication authorization. Source-policy approval at state level does not supply
county attribution or these publication approvals.

DATA-005 cannot be Done until the remaining evidence, geographic/coverage
decisions, reviewed county corrections and authorized canonical publication are
supported. [The PowerShell runbook](DATA005-COUNTY-RUNBOOK.md) reproduces the
audit and the explicit incomplete-coverage gate.

## Artifact locations

`data/data005-county/final/` contains the observation comparisons, all 566
dispositions, 283 correction proposals, all 144 original exclusions,
reporting-unit and state coverage, reference hierarchy, official candidate
components, source inventory and review manifest. `live-final/` contains
read-only preservation and FEC authority proof; `tests-final/` contains the full
JUnit report and source hashes. Raw evidence remains in the `raw*` directories
and `mn-input/`. Earlier research runs are retained.

`artifacts/data005-county/` contains checked source/evidence ZIPs with per-file
SHA-256 manifests and `delivery.json`. Prior DATA-005/FEC packages and the user's
fresh-evidence directories are preserved.
