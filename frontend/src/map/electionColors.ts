import type { Summary } from "./types";

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
export function resultColor(summary?: Summary): string {
  if (!summary || summary.status === "no_results") return missingColor;
  if (summary.status === "tie") return tieColor;
  return summary.leader ? candidateColor(summary.leader) : indeterminateColor;
}
