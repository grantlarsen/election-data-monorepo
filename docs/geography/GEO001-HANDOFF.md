# GEO-001 handoff: GEO-002 and DATA-005

GEO-001 is complete for independent audit/reconciliation. **No publication is approved.** Review `data/geo001/review-ledger.csv`, grouped rationales in `review-groups.csv`, and `geo002-review-package.json`. The ledger has one row per observation, a current unpublished proposal key, existing decision/reference/jurisdiction IDs, source provenance, canonical impact links, applicable evidence dates and an owner for each hold.

## GEO-002

Use the **step6.2.1** targets under `data/geo001/corrected/reproduced/`. Exact release/context/proposal SHA-256 triples are in `geo002-review-package.json`; independent recomputation is in `independent-digest-checks.json`. The step6.2.0 digests were reproduced exactly but cannot authorize the corrected ruleset. A digest is an input to review, not an approval.

Among the original 1,837 differences: 1,755 supported; 61 require research; 21 original Kansas City place-coverage typings unsupported and corrected to source reporting units. Current 1,955-row ledger: 1,776 supported outcomes for their stated limited purpose, 163 research holds and 16 unsupported NM historical inferences. Classification-only support does not establish complete or additive county vote coverage.

Review supported county/name and typed independent-city proposals, source-scoped classifications, supplemental lineage, and each Bedford downgrade individually. Retain pending/ambiguous/invalid states for held cases. Research holds include early AK District 99 and the 2020 five-vote gap, CT 2024 legacy territorial coverage, aliases, SD source conventions, MO 36000, reference damage/identity continuity, and Jackson coverage. Keep all original released reference rows and UUIDs intact.

The three Bedford 2016 observations are:

| Observation | Existing decision | Candidate | Votes |
| --- | --- | --- | ---: |
| `3b4e0162-ed80-4096-a217-5d4e6f43a433` | `8bf749a2-e8f1-4819-9f2c-a05447e26714` | HILLARY CLINTON | 0 |
| `6b39af8a-ba48-4d28-886e-1eb41dabbe89` | `40c76f17-b42f-4a48-8fbf-a92e63305c76` | OTHER | 0 |
| `d9b6efec-d929-430b-8d29-f9123b03b712` | `e679b542-da71-4ad4-93f1-eadb54a64159` | DONALD TRUMP | 0 |

All three remain in published batch `4b122026-b9c1-4b0e-9529-3ee3f8eb753c`. Support a pending downgrade for retirement effective 2013-07-01; source padding/convention remains unproven. Require separate explicit downgrade authorization and canonical review. No successor remap or reassignment is authorized.

After evidence/actor review, regenerate exact contexts and previews for any changed rules, evidence or scope. Follow the existing append-only publication gate, including separate downgrade authorization and idempotence verification. Full vintage digests must not be treated as blanket approval for held cases. Current DATA-003 rejects the 47 cross-release historical/supplemental matches; any eligibility change requires separately tested work and a separate canonical publication workflow. Geometry remains DATA-007.

## DATA-005

`data/geo001/data005-144-handoff.csv` contains **exactly 144 distinct original 2008 exclusions**. Batch `f44e7295-900f-47ec-9947-97d4c7c74ded` remains PARTIAL with 9,330 accepted rows, 144 exclusions and 130,546,351 eligible votes. Its fingerprint remains `b0ff6b9c8c552810c16e1ea9e249a9e8c043a4db57c3db12477a91f1cbeaeee5`.

| Partition | Rows | Preview outcome / county eligibility |
| --- | ---: | --- |
| AK districts | 123 | 120 districts 1–40 classified non-county; three District 99 rows remain pending. No county allocation or new county eligibility. |
| CT/ME/MO/RI special units | 12 | Three per source category; classification alone supplies no county eligibility. CT/ME/RI rows are zero-valued in 2008; Kansas City rows sum to 153,219. |
| MN SAINT LOUIS aliases | 3 | County candidate only; not eligible until a reviewed source/year-specific alias and geographic decision are published, followed by all canonical checks. |
| VA county labels | 6 | Exact 51036 Charles City / 51095 James City primary-reference county proposals. Establish geographic county eligibility only after GEO-002 publication; no canonical batch is changed here. |
| Total | 144 | 132 classifications, six county-match proposals, six pending/ambiguous cases. |

Validate candidate totals at compatible reporting levels, then review any canonical supersession separately. Include the three already accepted 2008 Jackson observations in coverage review: official Missouri authority returns separate Jackson and Kansas City. Kansas City must not be allocated or added to a supposed full Jackson county without checking the source segments. Preserve all source votes and lineage.

The precise question for each non-county unit is whether it is a separate omitted component, an included subtotal, a zero placeholder, or an overlapping category in that election's source. The current ledger deliberately does not answer that question from the label alone. Official RI 2008 town/state totals include limited precincts; Maine's archived 2008 table and CT's scanned statement do not establish the MEDSL special-row conventions. Those are explicit DATA-005 research tasks, alongside independent state/candidate totals and the existing eight-hour estimate.
