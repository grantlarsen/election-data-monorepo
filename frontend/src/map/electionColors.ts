import type { Summary, MapCandidate } from "./types";

export const partyPalette = { Democratic: "#3276ac", Republican: "#bd5548", "Other / independent": "#358369", "Multiple major parties": "#8c6bb1" };
export function partyGroup(labels: string[] = []): keyof typeof partyPalette {
  const democratic = labels.some(label => ["DEMOCRATIC", "DEMOCRAT", "DEMOCRATIC-FARMER-LABOR"].includes(label));
  const republican = labels.includes("REPUBLICAN");
  return democratic && republican ? "Multiple major parties" : democratic ? "Democratic" : republican ? "Republican" : "Other / independent";
}
export function mapCandidateColor(candidate: MapCandidate, byParty: boolean): string {
  return byParty ? partyPalette[partyGroup(candidate.party_labels)] : candidateColor(candidate.label);
}

// Stable source-label colors across elections and drill-down scopes; no inferred parties.
const palette = [
  "#bd5548",
  "#3276ac",
  "#8c6bb1",
  "#358369",
  "#bf7625",
  "#8a654d",
  "#687687",
  "#bb5d8f",
  "#507c38",
  "#4a8f98",
  "#8c7931",
];
export const missingColor = "#d9ded9";
export const indeterminateColor = "#7d8584";
export const tieColor = "#8e759b";
export function candidateColor(label: string): string {
  let hash = 0;
  for (const character of label.normalize("NFKC").trim().toUpperCase())
    hash = (Math.imul(hash, 31) + character.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length];
}
export function resultColor(summary?: Summary, byParty = false): string {
  if (!summary || summary.status === "no_results") return missingColor;
  if (summary.status === "tie") return tieColor;
  const leader = summary.candidates.find(candidate => candidate.label === summary.leader);
  return leader ? mapCandidateColor(leader, byParty) : indeterminateColor;
}
