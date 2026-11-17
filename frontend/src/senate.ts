import { ApiError } from './api';
import { aggregateMinorCandidates } from './candidateAggregation';
import type { CandidatePortrait } from './candidateMedia';

export interface SenateCandidate {
  portrait?: CandidatePortrait | null;
  name: string; party: string; votes: number; share_pct: number | null;
  outcome: '' | 'leads' | 'won';
  candidacy_id?: string | null; kind?: 'candidate' | 'aggregate'; incumbent?: boolean | null;
  incumbent_evidence?: { url: string; as_of: string; reviewed_at: string } | null;
}
export interface SenateRace {
  id: string; state_code: string; state_name: string; seat_class: number; special: boolean;
  status: 'counting' | 'called' | 'final'; total_votes: number; candidates: SenateCandidate[];
  count_updated_at: string | null; source_read_at: string; called_at: string | null;
  source: string; source_url: string; page_url: string;
  contest_id?: string | null;
  summary_status?: 'available' | 'tie' | 'zero_total' | 'indeterminate' | 'no_results' | null;
  leader?: string | null; margin_votes?: number | null; margin_pct?: number | null;
}

/** Compact results retain original candidate objects and synthesize only Other. */
export function senateDisplayCandidates(race: SenateRace): SenateCandidate[] {
  return aggregateMinorCandidates(race.candidates, race.total_votes, {
    name: candidate => candidate.name,
    parties: candidate => candidate.party ? [candidate.party === 'D' ? 'DEMOCRATIC' : candidate.party === 'R' ? 'REPUBLICAN' : candidate.party] : [],
    other: (_members, votes, share_pct) => ({
      name: 'Other', kind: 'aggregate', party: 'O', votes, share_pct, outcome: '', candidacy_id: null,
    }),
  });
}
export interface ProvisionalSenateElection { race: SenateRace; checked_at: string; stale: boolean; sha256: string; retrieved_at: string }

export const senateRaceHref = (state: string) => `/senate/2026/races/${encodeURIComponent(state)}`;
export interface SenateResults {
  control?: SenateControl | null;
  year: number; election_date: string; races: SenateRace[]; expected_contests: number; missing_states: string[];
  checked_at: string; retrieved_at: string; published_at: string; next_refresh_at: string;
  stale: boolean; refresh_failed: boolean; sha256: string; source_url: string; manifest_url: string;
}

export interface SenateControl {
  total_seats: number; majority_threshold: number; seats_up: number;
  retained: Record<string, number>; called: Record<string, number>; totals: Record<string, number>;
  unresolved: number; democratic_aligned: number; retained_democratic_aligned: number;
  independent_democratic_caucus: number; other_unaligned: number; certified_contests: number;
  control: 'D' | 'R' | null; gains: Record<string, number>; net_change: Record<string, number>;
  baseline_as_of: string; baseline_reviewed_at: string; sources: string[];
}

const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
const date = (value: string) => typeof value === 'string' && Number.isFinite(Date.parse(value));
export async function fetchSenateResults(signal: AbortSignal): Promise<SenateResults> {
  const response = await fetch('/api/v1/senate/2026/results', { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new ApiError(response.status, 'Senate results are temporarily unavailable. The daily snapshot may still be preparing.');
  const body: SenateResults = await response.json();
  if (body?.year !== 2026 || body.election_date !== '2026-11-03' || body.expected_contests !== 35 ||
      !Array.isArray(body.races) || !Array.isArray(body.missing_states) ||
      body.missing_states.some(state => typeof state !== 'string' || !/^[A-Z]{2}$/.test(state)) ||
      typeof body.stale !== 'boolean' || typeof body.refresh_failed !== 'boolean' ||
      ![body.checked_at, body.retrieved_at, body.published_at, body.next_refresh_at].every(date) ||
      typeof body.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(body.sha256) ||
      typeof body.source_url !== 'string' || typeof body.manifest_url !== 'string' ||
      body.races.some(race => !race || typeof race.id !== 'string' || typeof race.state_name !== 'string' ||
        !/^[A-Z]{2}$/.test(race.state_code) || ![2, 3].includes(race.seat_class) || typeof race.special !== 'boolean' ||
        !['counting', 'called', 'final'].includes(race.status) || !count(race.total_votes) ||
        !date(race.source_read_at) || !(race.count_updated_at === null || date(race.count_updated_at)) ||
        typeof race.source !== 'string' || typeof race.source_url !== 'string' || typeof race.page_url !== 'string' ||
        !Array.isArray(race.candidates) || !race.candidates.length || race.candidates.some(candidate =>
          !candidate || typeof candidate.name !== 'string' || typeof candidate.party !== 'string' || !count(candidate.votes) ||
          !['', 'leads', 'won'].includes(candidate.outcome) || !(candidate.share_pct === null ||
            (Number.isFinite(candidate.share_pct) && candidate.share_pct >= 0 && candidate.share_pct <= 100))) ||
        race.candidates.reduce((sum, candidate) => sum + candidate.votes, 0) !== race.total_votes) ||
      new Set(body.races.map(race => race.id)).size !== body.races.length ||
      body.races.length + body.missing_states.length !== body.expected_contests) {
    throw new Error('Unexpected Senate results response');
  }
  return body;
}
