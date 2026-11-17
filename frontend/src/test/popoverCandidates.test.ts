import { describe, expect, it } from 'vitest';
import { popoverCandidates } from '../map/popoverCandidates';
import type { MapCandidate, Summary } from '../map/types';

const candidate = (label: string, votes: number, party_labels: string[] = ['GREEN']): MapCandidate => ({
  label, votes, party_labels, share: null, kind: 'candidate', candidacy_id: label,
  geographic_reference_id: null, observation_ids: [label], correction_ids: [],
});
const summary = (total_votes: number | null, candidates: MapCandidate[]): Summary => ({
  total_votes, candidates, status: 'available', leader: null, margin_votes: null, margin_pp: null,
});

describe('popover candidate grouping', () => {
  it.each([
    { total: 100_000, votes: 99, grouped: true },
    { total: 100_000, votes: 100, grouped: false },
    { total: 100_000, votes: 500, grouped: false }, // Below 1,000, above 0.1%.
    { total: 10_000_000, votes: 999, grouped: true },
    { total: 10_000_000, votes: 1_000, grouped: false }, // Below 0.1%, at 1,000.
    { total: 10_000_000, votes: 1_001, grouped: false },
    { total: 999_000, votes: 998, grouped: true }, // A rounded 0.10% must still group.
    { total: 999_000, votes: 999, grouped: false },
    { total: 100, votes: 0, grouped: true },
  ])('uses the strict smaller cutoff for $votes votes out of $total', ({ total, votes, grouped }) => {
    const source = summary(total, [candidate('Major', total - votes, ['DEMOCRATIC']),
      { ...candidate('Minor', votes), share: Number((votes / total * 100).toFixed(2)) }]);
    const before = structuredClone(source);
    const result = popoverCandidates(source);
    expect(result.map(row => row.label)).toEqual(['Major', grouped ? 'Other' : 'Minor']);
    expect(result.reduce((sum, row) => sum + row.votes, 0)).toBe(total);
    expect(source).toEqual(before);
  });

  it('preserves major-party, fusion and unknown-party candidates even below the cutoff', () => {
    const labels = [['DEMOCRATIC'], ['REPUBLICAN'], ['DEMOCRATIC-FARMER-LABOR'],
      ['GREEN', 'DEMOCRATIC'], ['REPUBLICAN', 'CONSERVATIVE'], ['DEMOCRATIC', 'REPUBLICAN'], []];
    const source = summary(100_000, labels.map((parties, index) => candidate(`Candidate ${index}`, 1, parties)));
    expect(popoverCandidates(source)).toBe(source.candidates);
  });

  it('combines only eligible candidates and existing Other buckets without inventing an identity', () => {
    const source = summary(100_000, [candidate('Democrat', 60_000, ['DEMOCRATIC']),
      candidate('Republican', 39_200, ['REPUBLICAN']),
      { ...candidate('Independent', 50, ['INDEPENDENT']), kind: 'source_candidate', incumbent: true },
      candidate('Green', 49), candidate('Libertarian', 600, ['LIBERTARIAN']),
      candidate('Unknown party', 1, []),
      { ...candidate('Write-ins', 80), kind: 'aggregate', candidacy_id: null },
      { ...candidate('OTHER', 20), kind: 'aggregate', candidacy_id: null },
    ]);
    const before = structuredClone(source);
    const rows = popoverCandidates(source);
    expect(rows.map(row => row.label)).toEqual(['Democrat', 'Republican', 'Libertarian', 'Unknown party', 'Write-ins', 'Other']);
    expect(rows.at(-1)).toEqual({ label: 'Other', votes: 119, share: expect.closeTo(0.119, 12), kind: 'aggregate',
      candidacy_id: null, geographic_reference_id: null,
      observation_ids: ['Independent', 'Green', 'OTHER'], correction_ids: [] });
    expect(rows.reduce((sum, row) => sum + row.votes, 0)).toBe(source.total_votes);
    expect(source).toEqual(before);
  });

  it.each([null, 0])('keeps candidates separate when total votes are %s', total => {
    const source = summary(total, [candidate('Independent', 0, ['INDEPENDENT'])]);
    expect(popoverCandidates(source)).toBe(source.candidates);
    expect(popoverCandidates()).toEqual([]);
  });
});
