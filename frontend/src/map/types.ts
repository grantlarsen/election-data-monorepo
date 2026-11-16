import type { JurisdictionCollection } from "../geography/unitedStates";
import type { Publication } from "../api";

export interface MapCandidate {
  party_labels?: string[];
  label: string;
  kind: string;
  votes: number;
  share: number | null;
  candidacy_id: string | null;
  geographic_reference_id: string | null;
  reference_vintage_start?: number | null;
  reference_vintage_end?: number | null;
  observation_ids: string[];
  correction_ids: string[];
}
export interface Summary {
  status: "available" | "tie" | "zero_total" | "indeterminate" | "no_results";
  total_votes: number | null;
  leader: string | null;
  margin_votes: number | null;
  margin_pp: number | null;
  candidates: MapCandidate[];
}
export interface MapUnit {
  id: string;
  geoid: string | null;
  name: string;
  state_code: string;
  jurisdiction_id: string | null;
  contest_id: string | null;
  publication_batch_id: string | null;
  has_geometry: boolean;
  summary: Summary;
  geometry_match?:
    | "matched"
    | "boundary_only"
    | "missing_reference"
    | "missing_geometry";
}

/** A leader label resolves only within its own result group, with no guessed IDs. */
export function leaderCandidate(summary: Summary): MapCandidate | undefined {
  const matches = summary.candidates.filter(candidate => candidate.label === summary.leader);
  return matches.length === 1 ? matches[0] : undefined;
}
export interface ElectionMap {
  year: number;
  office: string;
  stage: string;
  reporting_level: "state" | "county" | "congressional_district";
  drill_down_level: "county" | null;
  state_code: string | null;
  selected_jurisdiction_id: string | null;
  availability:
    | "available"
    | "no_matching_published_results"
    | "unsupported_selection"
    | "boundaries_unavailable";
  boundary: null | {
    version: string;
    boundary_vintage: string;
    vintage_note: string;
    documentation_url: string;
    display_sha256: string;
    repaired_features: number;
    sources: {
      level: string;
      url: string;
      sha256: string;
      retrieved_at: string;
    }[];
  };
  features: JurisdictionCollection;
  units: MapUnit[];
  publications: Publication[];
  coverage: {
    boundary_units: number;
    units_with_results: number;
    missing_results: number;
    results_without_geometry: number;
  };
  metric_note: string;
  source_note: string;
}

export const number = (value: number) => value.toLocaleString("en-US");
export const percent = (value: number | null) =>
  value === null ? "Unavailable" : `${value.toFixed(2)}%`;
export const margin = (summary: Summary) =>
  summary.margin_pp === null
    ? "Unavailable"
    : `${summary.margin_pp.toFixed(2)}%`;
