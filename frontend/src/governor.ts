import { ApiError } from './api';
import { aggregateMinorCandidates } from './candidateAggregation';
import type { CandidatePortrait } from './candidateMedia';

export const governorStates = 'AK AL AR AZ CA CO CT FL GA HI IA ID IL KS MA MD ME MI MN NE NH NM NV NY OH OK OR PA RI SC SD TN TX VT WI WY'.split(' ');
export interface GovernorCandidate {
  portrait?: CandidatePortrait | null;
  candidacy_id?: string | null; incumbent?: boolean | null;
  incumbent_evidence?: { url: string; as_of: string; reviewed_at: string } | null;
  name: string; party: string; votes: number | null; share_pct: number | null;
  outcome: '' | 'leads' | 'won'; source_row_number: number; kind?: 'candidate' | 'aggregate';
}
export interface GovernorRace {
  contest_id?: string | null;
  previous_election?: { year: number; winner_name: string; party: string; source_url: string; reviewed_at: string; source_sha256: string } | null;
  flipped?: boolean | null;
  id: string; state_code: string; state_name: string;
  status: 'counting' | 'called' | 'final'; total_votes: number | null; candidates: GovernorCandidate[];
  count_updated_at: string | null; source_read_at: string; called_at: string | null;
  source: string; source_url: string; page_url: string;
}
export interface GovernorResults {
  year: number; election_date: string; races: GovernorRace[]; expected_contests: number; missing_states: string[];
  checked_at: string; retrieved_at: string; published_at: string; next_refresh_at: string;
  stale: boolean; refresh_failed: boolean; sha256: string; source_url: string; manifest_url: string;
}
export interface ProvisionalGovernorElection { race: GovernorRace; checked_at: string; retrieved_at: string; stale: boolean; sha256: string }
export const governorRaceHref = (state: string) => `/governor/2026/races/${encodeURIComponent(state)}`;
export const governorStatuses = { counting: 'Counting · no call', called: 'Media call · uncertified', final: 'Certified · per source' };
export const governorParties: Record<string, string> = { D: 'Democratic', R: 'Republican', I: 'Independent', L: 'Libertarian', G: 'Green', O: 'Other' };
export const governorWinner = (race: GovernorRace) => race.status === 'counting' ? undefined : race.candidates.find(c => c.outcome === 'won');
export const governorCandidateKind = (candidate: GovernorCandidate) => candidate.kind ||
  (/^(write[ -]?ins?|other|scattering)$/i.test(candidate.name) ? 'aggregate' as const : 'candidate' as const);

/** Group small source lines for the overview only; full race tables retain every row. */
export function governorDisplayCandidates(race: GovernorRace): GovernorCandidate[] {
  if (race.total_votes === null || race.candidates.some(c => c.votes === null)) return race.candidates;
  return aggregateMinorCandidates(race.candidates.map(c => ({ ...c, votes: c.votes!, kind: governorCandidateKind(c) })), race.total_votes, {
    name: c => c.name, parties: c => [c.party === 'D' ? 'DEMOCRATIC' : c.party === 'R' ? 'REPUBLICAN' : c.party],
    other: (_members, votes, share_pct) => ({ name: 'Other', party: 'O', kind: 'aggregate' as const, votes, share_pct,
      outcome: '' as const, source_row_number: 0, candidacy_id: null, incumbent: null }),
  });
}

const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
const date = (value: string) => typeof value === 'string' && Number.isFinite(Date.parse(value));
export async function fetchGovernorResults(signal: AbortSignal): Promise<GovernorResults> {
  const response = await fetch('/api/v1/governor/2026/results', { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new ApiError(response.status, 'Governor results are temporarily unavailable.');
  const body: GovernorResults = await response.json();
  if (body?.year !== 2026 || body.election_date !== '2026-11-03' || body.expected_contests !== 36 ||
      !Array.isArray(body.races) || !Array.isArray(body.missing_states) ||
      body.missing_states.some(state => !governorStates.includes(state)) ||
      typeof body.stale !== 'boolean' || typeof body.refresh_failed !== 'boolean' ||
      ![body.checked_at, body.retrieved_at, body.published_at, body.next_refresh_at].every(date) ||
      typeof body.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(body.sha256) ||
      typeof body.source_url !== 'string' || typeof body.manifest_url !== 'string' ||
      body.races.some(race => !race || typeof race.state_name !== 'string' || !governorStates.includes(race.state_code) ||
        race.id !== `GOV-${race.state_code}` || !Object.hasOwn(governorStatuses, race.status) ||
        !(race.total_votes === null || count(race.total_votes)) || !date(race.source_read_at) ||
        !(race.count_updated_at === null || date(race.count_updated_at)) || !(race.called_at === null || date(race.called_at)) ||
        typeof race.source !== 'string' || typeof race.source_url !== 'string' || typeof race.page_url !== 'string' ||
        !Array.isArray(race.candidates) || !race.candidates.length || race.candidates.some(c => !c ||
          typeof c.name !== 'string' || typeof c.party !== 'string' || !count(c.source_row_number) ||
          (race.total_votes === null ? c.votes !== null || c.share_pct !== null : c.votes === null || !count(c.votes)) ||
          !['', 'leads', 'won'].includes(c.outcome) || !(c.share_pct === null ||
            Number.isFinite(c.share_pct) && c.share_pct >= 0 && c.share_pct <= 100)) ||
        (race.total_votes !== null && race.candidates.reduce((sum, c) => sum + (c.votes ?? 0), 0) !== race.total_votes) ||
        race.candidates.filter(c => c.outcome === 'won').length !== (race.status === 'counting' ? 0 : 1)) ||
      new Set([...body.races.map(race => race.state_code), ...body.missing_states]).size !== 36 ||
      body.races.length + body.missing_states.length !== 36) throw new Error('Unexpected Governor results response');
  return body;
}
