import { aggregateMinorCandidates } from '../candidateAggregation';
import type { MapCandidate, Summary } from './types';

/** Compact presentation only; source rows, leaders and margins remain unchanged. */
export function popoverCandidates(summary?: Summary): MapCandidate[] {
  if (!summary) return [];
  return aggregateMinorCandidates(summary.candidates, summary.total_votes, {
    name: candidate => candidate.label,
    parties: candidate => candidate.party_labels,
    other: (members, votes, share) => ({
      label: 'Other', kind: 'aggregate', votes, share,
      candidacy_id: null, geographic_reference_id: null,
      observation_ids: members.flatMap(candidate => candidate.observation_ids || []),
      correction_ids: members.flatMap(candidate => candidate.correction_ids || []),
    }),
  });
}
