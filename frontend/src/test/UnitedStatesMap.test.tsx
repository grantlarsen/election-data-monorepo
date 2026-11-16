import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { geoArea, geoContains } from "d3-geo";
import greatLakes from "../geography/data/great-lakes.json";
import type { FeatureCollection, Polygon, MultiPolygon } from "geojson";
import { UnitedStatesMap } from "../geography/UnitedStatesMap";
import {
  MAP_HEIGHT,
  MAP_WIDTH,
  matchJurisdictions,
  projectionFeature,
  projectUnitedStates,
} from "../geography/unitedStates";
import type {
  JurisdictionCollection,
  JurisdictionFeature,
} from "../geography/unitedStates";
import { candidateColor, resultColor } from "../map/electionColors";

function rectangle(
  geoid: string,
  state: string,
  west: number,
  south: number,
  east: number,
  north: number,
): JurisdictionFeature {
  return {
    type: "Feature",
    id: geoid,
    properties: {
      geoid,
      state_code: state,
      name: state,
      jurisdiction_id: `canonical-${geoid}`,
    },
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [west, south],
          [east, south],
          [east, north],
          [west, north],
          [west, south],
        ],
      ],
    },
  };
}
const features: JurisdictionCollection = {
  type: "FeatureCollection",
  features: [
    rectangle("06", "CA", -123, 34, -117, 40),
    rectangle("02", "AK", -160, 59, -145, 68),
    rectangle("15", "HI", -158, 19, -155, 22),
  ],
};
function rows() {
  return features.features.map((feature) => ({
    id: feature.properties.geoid,
    geoid: feature.properties.geoid,
    state_code: feature.properties.state_code,
    jurisdiction_id: feature.properties.jurisdiction_id!,
    value: feature.properties.state_code,
  }));
}

describe("generic United States mapping", () => {
  it("masks Great Lakes water while retaining both Michigan peninsulas and Wisconsin/Minnesota land", () => {
    const water = greatLakes as FeatureCollection<
      Polygon | MultiPolygon,
      { name: string }
    >;
    const contains = (point: [number, number]) =>
      water.features.some((lake) =>
        geoContains(projectionFeature(lake), point),
      );
    expect(contains([-86.5, 44])).toBe(true); // Lake Michigan, inside legal state waters.
    expect(contains([-90, 47.5])).toBe(true); // Lake Superior.
    for (const land of [
      [-84.5, 43.5],
      [-87, 46.4],
      [-89.4, 43.07],
      [-94.2, 46.35],
    ] as [number, number][])
      expect(contains(land)).toBe(false);
    const onSelect = vi.fn();
    render(
      <UnitedStatesMap
        features={features}
        data={matchJurisdictions(features, rows())}
        title="Water regression"
        fill={() => "#123456"}
        describe={() => "Land"}
        tooltip={() => "Land"}
        onSelect={onSelect}
        attribution="Physical water provenance"
        water={water}
      />,
    );
    const lake = screen.getByRole("img", { name: "Lake Michigan" });
    expect(lake).toHaveAttribute("pointer-events", "all");
    fireEvent.click(lake);
    expect(onSelect).not.toHaveBeenCalled();
    expect(lake.closest("svg")?.lastElementChild).toHaveClass("map-water");
  });
  it("uses Albers USA to place Alaska and Hawaii below the mainland with finite paths", () => {
    const projected = projectUnitedStates(features);
    expect(projected).toHaveLength(3);
    for (const item of projected) {
      expect(item.path).toMatch(/^M/);
      expect(item.path).not.toMatch(/NaN|Infinity/);
      const [[left, top], [right, bottom]] = item.bounds;
      expect(left).toBeGreaterThanOrEqual(23);
      expect(right).toBeLessThanOrEqual(MAP_WIDTH - 23);
      expect(top).toBeGreaterThanOrEqual(23);
      expect(bottom).toBeLessThanOrEqual(MAP_HEIGHT - 23);
    }
    expect(projected[1].bounds[0][1]).toBeGreaterThan(
      projected[0].bounds[0][1],
    );
    expect(projected[2].bounds[0][1]).toBeGreaterThan(
      projected[0].bounds[0][1],
    );
  });

  it("normalizes RFC polygon winding for D3 without modifying the boundary source", () => {
    const before = JSON.stringify(features);
    expect(geoArea(features.features[0])).toBeGreaterThan(2 * Math.PI);
    expect(geoArea(projectionFeature(features.features[0]))).toBeLessThan(
      2 * Math.PI,
    );
    expect(JSON.stringify(features)).toBe(before);
  });

  it("matches reordered data by exact GEOID and canonical identity, never position or name", () => {
    const data = rows().reverse();
    expect(matchJurisdictions(features, data).get("06")?.value).toBe("CA");
    expect(matchJurisdictions(features, data.slice(1)).has("15")).toBe(false);
    expect(() => matchJurisdictions(features, [...data, data[0]])).toThrow(
      /same GEOID/,
    );
    expect(() =>
      matchJurisdictions(features, [{ ...data[0], state_code: "CA" }]),
    ).toThrow(/do not agree/);
    expect(() =>
      matchJurisdictions(features, [
        { ...data[0], jurisdiction_id: "wrong-canonical-id" },
      ]),
    ).toThrow(/do not agree/);
    const unverified = {
      ...features,
      features: [
        {
          ...features.features[2],
          properties: {
            ...features.features[2].properties,
            jurisdiction_id: null,
          },
        },
      ],
    };
    expect(() => matchJurisdictions(unverified, [data[0]])).toThrow(
      /do not agree/,
    );
  });

  it("allows keyboard and pointer selection using caller-supplied data and tooltips", async () => {
    const onSelect = vi.fn();
    const data = matchJurisdictions(features, rows());
    render(
      <UnitedStatesMap
        features={features}
        data={data}
        title="Generic geographic data"
        fill={(row) => (row?.value === "CA" ? "#123456" : "#abcdef")}
        describe={(row) => `Select ${row?.value}`}
        tooltip={(row) => `Data: ${row?.value}`}
        onSelect={onSelect}
        attribution="Source archive"
      />,
    );
    const california = screen.getByRole("button", { name: "Select CA" });
    expect(california).toHaveAttribute("fill", "#123456");
    fireEvent.focus(california);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Data: CA");
    fireEvent.keyDown(california, { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith(
      data.get("06"),
      expect.objectContaining({ id: "06" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Select AK" }));
    expect(onSelect).toHaveBeenLastCalledWith(
      data.get("02"),
      expect.objectContaining({ id: "02" }),
    );
  });

  it("anchors a hover tooltip near the pointer, portals it outside the map, and dismisses it with Escape", () => {
    render(
      <UnitedStatesMap
        features={features}
        data={matchJurisdictions(features, rows())}
        title="Anchor regression"
        fill={() => "#123456"}
        describe={(row) => `Select ${row?.value}`}
        tooltip={(row) => `Data: ${row?.value}`}
        onSelect={vi.fn()}
        attribution="Source"
      />,
    );
    const california = screen.getByRole("button", { name: "Select CA" });
    fireEvent.mouseEnter(california, { clientX: 220, clientY: 180 });
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.parentElement).toBe(document.body);
    expect(tooltip).toHaveStyle({ left: "236px", top: "196px" });
    fireEvent.mouseMove(california, { clientX: 240, clientY: 200 });
    expect(tooltip).toHaveStyle({ left: "256px", top: "216px" });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.mouseMove(california, { clientX: 245, clientY: 205 });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("assigns stable colors to arbitrary candidate labels without inferring parties", () => {
    expect(candidateColor("Example federal candidate")).toMatch(
      /^#[0-9a-f]{6}$/,
    );
    expect(candidateColor("Example federal candidate")).toBe(
      candidateColor("EXAMPLE FEDERAL CANDIDATE"),
    );
    expect(resultColor()).not.toBe(candidateColor("Example federal candidate"));
  });
});
