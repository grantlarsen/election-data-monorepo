# 2024 U.S. House district returns

The House adapter reuses immutable source releases, ingestion runs, observations,
canonical contests/candidacies/ballot lines, geographic references and publication
pointers. It imports the 2024 **regular general election**, including DC's delegate.
Other years, primaries, specials and runoffs remain in the archived original file.
No person matching, district polygons or election winner inference is performed.

Before this change, those shared tables and read APIs existed, but no House adapter,
district reference loader, House observations or House publication existed.

## Sources and decisions

- [MEDSL U.S. House 1976–2024](https://doi.org/10.7910/DVN/IG0UN2),
  Harvard Dataverse V15.0, released March 9, 2026. Original file ID `13592823`,
  `1976-2024-house.tab`, 4,156,562 bytes, SHA-256
  `76eec42483ee9f0fc5cf6e377442c783d1ae6eefa929729fd6561a69bab47f2a`.
  The original is comma-separated despite its extension and MIME type.
  Use `?format=original`; the archive MD5 describes a different representation.
  License: CC0 1.0. Dataverse requires guestbook 458; the existing acquisition
  implementation uses the user's configured answers without inventing identity data.
- [MEDSL codebook](https://dataverse.harvard.edu/api/access/datafile/12066703?format=original)
  establishes party-line votes and the at-large district convention. Fusion lines
  are additive within a source-scoped candidacy. A repeated candidate label without
  a fusion indicator is withheld for review. Canonical person IDs remain null.
- [Census 2024 Gazetteer](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2024.html),
  [119th Congress ZIP](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_119CDs_national.zip),
  SHA-256 `544b14949130dfa5e07bf3179854a8138deefa825ad6e8187057de175d71b17d`.
  Its 440 rows include Puerto Rico and three undefined `ZZ` areas, which are
  explicitly excluded. The remaining 436 are 435 voting districts plus DC.
  [Census district conventions](https://www.census.gov/geographies/mapping-files/2025/dec/rdo/119-congressional-district-bef.html)
  distinguish `00` at-large, `98` nonvoting delegate and `ZZ` undefined areas.
  MEDSL DC district `0` maps explicitly to Census `1198`. State at-large districts
  retain `00`. District identities are scoped to the 119th Congress to avoid
  silently reusing a code across redistricting. No legal effective dates are
  inferred from a statistical reference; no geometry is loaded.
- [House Clerk's official 2024 election statistics](https://clerk.house.gov/member_info/electionInfo/2024/statistics2024.pdf)
  provides independent reference checks. PDF page 4 has Alaska's source-reported
  House counts (159,550; 152,828; 3,417; 13,010; 750), totaling 329,555.
  PDF page 31 has Maine district 1 candidate counts (154,849; 249,798; 20,883),
  totaling 425,530, and Maine district 2 candidate counts (194,445; 197,151),
  totaling 391,596, with 11,340 exhausted ballots separately. Pages 17–19 and 58
  identify FL-20 and OK-03 as races with no recorded vote count. These are selected
  independent checks, **not a certified all-district comparison**.

## Stored semantics

`election_result_observation` stores the original row, original ordinal, checksum,
normalized candidate/party labels and nullable counts. County fields remain null.
`house_return_detail` adds the district, stage, special/runoff/write-in/unofficial/
fusion indicators and missing-data/category flags. Both are inserted atomically
with the source's active-year pointer using the shared loader.

The known FL-20 and OK-03 `(candidatevotes=1, totalvotes=-1)` sentinels become
**null observed counts**, with `UNOPPOSED_VOTE_PLACEHOLDER` and `MISSING_VOTES`
flags; their exact source strings remain in `raw_json`. A real one-vote result
elsewhere remains one vote. Other negative or malformed counts fail ingestion.
There is no vote imputation. Their contests, candidacies and ballot lines are
modeled, but no zero or one-vote canonical returns are created for them.

Named write-ins receive source-scoped candidacies and write-in ballot lines.
Unidentified write-in buckets remain separate `write_in` returns. Unnamed aggregate
source categories remain aggregate returns. Blank, void, over/under-vote and
exhausted-ballot categories are retained as observations with `NON_VOTE_CATEGORY`
materialization issues and excluded from canonical vote totals.

`house_district_reconciliation` stores each batch/district's repeated source total,
source category sum, canonical sum, row ordinals, flags and exact reconciliation
basis. Some repeated totals include administrative categories (DC); others omit
them (NY). The complete source sum or the vote-category sum must equal the one
reported total. Missing/conflicting totals, duplicate logical rows, unverified
fusion, unsupported modes, unofficial results, unresolved names or unmatched
districts withhold the entire district's vote categories. No stranded candidate
is published after another candidate in the same district fails validation.

The publication is immutable apart from its active pointer. Its fingerprint pins
source release/hash, reference release/hash, normalized source inputs and the
ruleset. Existing geography decisions are checked on reruns. A differing decision
requires the established geography review workflow. Identical reruns reuse the
batch; old batches and source releases remain queryable.

## Verified snapshot (November 16, 2026)

| Measure | Verified value |
| --- | ---: |
| Original file rows | 33,805 |
| Selected immutable observations | 1,353 |
| Modeled contests | 436 |
| Source-scoped candidacies / ballot lines | 1,133 / 1,168 |
| Reconciled contests | 434 |
| Missing-vote contests | 2 |
| Published returns | 1,282 |
| Excluded non-vote categories / missing placeholders | 69 / 2 |
| API items after fusion aggregation | 1,247 |
| Published source-native vote-category sum | 148,310,611 |

This is a **PARTIAL source-native publication**, including DC and unidentified
vote buckets. Its sum is not a national two-party vote metric, turnout, or a
uniform ranked-choice round. Alaska and Maine receive
`SOURCE_REPORTED_RCV_COUNTS` flags: preserve MEDSL's reported counts without
inferring transfer rounds or winners. The APIs expose publication-level partial
coverage; detailed source flags and reconciliation reasons are in the tables
and publication report. The two missing-vote contests appear in discovery but
have no result rows or result-backed publication entry.

Implementation: `ingestion/adapters/medsl_house.py`, `ingestion/house_returns.py`,
`ingestion/adapters/census_congressional_districts.py`,
`app/services/house_returns.py`, `app/models/house_returns.py` and the additive
`house_return_evidence` Alembic revision. Existing migrations are unchanged.

Local evidence is under ignored `artifacts/house-returns/`: the full-source
verification report, test XML, source hashes and local publication/API checks.
See the [runbook](house_returns_2024_runbook.md) for repeatable commands.

Local deployment is at Alembic head `house_return_evidence`, with publication
batch `ec21fc45-c177-411a-8248-ae2bb2bc22ca`. The full Python 3.12/PostgreSQL suite
passed **291 tests, zero failures/skips**, with unchanged implementation hashes
during the run. The full pinned-source test used an isolated migrated schema;
the live API then passed an independent all-page check of 1,247 items and 1,282
distinct observation links. Observation replay inserted zero rows and reused
all 1,353 observations; publication replay was `UNCHANGED`. Alembic `check`
reported no schema drift. All five prior presidential publication pointers and
totals, the FEC state pointer and the 94,151 presidential observation count
were preserved.

The selected Clerk checks above were executed against the pinned MEDSL file.
The original official PDF is archived with SHA-256
`d4ba800fc17135b616ae556c92861080ab962d95916ace34b546c5aac824aec4`;
the results and page locators are in
`data/house-returns/independent-reference-checks.json`.

Remaining scope: certified all-district comparison, historical/special/runoff
House ingestion, canonical person matching, district polygons and ranked-choice
round modeling. None is silently inferred from this import.
