# Site navigation and presidential history

The logo opens `/`, a landing placeholder. The President, Senate, House,
Governor, States, Financing and Search controls expand one disclosure at a time.
Links use ordinary keyboard navigation; Escape returns focus to the section
button. Outside clicks and route changes dismiss the disclosure. Existing map,
contest and candidate tools remain under Search. Every header destination starts
with its own page context; election, office and geography selections never carry
across header sections. Header labels have no caret icons.

The site has no global filter panel, filter toggle or applied-filter strip.
Navigation follows election pages, local year/view links, state/county drill-down
and breadcrumbs. URL parameters remain supported within a page and its record
links for direct loading, pagination, refresh and browser history.

`navigation.ts` defines destinations; unbuilt pages have explicit “Coming soon”
placeholders. The requested page follow-ups are UI-012–UI-030 in
`Election_Data_Project_Backlog.csv`, including the landing page, primary and
future election pages, office histories, financing pages and global search.
The existing 2024 presidential page is reused. “Add backlog item to create page”
was treated as an instruction for the PAC/Super PAC page, not a navigation label.

`/presidential/history` discovers all presidential election events through every
page of `/api/v1/elections`. Events sharing an election date and stage are grouped
into one card, avoiding one duplicate card per state. The seven current general
elections (2000–2024) link to existing year pages. Other discovered dates/stages
link to the existing map selection and show a neutral preview-pending state if
no image has been generated. Errors, retry and an empty database are explicit.
Senate/House/Governor/States histories remain separate backlog pages.

Cards use checked-in, lazy-loaded **PNG files**, with no interactive map or result
rendering inside the grid. They are snapshots of published statewide results,
not current coverage guarantees. `presidential-previews.json` records the source
publication/boundary metadata and generation timestamps. Regenerate after relevant
publications or boundaries change. With optional Playwright Python tooling and
Edge installed, from the repository root:

```powershell
python frontend/scripts/generate-election-previews.py
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
```

The development Compose service mounts `frontend/public` so generated files are
served without rebuilding the image. Fresh builds include them normally. Apply
the updated mount to an existing local stack with
`docker compose up -d --no-deps frontend`.

Validation: 185 frontend tests and strict production build passed. Live Edge
checks verified all seven PNGs decode, no map API/SVG rendering occurs in the
archive, all menu sections fit at 320/375/768/1440px, Escape focus return,
placeholder reload, and logo navigation. Desktop/mobile screenshots were inspected;
local evidence is under ignored `artifacts/header-*`.
