import type { Summary, MapCandidate } from './types';
import { leaderCandidate } from './types';

export const partyPalette = {
  Democratic: '#3276ac',
  Republican: '#bd5548',
  'Other / independent': '#358369',
  'Multiple major parties': '#8c6bb1',
  'Party unavailable': '#687687',
};
export const missingColor = '#d9ded9';
export const indeterminateColor = '#7d8584';
export const tieColor = '#8e759b';

export function partyGroup(labels: string[] = []): keyof typeof partyPalette {
  const normalized = labels.map(label => label.normalize('NFKC').trim().toUpperCase()).filter(Boolean);
  const democratic = normalized.some(label => ['DEMOCRATIC', 'DEMOCRAT', 'DEMOCRATIC-FARMER-LABOR'].includes(label));
  const republican = normalized.includes('REPUBLICAN');
  return democratic && republican ? 'Multiple major parties' : democratic ? 'Democratic' : republican ? 'Republican'
    : normalized.length ? 'Other / independent' : 'Party unavailable';
}

/** Every election view uses the source parties, never candidate-name hashes. */
export function mapCandidateColor(candidate: Pick<MapCandidate, 'kind' | 'party_labels'>): string {
  return ['candidate', 'source_candidate'].includes(candidate.kind)
    ? partyPalette[partyGroup(candidate.party_labels)] : indeterminateColor;
}

export function resultColor(summary?: Summary): string {
  if (!summary || summary.status === 'no_results') return missingColor;
  if (summary.status === 'tie') return tieColor;
  const leader = leaderCandidate(summary);
  return leader ? mapCandidateColor(leader) : indeterminateColor;
}
