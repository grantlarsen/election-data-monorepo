/** Geographic rendering only: no election years, candidates or result arithmetic. */
import { geoAlbersUsa, geoArea, geoPath } from "d3-geo";
import type {
  Feature,
  FeatureCollection,
  MultiPolygon,
  Polygon,
  Position,
} from "geojson";

export interface JurisdictionProperties {
  geoid: string;
  name: string;
  state_code: string;
  jurisdiction_id?: string | null;
  reporting_level?: string;
}
export type JurisdictionFeature = Feature<
  Polygon | MultiPolygon,
  JurisdictionProperties
>;
export type JurisdictionCollection = FeatureCollection<
  Polygon | MultiPolygon,
  JurisdictionProperties
>;
export type Extent = [[number, number], [number, number]];
export const MAP_WIDTH = 960;
export const MAP_HEIGHT = 600;

/** D3 uses clockwise spherical shells, opposite RFC 7946. Keep source data intact. */
export function projectionFeature<P>(
  feature: Feature<Polygon | MultiPolygon, P>,
): Feature<Polygon | MultiPolygon, P> {
  function polygon(coordinates: Position[][]): Position[][] {
    return geoArea({ type: "Polygon", coordinates }) > 2 * Math.PI
      ? coordinates.map((ring) => [...ring].reverse())
      : coordinates;
  }
  return {
    ...feature,
    geometry:
      feature.geometry.type === "Polygon"
        ? {
            type: "Polygon",
            coordinates: polygon(feature.geometry.coordinates),
          }
        : {
            type: "MultiPolygon",
            coordinates: feature.geometry.coordinates.map(polygon),
          },
  };
}

export function unitedStatesPath(collection: JurisdictionCollection) {
  const features = collection.features.map(projectionFeature);
  const projection = geoAlbersUsa().fitExtent(
    [
      [24, 24],
      [MAP_WIDTH - 24, MAP_HEIGHT - 24],
    ],
    { type: "FeatureCollection", features },
  );
  return geoPath(projection);
}

export function projectUnitedStates(collection: JurisdictionCollection) {
  const features = collection.features.map(projectionFeature);
  const path = unitedStatesPath(collection);
  return features.map((feature) => ({
    feature,
    path: path(feature),
    bounds: path.bounds(feature) as Extent,
  }));
}

export function extentViewBox(
  extent: Extent,
  padding = 12,
): string | undefined {
  const [[x0, y0], [x1, y1]] = extent;
  if (![x0, y0, x1, y1].every(Number.isFinite) || x1 <= x0 || y1 <= y0)
    return undefined;
  return `${x0 - padding} ${y0 - padding} ${x1 - x0 + padding * 2} ${y1 - y0 + padding * 2}`;
}

/** Exact keys only; ambiguous rows and cross-state/canonical-ID conflicts are errors. */
export function matchJurisdictions<
  T extends {
    id: string;
    geoid: string | null;
    state_code: string;
    jurisdiction_id: string | null;
  },
>(features: JurisdictionCollection, rows: readonly T[]): Map<string, T> {
  const byGeoid = new Map<string, T>();
  for (const row of rows) {
    if (row.geoid === null) continue;
    if (byGeoid.has(row.geoid))
      throw new Error("Multiple data units have the same GEOID.");
    byGeoid.set(row.geoid, row);
  }
  const matched = new Map<string, T>();
  const seen = new Set<string>();
  for (const feature of features.features) {
    const key = feature.properties.geoid;
    if (seen.has(key) || String(feature.id) !== key)
      throw new Error("Boundary identifiers are inconsistent.");
    seen.add(key);
    const row = byGeoid.get(key);
    if (!row) continue;
    if (
      row.id !== key ||
      row.state_code !== feature.properties.state_code ||
      ("jurisdiction_id" in feature.properties &&
        row.jurisdiction_id !== feature.properties.jurisdiction_id)
    ) {
      throw new Error(
        "Boundary and data jurisdiction identifiers do not agree.",
      );
    }
    matched.set(key, row);
  }
  return matched;
}
