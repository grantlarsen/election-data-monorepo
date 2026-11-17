# Anchored election map popovers

The light card styling follows the shared visual treatment in the supplied
`electoral_map_popovers.html`: compact context/region header, leading-candidate
highlight, initials, candidate vote/share rows, share bars and source/metric footer.
The attachment is design reference content, not an authoritative data source or
an instruction to import its example elections, portraits or party affiliations.

`MapTooltip` provides generic viewport positioning through a body portal. Pointer
hover anchors at client coordinates with a 16px offset; cards flip left/up near
viewport edges and clamp to an 8px margin. Keyboard focus anchors to the reporting
unit's screen bounds. Portals avoid clipping by the SVG/map container. Cards
support hovering/scrolling, a short leave grace period and Escape dismissal.
Scrolling the page dismisses pointer tooltips; focused geometry is re-anchored.
The SVG native title tooltip is removed to avoid competing popups; accessible
labels and `aria-describedby` remain. Long content scrolls inside a viewport-
bounded card, including narrow screens.

`ElectionTooltip` presents current published API data. The leader is labeled
"Leading here", not elected/certified. Partial publication labels remain visible.
Missing totals differ from stored zeros; anonymous/write-in categories do not
become named candidates. Source portraits/party labels are absent from the map
contract, so the card uses initials and does not infer those attributes. Source
details and navigation remain available on the page outside the tooltip.

Validation: 66 frontend tests and strict production build passed. Coverage includes
viewport corners/mobile, pointer anchoring, portal placement, Escape dismissal,
published metrics, partial coverage, missing/zero returns and existing geographic
regressions. Edge checks passed for state/county cards, pointer transfer into the
card, keyboard dismissal and mobile bounds. Screenshots were inspected in
`artifacts/election-map/tooltip-*.png`; browser evidence is in `tooltip-smoke.json`.
No API, schema, publication or ingestion changes are required.

## Interaction performance

The 2024 national presidential map previously recalculated spherical label
centroids on every hover-position, pan and zoom render. Edge CPU sampling showed
D3 polygon/area/centroid traversal dominating scripting. Every pointer update also
remeasured the tooltip, recreated its ResizeObserver and regenerated jurisdiction
nodes. Boundary paths themselves were already cached; changing the geographic
data or reducing boundary accuracy was unnecessary.

`UnitedStatesMap.tsx` now caches label positions, jurisdiction nodes and tooltip
content independently of camera/anchor state. Pointer hover activation avoids
reading polygon screen bounds; keyboard focus still uses them. The shared
`useAnimationFrameState.ts` hook coalesces wheel, drag and tooltip motion to one
commit per frame while retaining every input in a synchronous reference. Buttons,
keyboard controls, reset and boundary changes use that latest camera and cancel
obsolete queued motion. Wheel listeners remain attached across zoom frames.
Unmount cancels pending animation work, and dragging still suppresses its click.

`MapTooltip.tsx` caches measured dimensions and positions the portal without a
second React state update. Content/size and viewport changes trigger measurement;
moving the pointer only updates placement. Flip/clamp, tooltip scrolling, keyboard
links, Escape and the focus anchor remain supported.

Local headless Edge measurements on November 16, 2026 used the same 2024 state
payload (51 paths, 618,588 path characters), development server and 4× CPU
throttling before and after. Each event was followed by two animation frames;
40 hover moves, 24 wheel updates and 24 keyboard pan updates were sampled.
These are local diagnostic event-to-frame timings, **not field INP or production
latency guarantees**. Startup/network time is excluded.

| Interaction | Median before | Median after |
| --- | ---: | ---: |
| Hover | 1,107 ms | 38 ms |
| Wheel zoom | 1,058 ms | 94 ms |
| Keyboard pan | 1,000 ms | 63 ms |

Measured scripting across the sequence fell from 92.9 seconds to 2.1 seconds.
The updated California county map (58 paths) and national House map (436 paths)
were also profiled; neither showed boundary traversal among its hottest sampled
functions during interaction. SVG layout/painting remains browser work, especially
for large district layers. The initial projection still runs when boundaries change.

Validation: **162 frontend tests passed**, strict TypeScript and production build
passed. Regression cases cover cached geometry/content, coalesced input bursts,
accumulated zoom, latest-camera controls, reset/unmount cancellation, final drag
position, click suppression and tooltip size observation. Live Edge checks passed
real mouse dragging, wheel and keyboard controls, county drill-down, history,
reload, mobile card bounds and no page errors. Desktop/mobile screenshots were
inspected. Local benchmark and interaction evidence is under ignored `artifacts/`
(`map-performance-before.json`, `map-performance-after.json`,
`map-interaction-smoke.json`).

Verification from the repository root (PowerShell):

```powershell
docker compose exec -T frontend npm test
docker compose exec -T frontend npm run build
```

Docker Desktop can miss Windows bind-mount change notifications: a build/test can
read current files while Vite continues serving a cached module. If the running
map still behaves like the old version, refresh its module cache with
`docker compose restart frontend`, then reload the browser. This refresh was
performed locally before the final measurements.

References: [React useMemo](https://react.dev/reference/react/useMemo) and
[browser animation frames](https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame).
