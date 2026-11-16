import { useMemo } from "react";
import { UnitedStatesMap } from "../geography/UnitedStatesMap";
import { matchJurisdictions } from "../geography/unitedStates";
import type { ElectionMap, MapUnit } from "./types";
import { ElectionTooltip } from "./ElectionTooltip";
import { resultColor } from "./electionColors";
import greatLakes from "../geography/data/great-lakes.json";
import type { FeatureCollection, Polygon, MultiPolygon } from "geojson";

const water = greatLakes as FeatureCollection<
  Polygon | MultiPolygon,
  { name: string }
>;

/** Election adapter: the underlying UnitedStatesMap has no election-specific behavior. */
export function GeographyMap({
  data,
  onSelect,
  selectedId,
}: {
  data: ElectionMap;
  onSelect: (unit: MapUnit) => void;
  selectedId?: string;
}) {
  const match = useMemo(() => {
    try {
      return { units: matchJurisdictions(data.features, data.units) };
    } catch {
      return {
        error:
          "Boundary and result jurisdictions could not be matched safely. Use the table to inspect the published records.",
      };
    }
  }, [data.features, data.units]);
  if (!match.units)
    return (
      <p role="alert" className="notice notice-error">
        {match.error}
      </p>
    );
  return (
    <UnitedStatesMap
      features={data.features}
      data={match.units}
      water={water}
      title={
        data.state_code
          ? `${data.state_code} · ${data.reporting_level.replaceAll("_", " ")} map`
          : "United States election map"
      }
      selectedId={selectedId}
      fill={(unit) => resultColor(unit?.summary)}
      describe={(unit, feature) =>
        `${unit?.name || feature.properties.name}: ${unit?.summary.leader || (unit?.summary.status === "tie" ? "Tie" : "No determined leader")}`
      }
      tooltip={(unit, feature) => (
        <ElectionTooltip
          data={data}
          unit={unit}
          name={feature.properties.name}
        />
      )}
      onSelect={(unit) => {
        if (unit) onSelect(unit);
      }}
      attribution={
        <>
          {data.boundary
            ? `U.S. Census Bureau · ${data.boundary.version}`
            : "Boundary provenance available in source details"}{" "}
          ·{" "}
          <a href={greatLakes.source.documentation}>
            Water: Natural Earth {greatLakes.source.version}
          </a>
        </>
      }
    />
  );
}
