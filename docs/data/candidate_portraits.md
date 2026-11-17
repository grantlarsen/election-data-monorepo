# Reviewed candidate portraits

The 2026 House roster has 529 reviewed, locally cached portraits across 428
districts and all 50 states: 355 congressional portraits and 174 Wikimedia
Commons portraits. These cover 411 source-called winners. The remaining 833
named source entries retain the existing fallback; ambiguous identities and
unverified reuse terms never receive a guessed image. Anonymous vote categories
are outside the portrait catalog.

The 2026 Senate roster has 66 locally cached portraits across all 35 races,
including 59 Democratic/Republican candidate entries. Research checked 128 named
source entries with at least 100 votes. The remaining source labels retain their
initials or party dots; a name shared with a famous person is not image evidence.
The catalog records unassigned labels and the reason no photo was assigned.

Sources are [public-domain congressional photos](https://github.com/unitedstates/images)
and individual Wikimedia Commons files with reviewed reuse terms. The congressional
legislator and image repositories are pinned by commit. Commons records retain the
file upload timestamp, source description, author, license and original/download
URLs. Original Senate API responses are archived under
`data/candidate-portraits/research/`; House responses, election-page revisions,
roster evidence and download reviews are under
`data/candidate-portraits/house-research/`.
Each downloaded raster has a SHA-256, retrieval timestamp and checksum-named asset
under `frontend/public/media/candidates/`. House assets total approximately
29.8 MB, alongside approximately 3.1 MB of Senate assets; no
new image service or package is required. Some official portraits are historical;
the image is not evidence of a current office or current appearance.

`backend/ingestion/catalog/senate_portraits.json` and
`backend/ingestion/catalog/house_portraits.json` are the reviewed media crosswalks.
Assignments require the exact source, election year, race, source name and party.
Political biographies, Bioguide IDs and file descriptions supply match evidence.
No portrait is attached to an anonymous bucket or selected by name in the browser.
In particular, the Alaska candidates Dan Sullivan and Daniel J. Sullivan Jr. remain
distinct; only the reviewed incumbent receives the congressional portrait.

House congressional assignments reuse reviewed Bioguide evidence, including
explicitly linked historical members. The House image-repository commit is
`aec3e4a88af843b282c0576f420b930f6a9a46ad`. Commons assignments match the candidate,
party and district in the election-page infobox or its linked political
biography; explicit ballot-name aliases are retained. Five Iowa legislative
portraits additionally retain the
[Iowa General Assembly permission](https://commons.wikimedia.org/wiki/Template:Iowa_General_Assembly_official_portrait_permission)
and VRT ticket `2010030210041811`. That permission was reviewed for those files;
an arbitrary copyright claim is insufficient. Each file retains its own reuse
terms and attribution rather than assuming all Commons files have one license.

This is a source-candidacy presentation annotation. It does not assign a canonical
person, FEC ID, campaign committee, incumbency or financial data. It reuses the
existing source-scoped Senate and House read models without a database migration.
`candidate_media.py` loads the validated catalog once per API process and enriches
each matching candidate with optional `portrait` metadata. Candidate profiles
receive the same data in `provisional_election` or `provisional_house_election`.
Restart the API after changing the catalog.

`CandidateAvatar` displays the image on the profile and replaces available table
dots and map-popover initials with thumbnails. The browser matches the profile's
explicit candidacy UUID to its source result row. Candidate links, badges and vote
metrics remain unchanged. Other/write-in aggregates never inherit a person's
portrait. Missing, unsafe or broken images retain the existing fallback. Images
are served locally, lazy-loaded, asynchronously decoded and bounded by the avatar
size. Profile credits link to the source and license; thumbnail titles include
the photographer/credit and license, with attribution available through the
adjacent candidate-profile link.

## Replay and validation

From the repository root in PowerShell:

```powershell
# Verify the checked-in assets without any network requests.
python backend/ingestion/candidate_portraits.py --verify-only

# Download missing or corrupt files from the reviewed, pinned catalog.
# Bytes that do not match the approved checksum are rejected.
python backend/ingestion/candidate_portraits.py

# Optionally verify just the House catalog.
python backend/ingestion/candidate_portraits.py --catalog backend/ingestion/catalog/house_portraits.json --verify-only

# Refresh the running catalog/module cache after edits.
docker compose restart api frontend

docker compose exec -T frontend npm test -- --maxWorkers=4
docker compose exec -T frontend npm run build
```

Both commands process both chamber catalogs by default. The replay command
records each catalog checksum, plus inserted, updated, unchanged, excluded and rejected
asset counts plus per-file status in a uniquely identified JSON run report under
`data/candidate-portraits/reports/`. It is restartable and idempotent for pinned
inputs. Verification never downloads; a missing/corrupt file fails explicitly.
Downloads use the source's supplied raster thumbnails, preserve the approved
bytes and atomically replace a cache file only after size/signature/checksum
validation. Failed bytes never replace an existing file. Reviewed assignments
sharing the same asset reuse that cache file.

To add an image, review its candidate identity and reuse terms, archive the source
metadata, record the scoped assignment and downloaded checksum, then verify the
catalog and assets before restarting the API. Ambiguous matches and insufficient
reuse information remain unassigned. The ordinary daily vote refresh does not
search for, overwrite or reassign portraits.

House validation on November 17, 2026: all 274 frontend tests and the strict
TypeScript/production build passed. Relevant Python 3.12 source/API checks passed
91 tests (one optional retained-input test skipped); PostgreSQL and portrait
checks passed 16 tests. Offline verification and repeat replay each reported
595 unchanged assets and zero rejections. Every House assignment matched its
exact live source candidate, party and district; all 529 served files matched
their approved SHA-256. Six source-scoped API profiles retained their portrait
and attribution without resolving a person or financial identity. Desktop/mobile
profile and results checks at 1440px and 375px passed without overflow or page
errors. All 174 Commons images and 30 sampled congressional images decoded in
review sheets. Evidence is under ignored `artifacts/house-current/headshots-*`.

Earlier Senate validation on November 17, 2026: 238 frontend tests, 67 backend/API/PostgreSQL
tests in Python 3.12, strict TypeScript and production build passed. Offline
verification and a repeat cache run each reported 66 unchanged files and zero
rejections. Browser checks decoded and checksum-verified all 66 served portraits
and checked all 66 source-candidacy API profiles; person identities and financial
totals remained unresolved. Desktop/mobile profile, table and popover checks
passed at 1440px and 375px without overflow or page errors. The contact sheet was
inspected and three wide photos replaced with closer crops already published by
their source. Evidence is under ignored `artifacts/senate-results/portrait-*`.
