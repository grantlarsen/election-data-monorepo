# DATA-004 delivery — 2026-11-14

Recommended status: **Complete for the geographic architecture definition of done**.
Remaining DATA-004 engineering: **0 hours**; allow **1 hour of reviewer handoff**.
Actual county/district boundary imports and independent review/publication of source decisions remain separate work below. No real congressional district history or geometry was imported or certified by this patch.

## Audit and acceptance matrix

Audited repository HEAD: `fe1373d780f8b1c07f217c79c14d31ae4e0c4653` plus the existing untracked backlog CSV. No AGENTS.md was found. Inspected models, all six existing migrations, reference adapters/loaders, resolver and publication services, canonical materialization, tests, backlog, and live PostgreSQL before schema changes. Initial Alembic head was `d003f93a1700`.

| Acceptance | Before: verified live/code evidence | Implemented and executed verification |
| --- | --- | --- |
| Identity distinct from source identifiers and boundary versions | 3,258 jurisdiction UUIDs; 19,155 released references/identifiers. Existing county allocator conservatively separates changed code/name identities; reviewed continuity links exist but none are populated. | Reuse those UUIDs; add a separate boundary table. Composite FKs reject identifier, containment, boundary and decision records that point to the wrong reference identity. County/CD identity tests pass. No identity merges. |
| Multiple non-overlapping boundary vintages | No boundary version table; product-year ranges are statistical coverage, not verified legal dates. | `jurisdiction_boundary_vintage`, required cited applicability start, optional exclusive end, unique version label, global GiST exclusion per jurisdiction. Adjacent intervals, unbounded ends, invalid intervals, cross-release overlaps and concurrent inserts tested on PostgreSQL. |
| County-equivalent and House district support | County equivalents are represented as `kind='county'`. Allowed reference kinds were state/county/place; no CD imports. | Add `congressional_district`, widen kind to 32 characters, preserve separate identifier namespaces. Four-digit Census CD validation and state containment supported. Both county and CD boundary fixtures pass; no actual CD dataset is claimed. |
| Historical relationships and dates | 18,849 released containment rows without dates; all 19,155 identifiers have unknown dates. Dated change evidence and reviewed continuity link models already exist. | Add nullable containment dates with citation requirements and interval checks; preserve existing unknowns. Test dated parent changes, reference identity, identifier uniqueness, and exact date endpoints. Existing change/link workflow remains authoritative for recodes/successors. |
| Provenance and reproducible resolution | Seven source releases; 94,151 legacy `step6-v1` roots. Current resolver pinned the primary release but selected supplemental references and approved evidence from current state. | Freeze primary/supplemental reference evidence, source checksums, approved alias/change snapshots, source release/year scope and observation-input digest in immutable, shared contexts. Replay survives newer references and active-source changes. Corrupt/changed inputs and contradictory supplemental evidence fail explicitly. |
| Explicit exceptional statuses | Live: 1,077 unresolved, 209 ambiguous, four invalid. Revised Step 6.2 code was present but live roots remained v1. | Retain all roots. Enforce known statuses, target/null semantics, chain scope, single roots/successors, append-only decisions/contexts. Exact dated lookup reports unresolved, ambiguous, invalid, pending or out-of-vintage explicitly. Five read-only comparisons archived. |
| DATA-003 compatibility and migration safety | Five published 2000–2016 batches; 49,745 canonical returns. | Full migration-chain tests; populated downgrade/re-upgrade preservation; guarded refusal to discard new history; 29 live table fingerprints unchanged; all five canonical preview fingerprints/counts/vote sums reproduce. Alembic check reports no drift. |

Before this work, available tests and Step 6.2 code were **inspection evidence**, not proof of execution. The final full suite was executed against PostgreSQL and passed **106 tests, zero failures/errors/skips**, including **13 new DATA-004 cases**. The first full attempt found two stale manually defined SQLite fixture schemas (100 passed, two failed); those fixtures were updated with the new nullable fields. PostgreSQL is the basis for all new architecture and migration acceptance tests.

Runtime observed: Python 3.12.16, PostgreSQL 18.6, PostGIS 3.7.0, SQLAlchemy 2.1.8, Alembic 1.20.1, psycopg 3.3.9, Polars 1.44.2, pytest 9.2.0. See `data/data004/pytest.xml` and `validation.json` for execution evidence.

## Architecture decisions and patch scope

1. **Keep identity allocation explicit.** A jurisdiction UUID is not a FIPS code, source reporting unit or boundary. Existing UUIDs, released labels, and observation links are preserved. Existing deterministic allocation remains compatible; it is not proof of legal continuity across changed/recycled identifiers. New district intake must explicitly assign/review identities. Existing `geographic_identity_link` represents reviewed continuity/succession without merging old UUIDs.
2. **Separate three clocks.** `geographic_reference.vintage_start/end` describes inclusive product-year coverage. Identifier/containment validity uses nullable legal/evidenced dates. Boundary applicability uses a required start and `[valid_from, valid_until)` dates. A null end means open-ended; a null legacy start means unknown, not proof of indefinite validity. No product coverage range is converted into dates. Date-bearing new identifiers/relationships require a citation.
3. **One boundary applicability timeline per jurisdiction.** The GiST exclusion prevents overlaps across all releases, including simultaneous writers; `btree_gist` is the only extension prerequisite. DATA-007 can attach multiple geometry representations to a version UUID without duplicating applicability periods. This patch adds no geometry column, import, topology validation or rendering.
4. **Keep release evidence attached to its identity.** Composite reference/identity FKs close previously unenforced consistency gaps. A resolution's primary `reference_release_id` is its selection/run scope; historical or supplemental `reference_id` may belong to another release. That is deliberate, documented evidence, not a crosswalk. A composite FK tying those two release fields together would incorrectly forbid historical evidence.
5. **Make new MEDSL decisions reproducible.** A SHA-256 keyed context stores complete reference/evidence input snapshots once per changed publication. Primary and supplemental releases, source checksums, source release/year selection, raw observation hashes and used normalized inputs are bound to the digest. Previews are REPEATABLE READ / READ ONLY and archive their manifest without inserting database rows. Changed publication approval binds to the context digest as well as the decision diff. A saved preview can be replayed via `--context-file`; a persisted context via `--context-sha256`. A different ruleset requires its recorded code version.
6. **Preserve old decisions honestly.** Existing roots retain null context digests. They are not retroactively described as having archived original contexts, and this work does not certify reproduction of their original v1 decision process. New snapshots/replay are verified; legacy decision adjudication belongs to GEO-001/002. Unchanged decisions do not get cosmetic supersession records merely to add provenance fields.
7. **Reject unsupported or ambiguous identity choices.** Exact dated identifier lookup requires a release, kind, scheme, value and date; unknown starts stay pending. Competing evidence stays ambiguous. The MEDSL pipeline retains classification before county matching, independent state validation, reviewed aliases and retired-code handling. Contradictory tied supplemental references now raise an error instead of depending on database row order.
8. **Protect history at the database.** Decisions and input contexts reject UPDATE/DELETE. Supersession must remain within the same observation/reference-release chain. Migrations are additive and transactional. Empty DATA-004 additions can be downgraded; downgrade refuses to discard new boundary, district, dated-evidence or context history. The shared extension remains installed. Do not use the older Step 6.1 destructive downgrade path.

Implementation reuses `geography.py`, existing source releases, immutable observations, resolver, publish gate and canonical services. The new `app.services.geography.resolve_identifier` resolves dated reference identifiers; it does not allocate identities, infer boundaries or ingest data. Existing `geo validate` understands the new district namespace. All DataFrame operations use Polars.

## Preservation evidence

`before.json` was captured before the migration. `after.json` compares every original column using a sorted multiset content hash plus row counts; added nullable columns are inventoried separately. **All 29 original table comparisons are true.** This includes identity/provenance tables as well as every canonical table.

| Preserved table/group | Rows |
| --- | ---: |
| Election observations | 94,151 |
| Geographic decisions | 94,151 |
| References / identifiers | 19,155 each |
| Jurisdictions | 3,258 |
| Released containment relationships | 18,849 |
| Source releases / active source-year pointers | 7 each |
| Canonical batches / publication pointers | 5 each |
| Canonical returns / materialization issues | 49,745 / 779 |

No legacy identity/reference mismatches were found before adding constraints. New boundary/context tables are **empty in the project database**, as expected: tests use isolated `_test` database schemas and comparisons are read-only. All existing identifiers still have unknown legal dates. Actual data population is not implied by schema support.

| Published year | Accepted rows | Excluded rows | Stored eligible vote sum, unchanged |
| --- | ---: | ---: | ---: |
| 2000 | 12,428 | 200 | 104,163,480 |
| 2004 | 9,330 | 144 | 121,536,863 |
| 2008 | 9,330 | 144 | 130,546,351 |
| 2012 | 9,330 | 144 | 128,446,248 |
| 2016 | 9,327 | 147 | 135,881,227 |

These are the existing partial canonical subsets, not asserted national totals. All five recomputed fingerprints, accepted/excluded counts and eligible sums match their published batches. No supersession/publication was performed.

## Exception investigation

The exported inventory includes every original exception's observation UUID, source row/hash, year, state, raw reporting label/code, selected release, status, method and reason. `exception_triage.csv` adds the preview outcome, proposed action, citation/research requirement and backlog owner. `exception_groups.csv` provides year/state/unit/reason groupings. `preview_review.csv` includes new issues discovered among previously matched rows.

| Year | Original unresolved | Ambiguous | Invalid | Total |
| --- | ---: | ---: | ---: | ---: |
| 2000 | 176 | 24 | 0 | 200 |
| 2004 | 126 | 18 | 0 | 144 |
| 2008 | 126 | 18 | 0 | 144 |
| 2012 | 126 | 18 | 0 | 144 |
| 2016 | 129 | 18 | 0 | 147 |
| 2020 | 199 | 53 | 0 | 252 |
| 2024 | 195 | 60 | 4 | 259 |
| Total | 1,077 | 209 | 4 | 1,290 |

By state: AK 1,025; CT 55; VA 64; MO 29; MN 21; NM 21; RI 20; ME 16; LA 16; IL 8; SD 7; DC 4; FL 4.

| Original exception group | Rows | Evidence-supported disposition / remaining work |
| --- | ---: | --- |
| Alaska districts 1–40 | 1,000 | Classify in the election-source namespace; [Alaska's official 2008 results](https://www.elections.alaska.gov/results/08GENR/data/results.htm) and [district statement](https://www.elections.alaska.gov/Core/Archive/08GENR/data/sovc/hd8.pdf) establish district reporting. No borough allocation or canonical historical district boundary is established. GEO-001 still reviews each year/plan. |
| Alaska District 99 | 25 | Pending; obtain year-specific official meaning and coverage. A citation about another year's District 99 is insufficient. |
| CT statewide write-in, ME UOCAVA, RI federal precinct, MO Kansas City place code | 73 | Source-scoped non-county classification. Votes cannot be allocated to counties or assumed mutually exclusive/comprehensive without source reconciliation. |
| Virginia Charles City / James City | 64 | Existing Step 6.2 name fix preserves CITY within county names. Codes 51036/51095 and typed county names are in the [Census county code file](https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt). Review/publication remains GEO-001/002. |
| 2000 DC / Miami-Dade | 8 | Exact county evidence in already ingested independent Census 2000 Gazetteer supplements absent CBP entries. Preserve separate releases. |
| 2024 Connecticut legacy counties | 39 | Historical reporting-area matches, not planning-region conversions. The [Census notice](https://www.federalregister.gov/documents/2022/06/06/2022-12063/change-to-county-equivalents-in-the-state-of-connecticut) distinguishes eight legacy counties from nine planning regions. Verify source reporting scope; never allocate through an assumed one-to-one crosswalk. |
| MN SAINT LOUIS, LA LA SALLE, IL DEWITT/JODAVIESS, MO DE KALB | 49 | Reviewed alias candidates: 21/16/8/4 rows respectively. Exact state/code gives a candidate; spacing/abbreviations do not authorize linking. Census code evidence plus contemporaneous source/reference review is required. LaSalle's documented name correction is in the [Census change record](https://www.census.gov/programs-surveys/geography/technical-documentation/county-changes.2010.html). Existing aliases remain proposals. |
| NM DONA ANA | 21 | Reference-quality research: persisted 2017–2021 label contains a replacement character; 2022–2024 label is `Do a Ana`. The Census code file identifies 35013 as Doña Ana County. Inspect archived source bytes/decoder and review continuity between existing UUIDs. Do not repair released labels in place or approve an alias merely to hide encoding damage. |
| SD 2016 new code / 2024 retired code | 3 / 4 | [Census documents](https://www.census.gov/programs-surveys/geography/technical-documentation/county-changes.2010.html) the 2015 Shannon/Oglala Lakota recode. The three 2016 observations need verified event evidence and correct reference selection; four 2024 retired-code observations need source-convention research. No automatic 46113→46102 remap. |
| 2024 Missouri Kansas City raw code 36000 | 4 | Invalid state prefix; source research/correction decision required. Never substitute a place code from the label alone. |

The **2008 set of 144** consists of 123 AK district observations, 12 CT/ME/MO/RI special-unit observations, three MN alias cases and six VA county-label cases. Preview: 132 non-county classifications, three District 99 pending, three MN ambiguous, six county matches. All 144 remain excluded from the existing canonical batch; DATA-005 must reconcile compatible county/state candidate totals and publish only a reviewed superseding batch if warranted.

## Published statistics versus preview

| Status | Persisted, unchanged | Read-only Step 6.2 preview |
| --- | ---: | ---: |
| RESOLVED | 92,632 | 92,696 |
| RESOLVED_HISTORICAL | 229 | 273 |
| NON_COUNTY_CLASSIFIED | 0 | 1,073 |
| PENDING_REVIEW | 0 | 32 |
| AMBIGUOUS | 209 | 70 |
| UNRESOLVED | 1,077 | 3 |
| INVALID | 4 | 4 |
| Total | 94,151 | 94,151 |

Of the original 1,290 exceptions, previews produce **1,073 classifications, 111 county matches and 106 remaining review cases**. The full preview requires **109 reviews** because it additionally flags **three 2016 Bedford city 51515 rows** previously marked RESOLVED_HISTORICAL. Census documents retirement of that independent city effective July 1, 2013. All three are present in the existing 2016 canonical batch with **zero votes each**; see `downgrade_canonical_impact` in `reconciliation.json`. No change to them was published.

Five comparisons cover 12,628 / 18,948 / 18,948 / 22,093 / 21,534 observations for vintages 2000 / 2004 / 2012 / 2020 / 2024. There are **1,837 semantic decision differences**, **three proposed matched-status downgrades**, **zero canonical jurisdiction reassignments**, and preserved state/year raw vote bookkeeping sums. Differences also include typed independent-city methods and historical flags, not just original exceptions. The saved proposal/context digests are review inputs, not approval.

Important downstream limit: current DATA-003 canonical eligibility requires the matched reference to belong to its selected primary release and cover the election year. Therefore the 47 proposed cross-release historical/supplemental matches do **not** automatically become eligible canonical returns. GEO-002 must coordinate a separately tested DATA-003 follow-up for such lineage before any canonical supersession. Non-county classification likewise does not establish county-total eligibility.

## Remaining ownership and estimates

| Owner | Work still required | Remaining estimate |
| --- | --- | ---: |
| DATA-004 | Implementation, PostgreSQL verification and delivery complete; optional reviewer handoff | 0 engineering hours; 1 review hour |
| GEO-001 | Independently review archived five-vintage comparisons, 1,837 differences, 109 review cases and classification semantics for all seven years. Diagnose NM reference encoding and Bedford retired identifiers. | 12 hours retained; low confidence |
| GEO-002 | Approve only supported aliases/change/continuity evidence and exact proposal/context digests; review all downgrades. Publish append-only decisions, then prove idempotence and vote invariants. No approval supplied by this delivery. | 10 hours retained; low confidence |
| DATA-005 | Reconcile all 144 2008 exclusions with official sources at compatible reporting levels, explain coverage and handle reviewed supersession. | 8 hours retained |
| DATA-007 | Source/import 2008 county and 119th House geometry; explicitly assign district identities, establish evidenced applicability dates/history/containment, attach geometry to version UUIDs and validate PostGIS coverage/topology. | 26 hours retained; re-estimate after source inventory |
| DATA-003 follow-up, coordinated by GEO-002 | Design/verify canonical eligibility for approved cross-release historical evidence; preserve old batches/pointers until explicit supersession. | 4–8 additional hours, provisional |
| DATA-027 / DATA-028 | Existing 2020/2024 mode and source-quality work; include invalid MO codes without automatic correction. | Existing 24 / 16 hours retained |

These downstream estimates are planning judgments, not measured completion claims. `DATA004-backlog.csv` is the proposed task update; the user's existing untracked `Election_Data_Project_Backlog.csv` is left untouched. GEO-001 independent signoff, GEO-002 approval, geometry population, source corrections and actual district-history imports have not been completed by this architecture patch.

## Delivery artifacts

- `DATA004-RUNBOOK.md`: exact executed-style PowerShell/Docker commands, replay and guarded rollback.
- `data/data004/before.json`, `after.json`: schema, provenance inventory, row fingerprints and canonical replay.
- `data/data004/compare-*.json`, `reconciliation.json`: full frozen inputs, proposal digests, semantic differences and canonical impact.
- `data/data004/exception_triage.csv`, `exception_groups.csv`, `preview_review.csv`: exception-level assignments and evidence requirements.
- `data/data004/pytest.xml`: final 106-case executed test report. `pytest.txt` records the earlier two-fixture failure, not the final result.
- `data/data004/validation.json`, `SHA256SUMS.txt`: machine-readable verification and artifact integrity.
- `artifacts/data004/DATA-004-patch.zip`: changed source/tests/migration/docs only, with manifest and checksums.
- `artifacts/data004/DATA-004-evidence.zip`: generated audit/comparison/test artifacts, separate from the minimal patch.
