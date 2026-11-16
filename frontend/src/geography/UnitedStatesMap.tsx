import { useEffect, useId, useMemo, useRef, useState } from "react";
import { MapTooltip } from "./MapTooltip";
import type { TooltipPoint } from "./MapTooltip";
import type { ReactNode } from "react";
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
  attribution: ReactNode;
  water?: FeatureCollection<Polygon | MultiPolygon, { name: string }>;
}) {
  const [activeId, setActiveId] = useState<string>();
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
    hideTimer.current = setTimeout(() => setActiveId(undefined), 160);
  }
  function activate(id: string, target: SVGPathElement, point?: TooltipPoint) {
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
      if (event.key === "Escape") dismiss();
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
    (selected?.path && extentViewBox(selected.bounds)) ||
    `${(MAP_WIDTH * (1 - 1 / zoom)) / 2} ${(MAP_HEIGHT * (1 - 1 / zoom)) / 2} ${MAP_WIDTH / zoom} ${MAP_HEIGHT / zoom}`;
  return (
    <section className="us-map" aria-label={title}>
      <div className="us-map-heading">
        <div className="map-controls" aria-label="Map controls">
          <button
            aria-label="Zoom in"
            disabled={zoom >= 4 || !!selectedId}
            onClick={() => setZoom((value) => Math.min(4, value * 1.5))}
          >
            +
          </button>
          <button
            aria-label="Zoom out"
            disabled={zoom <= 1 || !!selectedId}
            onClick={() => setZoom((value) => Math.max(1, value / 1.5))}
          >
            −
          </button>
          <button onClick={() => setZoom(1)} disabled={zoom === 1}>
            Reset zoom
          </button>
        </div>
      </div>
      <svg
        className="us-map-svg"
        viewBox={viewBox}
        role="group"
        aria-label={title}
      >
        {visible.map(({ feature, path }) => {
          const id = feature.properties.geoid;
          const datum = data.get(id);
          const label = describe(datum, feature);
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
              role="button"
              tabIndex={0}
              aria-label={label}
              aria-pressed={selectedId === id}
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
              onBlur={dismiss}
              onClick={() => onSelect(datum, feature)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
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
