import { useEffect, useState } from "react";
import type { ElectionMap } from "./types";
import { ApiError } from "../api";

const count = (value: unknown) =>
  Number.isSafeInteger(value) && Number(value) >= 0;
const optionalPercent = (value: number | null) =>
  value === null || (Number.isFinite(value) && value >= 0 && value <= 100);

export async function fetchElectionMap(
  query: string,
  signal: AbortSignal,
): Promise<ElectionMap> {
  const response = await fetch(`/api/v1/election-map?${query}`, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new ApiError(
      response.status,
      "Map data is temporarily unavailable. Please try again.",
    );
  const data = (await response.json()) as ElectionMap;
  if (
    !data ||
    !Array.isArray(data.units) ||
    !Array.isArray(data.publications) ||
    data.features?.type !== "FeatureCollection" ||
    !Array.isArray(data.features.features) ||
    !data.coverage ||
    ![
      "boundary_units",
      "units_with_results",
      "missing_results",
      "results_without_geometry",
    ].every((key) =>
      count(data.coverage[key as keyof ElectionMap["coverage"]]),
    ) ||
    !["state", "county", "congressional_district"].includes(
      data.reporting_level,
    ) ||
    ![
      "available",
      "no_matching_published_results",
      "unsupported_selection",
      "boundaries_unavailable",
    ].includes(data.availability) ||
    data.units.some(
      (unit) =>
        !unit ||
        !unit.id ||
        typeof unit.name !== "string" ||
        typeof unit.state_code !== "string" ||
        !unit.summary ||
        ![
          "available",
          "tie",
          "zero_total",
          "indeterminate",
          "no_results",
        ].includes(unit.summary.status) ||
        !(
          unit.summary.total_votes === null || count(unit.summary.total_votes)
        ) ||
        !(
          unit.summary.margin_votes === null || count(unit.summary.margin_votes)
        ) ||
        !optionalPercent(unit.summary.margin_pp) ||
        !Array.isArray(unit.summary.candidates) ||
        unit.summary.candidates.some(
          (c) =>
            !c ||
            typeof c.label !== "string" ||
            !count(c.votes) ||
            !optionalPercent(c.share),
        ),
    )
  ) {
    throw new ApiError(
      502,
      "The map response could not be read. Please try again.",
    );
  }
  return data;
}

export function useElectionMap(query: string, enabled: boolean) {
  const [attempt, setAttempt] = useState(0);
  const key = `${query}&attempt=${attempt}`;
  const [state, setState] = useState<{
    key: string;
    data?: ElectionMap;
    error?: string;
  }>({ key: "" });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let current = true;
    fetchElectionMap(query, controller.signal)
      .then((data) => {
        if (current) setState({ key, data });
      })
      .catch((error) => {
        if (current)
          setState({
            key,
            error:
              error instanceof ApiError
                ? error.message
                : "The map response could not be read. Please try again.",
          });
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [key, query, enabled]);
  return {
    ...(state.key === key ? state : {}),
    retry: () => setAttempt((value) => value + 1),
  };
}
