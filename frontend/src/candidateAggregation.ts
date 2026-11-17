import { partyGroup } from './map/electionColors';

/** Presentation grouping shared by source-specific tables and map popovers. */
export function aggregateMinorCandidates<T extends { votes: number; kind?: string }>(
  candidates: T[], totalVotes: number | null,
  display: {
    name: (candidate: T) => string;
    parties: (candidate: T) => string[] | undefined;
    other: (members: T[], votes: number, share: number) => T;
  },
): T[] {
  if (!totalVotes) return candidates;
  const cutoff = Math.min(1000, totalVotes / 1000);
  const grouped = new Set(candidates.filter(candidate =>
    ['candidate', 'source_candidate'].includes(candidate.kind || 'source_candidate') &&
    partyGroup(display.parties(candidate)) === 'Other / independent' && candidate.votes < cutoff));
  if (!grouped.size) return candidates;

  // Keep distinct write-in categories separate from an existing Other bucket.
  for (const candidate of candidates) {
    if (candidate.kind === 'aggregate' && display.name(candidate).trim().toUpperCase() === 'OTHER') grouped.add(candidate);
  }
  const members = [...grouped];
  const votes = members.reduce((sum, candidate) => sum + candidate.votes, 0);
  return [...candidates.filter(candidate => !grouped.has(candidate)), display.other(members, votes, votes / totalVotes * 100)];
}
