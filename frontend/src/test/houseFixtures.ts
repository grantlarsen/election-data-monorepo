import type { HouseRace, HouseResults } from '../house';

export function snapshot(): HouseResults {
  const race: HouseRace = { id: 'CA-01', state_code: 'CA', state_name: 'California', district_code: '01',
    status: 'counting', total_votes: 100, candidates: [
      { name: 'Candidate D', party: 'D', votes: 60, share_pct: 60, outcome: 'leads', source_row_number: 1,
        candidacy_id: '11111111-1111-4111-8111-111111111111', incumbent: true },
      { name: 'Candidate R', party: 'R', votes: 35, share_pct: 35, outcome: '', source_row_number: 2 },
      { name: 'Write-in', party: 'O', votes: 5, share_pct: 5, outcome: '', source_row_number: 3 },
    ], count_updated_at: '2026-11-16T12:00:00Z', source_read_at: '2026-11-16T13:00:00Z', called_at: null,
    source: 'civicAPI', source_url: 'https://civicapi.org/race/example', page_url: 'https://www.callthemap.com/results/house/ca-01' };
  const counts: Record<string, number> = { AL:7, AK:1, AZ:9, AR:4, CA:52, CO:8, CT:5, DE:1, FL:28, GA:14,
    HI:2, ID:2, IL:17, IN:9, IA:4, KS:4, KY:6, LA:6, ME:2, MD:8, MA:9, MI:13, MN:8, MS:4, MO:8, MT:2,
    NE:3, NV:4, NH:2, NJ:12, NM:3, NY:26, NC:14, ND:1, OH:15, OK:5, OR:6, PA:17, RI:2, SC:7, SD:1,
    TN:9, TX:38, UT:4, VT:1, VA:11, WA:10, WV:2, WI:8, WY:1 };
  const races: HouseRace[] = [race, { ...race, id: 'WY-AL', state_code: 'WY', state_name: 'Wyoming', district_code: '00', status: 'final',
    candidates: race.candidates.map((c, index) => ({ ...c, outcome: index === 1 ? 'won' : '', name: `WY ${c.name}` })) },
    { ...race, id: 'FL-10', state_code: 'FL', state_name: 'Florida', district_code: '10', status: 'called', total_votes: null,
      candidates: [{ name: 'Unopposed candidate', party: 'D', votes: null, share_pct: null, outcome: 'won', source_row_number: 4 }] }];
  return { year: 2026, election_date: '2026-11-03', expected_contests: 435, races,
    missing_districts: Object.entries(counts).flatMap(([state, count]) => Array.from({ length: count }, (_, i) =>
      `${state}-${count === 1 ? 'AL' : String(i + 1).padStart(2, '0')}`)).filter(id => !races.some(r => r.id === id)),
    control: { total_seats: 435, majority_threshold: 218, called: { D: 1, R: 1, other: 0 }, unresolved: 433, control: null },
    checked_at: '2026-11-17T12:00:00Z', retrieved_at: '2026-11-17T12:00:00Z', published_at: '2026-11-17T05:00:00Z',
    next_refresh_at: '2026-11-18T12:00:00Z', stale: false, refresh_failed: false, sha256: 'a'.repeat(64),
    source_url: 'https://www.callthemap.com/results/data/2026/races.csv', manifest_url: 'https://www.callthemap.com/results/data/2026/manifest.json' };
}
