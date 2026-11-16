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
