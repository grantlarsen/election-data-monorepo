import type { CandidatePortrait } from '../candidateMedia';
import type { SenateRace } from '../senate';
import { candidacyId } from './fixtures';

export const portrait: CandidatePortrait = {
  url: `/media/candidates/${'a'.repeat(64)}.jpg`, source: 'https://commons.wikimedia.org/wiki/File:Example.jpg',
  credit: 'Example photographer / Wikimedia Commons', license: 'CC BY 4.0',
  license_url: 'https://creativecommons.org/licenses/by/4.0/', sha256: 'a'.repeat(64),
};
export const portraitRace: SenateRace = {
  id: 'SEN-FL', state_code: 'FL', state_name: 'Florida', seat_class: 3, special: true,
  status: 'called', total_votes: 100,
  candidates: [
    { name: 'Portrait candidate', party: 'D', votes: 60, share_pct: 60, outcome: 'won', candidacy_id: candidacyId, portrait },
    { name: 'Other candidate', party: 'R', votes: 40, share_pct: 40, outcome: '', candidacy_id: 'another-source-candidate' },
  ], count_updated_at: null, source_read_at: '2026-11-16T12:00:00Z', called_at: null,
  source: 'civicAPI', source_url: 'https://civicapi.org/race/example', page_url: 'https://www.callthemap.com/results/senate/florida',
};
