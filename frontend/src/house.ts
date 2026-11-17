import { ApiError } from './api';
import { aggregateMinorCandidates } from './candidateAggregation';
import type { CandidatePortrait } from './candidateMedia';

export interface HouseCandidate {
  portrait?: CandidatePortrait | null;
  candidacy_id?: string | null; incumbent?: boolean | null; incumbent_evidence?: { as_of: string; url: string } | null;
  name: string; party: string; votes: number | null; share_pct: number | null;
  outcome: '' | 'leads' | 'won'; source_row_number: number; kind?: 'candidate' | 'aggregate';
}
export interface HouseRace {
  contest_id?: string | null;
  id: string; state_code: string; state_name: string; district_code: string;
  status: 'counting' | 'called' | 'final'; total_votes: number | null; candidates: HouseCandidate[];
  count_updated_at: string | null; source_read_at: string; called_at: string | null;
  source: string; source_url: string; page_url: string;
}
export interface HouseResults {
  year: number; election_date: string; races: HouseRace[]; expected_contests: number; missing_districts: string[];
  control: { total_seats: number; majority_threshold: number; called: Record<'D' | 'R' | 'other', number>;
    unresolved: number; control: 'D' | 'R' | null };
  checked_at: string; retrieved_at: string; published_at: string; next_refresh_at: string;
  stale: boolean; refresh_failed: boolean; sha256: string; source_url: string; manifest_url: string;
}
export interface ProvisionalHouseElection { race: HouseRace; checked_at: string; retrieved_at: string; stale: boolean; sha256: string }
export const houseRaceHref = (id: string) => `/house/2026/races/${encodeURIComponent(id)}`;
export const houseRaceTitle = (race: HouseRace) => `${race.state_name} ${race.district_code === '00' ? 'at-large' : `District ${Number(race.district_code)}`}`;
export const houseWinner = (race: HouseRace) => race.status === 'counting' ? undefined : race.candidates.find(c => c.outcome === 'won');
export const houseStatuses = { counting: 'Counting · no call', called: 'Media call · uncertified', final: 'Certified · per source' };
export const houseParties: Record<string, string> = { D: 'Democratic', R: 'Republican', I: 'Independent', L: 'Libertarian', G: 'Green', O: 'Other' };
export const housePartyClass = (party?: string) => party === 'D' ? 'control-democratic' : party === 'R' ? 'control-republican' : party ? 'control-other' : 'control-uncalled';
export const houseCandidateKind = (candidate: HouseCandidate) => candidate.kind ||
  (/^(write[ -]?ins?|other|scattering)$/i.test(candidate.name) ? 'aggregate' as const : 'candidate' as const);

export function houseDisplayCandidates(race: HouseRace): HouseCandidate[] {
  if (race.total_votes === null || race.candidates.some(c => c.votes === null)) return race.candidates;
  return aggregateMinorCandidates(race.candidates.map(c => ({ ...c, votes: c.votes!,
    kind: houseCandidateKind(c) })), race.total_votes, {
    name: c => c.name, parties: c => [c.party === 'D' ? 'DEMOCRATIC' : c.party === 'R' ? 'REPUBLICAN' : c.party],
    other: (_members, votes, share_pct) => ({ name: 'Other', party: 'O', kind: 'aggregate' as const, votes, share_pct,
      outcome: '' as const, source_row_number: 0 }),
  });
}

const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
const date = (value: string) => typeof value === 'string' && Number.isFinite(Date.parse(value));
export async function fetchHouseResults(signal: AbortSignal): Promise<HouseResults> {
  const response = await fetch('/api/v1/house/2026/results', { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new ApiError(response.status, 'House results are temporarily unavailable.');
  const body: HouseResults = await response.json();
  if (body?.year !== 2026 || body.election_date !== '2026-11-03' || body.expected_contests !== 435 ||
      !Array.isArray(body.races) || !Array.isArray(body.missing_districts) ||
      body.missing_districts.some(id => typeof id !== 'string' || !/^[A-Z]{2}-(AL|\d{2})$/.test(id)) ||
      typeof body.stale !== 'boolean' || typeof body.refresh_failed !== 'boolean' ||
      ![body.checked_at, body.retrieved_at, body.published_at, body.next_refresh_at].every(date) ||
      typeof body.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(body.sha256) ||
      typeof body.source_url !== 'string' || typeof body.manifest_url !== 'string' ||
      body.races.some(race => !race || typeof race.state_name !== 'string' || !/^[A-Z]{2}$/.test(race.state_code) ||
        !/^\d{2}$/.test(race.district_code) || race.id !== `${race.state_code}-${race.district_code === '00' ? 'AL' : race.district_code}` ||
        !['counting', 'called', 'final'].includes(race.status) || !(race.total_votes === null || count(race.total_votes)) ||
        !date(race.source_read_at) || !(race.count_updated_at === null || date(race.count_updated_at)) ||
        !(race.called_at === null || date(race.called_at)) || typeof race.source !== 'string' ||
        typeof race.source_url !== 'string' || typeof race.page_url !== 'string' ||
        !Array.isArray(race.candidates) || !race.candidates.length || race.candidates.some(c => !c ||
          typeof c.name !== 'string' || typeof c.party !== 'string' || !count(c.source_row_number) ||
          (race.total_votes === null ? c.votes !== null || c.share_pct !== null : c.votes === null || !count(c.votes)) ||
          !['', 'leads', 'won'].includes(c.outcome) || !(c.share_pct === null ||
            Number.isFinite(c.share_pct) && c.share_pct >= 0 && c.share_pct <= 100)) ||
        (race.total_votes !== null && race.candidates.reduce((sum, c) => sum + (c.votes ?? 0), 0) !== race.total_votes) ||
        race.candidates.filter(c => c.outcome === 'won').length !== (race.status === 'counting' ? 0 : 1)) ||
      new Set([...body.races.map(race => race.id), ...body.missing_districts]).size !== 435 ||
      body.races.length + body.missing_districts.length !== 435) throw new Error('Unexpected House results response');
  const c = body.control;
  const called = { D: 0, R: 0, other: 0 };
  body.races.forEach(race => { const winner = houseWinner(race); if (winner) called[winner.party === 'D' ? 'D' : winner.party === 'R' ? 'R' : 'other']++; });
  if (!c || c.total_seats !== 435 || c.majority_threshold !== 218 || !c.called ||
      !(['D', 'R', 'other'] as const).every(party => c.called[party] === called[party]) ||
      c.unresolved !== 435 - called.D - called.R - called.other ||
      c.control !== (called.D >= 218 ? 'D' : called.R >= 218 ? 'R' : null)) throw new Error('Unexpected House seat accounting');
  return body;
}
