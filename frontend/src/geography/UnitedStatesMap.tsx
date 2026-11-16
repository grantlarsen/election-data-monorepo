import { useEffect, useId, useMemo, useRef, useState } from "react";
import { MapTooltip } from "./MapTooltip";
import './map-interactions.css';
import type { TooltipPoint } from "./MapTooltip";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import type { FeatureCollection, Polygon, MultiPolygon } from "geojson";
import type {
  JurisdictionCollection,
  JurisdictionFeature,
} from "./unitedStates";
import {
  extentViewBox,
  MAP_HEIGHT,
  MAP_WIDTH,
  projectUnitedStates,
  projectionFeature,
  unitedStatesPath,
} from "./unitedStates";

/** Reusable US choropleth. Callers supply matched data, colors and interactions. */
export function UnitedStatesMap<T>({
  features,
  data,
  title,
  fill,
  describe,
  tooltip,
  onSelect,
  selectedId,
  focusSelection = true,
  isInteractive = () => true,
  attribution,
  water,
}: {
  features: JurisdictionCollection;
  data: ReadonlyMap<string, T>;
  title: string;
  fill: (datum: T | undefined) => string;
  describe: (datum: T | undefined, feature: JurisdictionFeature) => string;
  tooltip: (datum: T | undefined, feature: JurisdictionFeature) => ReactNode;
  onSelect: (datum: T | undefined, feature: JurisdictionFeature) => void;
  selectedId?: string;
  focusSelection?: boolean;
  isInteractive?: (datum: T | undefined, feature: JurisdictionFeature) => boolean;
  attribution: ReactNode;
  water?: FeatureCollection<Polygon | MultiPolygon, { name: string }>;
}) {
  const [activeId, setActiveId] = useState<string>();
  const drag = useRef<{ pointer: number; x: number; y: number; centerX: number; centerY: number; scale: number; moved: boolean; element: SVGSVGElement } | undefined>(undefined);
  const suppressClick = useRef(false);
  const [dragging, setDragging] = useState(false);
  const [anchor, setAnchor] = useState<TooltipPoint>({ x: 0, y: 0 });
  const anchorTarget = useRef<SVGPathElement | null>(null);
  const pointerAnchor = useRef(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  function cancelHide() {
    clearTimeout(hideTimer.current);
  }
  function dismiss() {
    cancelHide();
    setActiveId(undefined);
  }
  function scheduleHide() {
    cancelHide();
    hideTimer.current = setTimeout(() => {
      if (!document.getElementById(tooltipId)?.contains(document.activeElement)) setActiveId(undefined);
    }, 160);
  }
  function activate(id: string, target: SVGPathElement, point?: TooltipPoint) {
    if (drag.current?.moved) return;
    cancelHide();
    anchorTarget.current = target;
    pointerAnchor.current = !!point;
    const rect = target.getBoundingClientRect();
    setAnchor(point || { x: rect.right, y: rect.top + rect.height / 2 });
    setActiveId(id);
  }
  useEffect(() => () => clearTimeout(hideTimer.current), []);
  useEffect(() => {
    if (!activeId) return;
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (document.getElementById(tooltipId)?.contains(document.activeElement)) anchorTarget.current?.focus();
        dismiss();
      }
    };
    const reposition = (event: Event) => {
      if (
        event.target instanceof Element &&
        event.target.closest('[role="tooltip"]')
      )
        return;
      if (pointerAnchor.current) {
        dismiss();
        return;
      }
      const rect = anchorTarget.current?.getBoundingClientRect();
      if (rect) setAnchor({ x: rect.right, y: rect.top + rect.height / 2 });
    };
    window.addEventListener("keydown", key);
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [activeId]);
  const [zoom, setZoom] = useState(1);
  const svgRef = useRef<SVGSVGElement>(null);
  const [center, setCenter] = useState({ x: MAP_WIDTH / 2, y: MAP_HEIGHT / 2 });
  const focusKey = focusSelection ? selectedId : undefined;
  function endDrag() {
    const current = drag.current;
    drag.current = undefined;
    if (current?.element.hasPointerCapture?.(current.pointer)) current.element.releasePointerCapture(current.pointer);
    setDragging(false);
  }
  useEffect(() => {
    endDrag();
    setZoom(1);
    setCenter({ x: MAP_WIDTH / 2, y: MAP_HEIGHT / 2 });
  }, [features, focusKey]);
  const pannable = zoom > 1 && !focusKey;
  function moveCenter(x: number, y: number) {
    const halfWidth = MAP_WIDTH / zoom / 2;
    const halfHeight = MAP_HEIGHT / zoom / 2;
    setCenter({ x: Math.max(halfWidth, Math.min(MAP_WIDTH - halfWidth, x)),
      y: Math.max(halfHeight, Math.min(MAP_HEIGHT - halfHeight, y)) });
  }
  function changeZoom(value: number, pointerOffset?: { x: number; y: number }) {
    endDrag();
    dismiss();
    const next = Math.max(1, Math.min(4, value));
    const halfWidth = MAP_WIDTH / next / 2;
    const halfHeight = MAP_HEIGHT / next / 2;
    setZoom(next);
    const anchorShift = 1 - zoom / next;
    setCenter(previous => ({ x: Math.max(halfWidth, Math.min(MAP_WIDTH - halfWidth, previous.x + (pointerOffset?.x || 0) * anchorShift)),
      y: Math.max(halfHeight, Math.min(MAP_HEIGHT - halfHeight, previous.y + (pointerOffset?.y || 0) * anchorShift)) }));
  }
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const wheel = (event: WheelEvent) => {
      if (focusKey || event.ctrlKey || event.metaKey || event.altKey || !Number.isFinite(event.deltaY) || event.deltaY === 0) return;
      const bounds = svg.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      // React wheel handlers may be passive. This listener must cancel page
      // scrolling while the pointer is over the map, including at zoom limits.
      event.preventDefault();
      const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.height : 1);
      const next = Math.max(1, Math.min(4, zoom * Math.exp(-Math.max(-240, Math.min(240, pixels)) * .002)));
      if (next === zoom) return;
      // SVG uses a centered, aspect-preserving viewport; account for letterboxing.
      const scale = Math.max(MAP_WIDTH / zoom / bounds.width, MAP_HEIGHT / zoom / bounds.height);
      changeZoom(next, { x: (event.clientX - bounds.left - bounds.width / 2) * scale,
        y: (event.clientY - bounds.top - bounds.height / 2) * scale });
    };
    svg.addEventListener('wheel', wheel, { passive: false });
    return () => svg.removeEventListener('wheel', wheel);
  }, [zoom, focusKey]);
  function startDrag(event: ReactPointerEvent<SVGSVGElement>) {
    suppressClick.current = false;
    if (!pannable || event.button !== 0 || event.isPrimary === false || drag.current) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    drag.current = { pointer: event.pointerId, x: event.clientX, y: event.clientY,
      centerX: center.x, centerY: center.y,
      scale: Math.max(MAP_WIDTH / zoom / bounds.width, MAP_HEIGHT / zoom / bounds.height),
      moved: false, element: event.currentTarget };
  }
  function pan(event: ReactPointerEvent<SVGSVGElement>) {
    const current = drag.current;
    if (!current || current.pointer !== event.pointerId) return;
    const dx = event.clientX - current.x;
    const dy = event.clientY - current.y;
    if (!current.moved && Math.hypot(dx, dy) < 5) return;
    if (!current.moved) {
      current.moved = true;
      suppressClick.current = true;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      setDragging(true);
      dismiss();
    }
    event.preventDefault();
    moveCenter(current.centerX - dx * current.scale, current.centerY - dy * current.scale);
  }
  const tooltipId = useId();
  const projected = useMemo(() => projectUnitedStates(features), [features]);
  const waterPaths = useMemo(() => {
    if (!water) return [];
    const path = unitedStatesPath(features);
    return water.features.map((feature) => ({
      name: feature.properties.name,
      path: path(projectionFeature(feature)),
    }));
  }, [features, water]);
  const active = projected.find(
    (item) => item.feature.properties.geoid === activeId,
  );
  const selected = projected.find(
    (item) => item.feature.properties.geoid === selectedId,
  );
  const visible = projected.filter((item) => item.path);
  const clipped = projected.length - visible.length;
  const showInsets =
    new Set(features.features.map((feature) => feature.properties.state_code))
      .size > 1;
  const viewBox =
    (focusSelection && selected?.path && extentViewBox(selected.bounds)) ||
    `${center.x - MAP_WIDTH / zoom / 2} ${center.y - MAP_HEIGHT / zoom / 2} ${MAP_WIDTH / zoom} ${MAP_HEIGHT / zoom}`;
  return (
    <section className="us-map" aria-label={title}>
      <div className="us-map-heading">
        <div className="map-controls" aria-label="Map controls">
          <button
            aria-label="Zoom in"
            disabled={zoom >= 4 || (!!selectedId && focusSelection)}
            onClick={() => changeZoom(zoom * 1.5)}
          >
            +
          </button>
          <button
            aria-label="Zoom out"
            disabled={zoom <= 1 || (!!selectedId && focusSelection)}
            onClick={() => changeZoom(zoom / 1.5)}
          >
            −
          </button>
          <button onClick={() => changeZoom(1)} disabled={zoom === 1}>
            Reset zoom
          </button>
        </div>
      </div>
      <svg
        ref={svgRef}
        className={`us-map-svg${pannable ? ' is-pannable' : ''}${dragging ? ' is-panning' : ''}`}
        viewBox={viewBox}
        role="group"
        aria-label={title}
        aria-description="Scroll to zoom toward the pointer. When zoomed, drag to pan or use the arrow keys. Reset zoom restores the full map."
        tabIndex={0}
        onPointerDown={startDrag}
        onPointerMove={pan}
        onPointerUp={event => { if (drag.current?.pointer === event.pointerId) endDrag(); }}
        onPointerCancel={endDrag}
        onLostPointerCapture={endDrag}
        onPointerLeave={() => { if (drag.current && !drag.current.moved) endDrag(); }}
        onClickCapture={event => { if (suppressClick.current) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false; } }}
        onKeyDown={event => {
          if (!pannable || event.altKey || event.ctrlKey || event.metaKey) return;
          const directions: Record<string, number[]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
          const delta = directions[event.key];
          if (!delta) return;
          event.preventDefault();
          dismiss();
          moveCenter(center.x + delta[0] * MAP_WIDTH / zoom * .1, center.y + delta[1] * MAP_HEIGHT / zoom * .1);
        }}
      >
        {visible.map(({ feature, path }) => {
          const id = feature.properties.geoid;
          const datum = data.get(id);
          const label = describe(datum, feature);
          const interactive = isInteractive(datum, feature);
          return (
            <path
              key={id}
              d={path!}
              data-geoid={id}
              data-jurisdiction-id={
                feature.properties.jurisdiction_id || undefined
              }
              fill={fill(datum)}
              stroke="#fff"
              strokeWidth={0.85}
              vectorEffect="non-scaling-stroke"
              role={interactive ? "button" : "img"}
              tabIndex={interactive ? 0 : undefined}
              aria-label={label}
              aria-pressed={interactive ? selectedId === id : undefined}
              aria-describedby={activeId === id ? tooltipId : undefined}
              onMouseEnter={(event) =>
                activate(id, event.currentTarget, {
                  x: event.clientX,
                  y: event.clientY,
                })
              }
              onMouseMove={(event) => {
                if (activeId === id)
                  setAnchor({ x: event.clientX, y: event.clientY });
              }}
              onMouseLeave={scheduleHide}
              onFocus={(event) => activate(id, event.currentTarget)}
              onBlur={event => {
                if (!document.getElementById(tooltipId)?.contains(event.relatedTarget as Node | null)) dismiss();
              }}
              onClick={() => { if (interactive) onSelect(datum, feature); }}
              onKeyDown={(event) => {
                if (event.key === "Tab" && !event.shiftKey && activeId === id) {
                  const link = document.getElementById(tooltipId)?.querySelector<HTMLAnchorElement>('a[href]');
                  if (link) {
                    event.preventDefault();
                    link.focus();
                  }
                }
                if (interactive && (event.key === "Enter" || event.key === " ")) {
                  event.preventDefault();
                  onSelect(datum, feature);
                }
              }}
            ></path>
          );
        })}
        {/* Physical water is drawn above legal jurisdiction fills and intercepts
            pointer events so lake surfaces cannot select the underlying state. */}
        <g className="map-water" aria-label="Physical water features">
          {waterPaths.map(
            (item) =>
              item.path && (
                <path
                  key={item.name}
                  d={item.path}
                  fill="#edf1ed"
                  stroke="none"
                  role="img"
                  aria-label={item.name}
                  pointerEvents="all"
                  onMouseEnter={dismiss}
                />
              ),
          )}
        </g>
      </svg>
      {active && (
        <MapTooltip
          id={tooltipId}
          anchor={anchor}
          onEnter={cancelHide}
          onLeave={scheduleHide}
        >
          {tooltip(data.get(active.feature.properties.geoid), active.feature)}
        </MapTooltip>
      )}
      <footer className="us-map-attribution">
        <span>{attribution}</span>
        <details className="us-map-projection">
          <summary>Projection & display notes</summary>
          <p>
            Albers USA ·{" "}
            {showInsets
              ? "Alaska and Hawaii are inset; Alaska is shown at a smaller scale. "
              : "State view fitted to its published boundaries. "}
            Outlying islands may be clipped; reporting units remain in the table.
            {water &&
              " Physical shoreline layer; not a historical shoreline survey."}
          </p>
        </details>
      </footer>
      {clipped > 0 && (
        <p role="status">
          {clipped} boundary units fall outside this projection and remain
          available in the table.
        </p>
      )}
    </section>
  );
}
