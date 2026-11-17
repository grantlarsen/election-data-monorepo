import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { fetchSenateResults, senateDisplayCandidates } from '../senate';
import type { SenateRace, SenateResults } from '../senate';
import states from '../geography/data/states.json';
import { portrait } from './portraitFixtures';

function stubResults(resultFetch: (url: string, options?: RequestInit) => unknown) {
  vi.stubGlobal('fetch', (url: string, options?: RequestInit) => String(url).includes('states.json')
    ? Promise.resolve({ ok: true, json: async () => states }) : resultFetch(url, options));
}

function snapshot(): SenateResults {
  const race: SenateRace = { id: 'SEN-FL', state_code: 'FL', state_name: 'Florida', seat_class: 3, special: true,
    status: 'called', total_votes: 100, candidates: [
      { name: 'Candidate R', party: 'R', votes: 60, share_pct: 60, outcome: 'won', candidacy_id: '11111111-1111-4111-8111-111111111111', incumbent: true,
        incumbent_evidence: { url: 'https://www.senate.gov/senators/Class_III.htm', as_of: '2026-11-03', reviewed_at: '2026-11-17' } },
      { name: 'Candidate D', party: 'D', votes: 35, share_pct: 35, outcome: '', candidacy_id: '22222222-2222-4222-8222-222222222222' },
      { name: 'Write-in', party: 'O', votes: 5, share_pct: 5, outcome: '', candidacy_id: null, kind: 'aggregate' },
    ], count_updated_at: '2026-11-16T12:00:00Z', source_read_at: '2026-11-16T13:00:00Z', called_at: null,
    source: 'civicAPI', source_url: 'https://civicapi.org/race/example', page_url: 'https://www.callthemap.com/results/senate/fl' };
  return { year: 2026, election_date: '2026-11-03', expected_contests: 35,
    races: [race, { ...race, id: 'SEN-WY', state_code: 'WY', state_name: 'Wyoming', seat_class: 2, special: false,
      status: 'final', source: 'Wyoming Secretary of State', source_url: 'https://sos.wyo.gov/results.pdf',
      candidates: race.candidates.map(candidate => ({ ...candidate, name: `WY ${candidate.name}` })) }],
    missing_states: 'AK AL AR CO DE GA IA ID IL KS KY LA MA ME MI MN MS MT NC NE NH NJ NM OH OK OR RI SC SD TN TX VA WV'.split(' '),
    checked_at: '2026-11-17T12:00:00Z', retrieved_at: '2026-11-17T12:00:00Z', published_at: '2026-11-16T15:00:00Z',
    next_refresh_at: '2026-11-18T12:00:00Z', stale: false, refresh_failed: false, sha256: 'a'.repeat(64),
    source_url: 'https://www.callthemap.com/results/data/2026/races.csv', manifest_url: 'https://www.callthemap.com/results/data/2026/manifest.json' };
}
const response = (body = snapshot()) => ({ ok: true, json: async () => body });
function open(path = '/senate/2026/results') {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

describe('2026 Senate results', () => {
  it('uses candidate thumbnails without assigning one to aggregate rows and preserves a dot when an image fails', async () => {
    const body = snapshot();
    body.races[0].candidates[0].portrait = portrait;
    body.races[0].candidates[2].portrait = portrait;
    stubResults(vi.fn().mockResolvedValue(response(body)));
    open();
    const card = await screen.findByRole('article', { name: 'Florida' });
    const images = card.querySelectorAll('tbody img');
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute('src', portrait.url);
    expect(within(card).getByRole('link', { name: 'Candidate R' }).closest('th')).toContainElement(images[0] as HTMLElement);
    fireEvent.error(images[0]);
    expect(card.querySelectorAll('tbody img')).toHaveLength(0);
    expect(within(card).getByRole('link', { name: 'Candidate R' }).closest('th')?.querySelector('.senate-party-dot')).toBeVisible();
  });
  it('places the map above state results and supports selecting and clearing a state', async () => {
    const user = userEvent.setup();
    stubResults(vi.fn().mockResolvedValue(response()));
    open('/senate/2026/results?state_code=WY&status=final');
    const map = await screen.findByRole('group', { name: '2026 Senate results map' });
    const florida = within(map).getByRole('button', { name: /^Florida:/ });
    expect(map.compareDocumentPosition(screen.getByRole('article', { name: 'Wyoming' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.keyDown(florida, { key: 'Enter' });
    expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
    expect(screen.queryByRole('article', { name: 'Wyoming' })).not.toBeInTheDocument();
    expect(florida).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('combobox', { name: 'Result status' })).toHaveValue('');
    await user.click(screen.getByRole('button', { name: 'Show all states' }));
    expect(screen.getAllByRole('article')).toHaveLength(2);
  });
  it('opens the real page from the header without a Coming soon label', async () => {
    const user = userEvent.setup();
    const fetch = vi.fn().mockResolvedValue(response()); stubResults(fetch);
    open('/');
    await user.click(screen.getByRole('button', { name: 'Senate' }));
    const link = screen.getByRole('link', { name: '2026 Election Results' });
    expect(link).toHaveAttribute('href', '/senate/2026/results');
    expect(within(link).queryByText('Coming soon')).not.toBeInTheDocument();
    await user.click(link);
    expect(await screen.findByRole('heading', { name: 'Florida' })).toBeVisible();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('2026 Senate Election Results');
    expect(document.title).toBe('2026 Senate Election Results | Electoral Atlas');
    expect(screen.queryByText(/US elections.*Research workspace/i)).not.toBeInTheDocument();
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/senate/2026/results');
  });

  it('shows candidate and bucket rows in one compact table with source times and distinct call/certification labels', async () => {
    stubResults(vi.fn().mockResolvedValue(response()));
    open();
    const florida = await screen.findByRole('article', { name: 'Florida' });
    expect(within(florida).getByText('Media call · uncertified')).toBeVisible();
    expect(within(florida).queryByText(/^Class /)).not.toBeInTheDocument();
    expect(within(florida).getAllByRole('table')).toHaveLength(1);
    expect(within(florida).getByRole('table', { name: 'Florida Senate candidate results' })).toBeVisible();
    expect(florida.querySelectorAll('caption, summary')).toHaveLength(0);
    expect(within(florida).getByText('60.00%')).toBeVisible();
    expect(within(florida).getByText('100 votes counted')).toBeVisible();
    expect(within(florida).queryByText(/Certified winner/)).not.toBeInTheDocument();
    expect(within(florida).getByText(/Source read:/)).toBeVisible();
    expect(within(florida).getByRole('link', { name: 'Candidate R' }).getAttribute('href')).toContain('/candidates/11111111-1111-4111-8111-111111111111');
    expect(within(florida).getByRole('link', { name: 'Florida' })).toHaveAttribute('href', '/senate/2026/races/FL');
    expect(within(florida).getByText('Incumbent')).toBeVisible();
    expect(within(florida).queryByRole('link', { name: 'Incumbent' })).not.toBeInTheDocument();
    expect(within(florida).queryByRole('link', { name: 'Write-in' })).not.toBeInTheDocument();
    expect(within(florida).getByRole('rowheader', { name: /^Write-in/ })).toBeVisible();
    const wyoming = screen.getByRole('article', { name: 'Wyoming' });
    expect(within(wyoming).getByText('Certified · per source')).toBeVisible();
    expect(within(wyoming).getByText('Certified winner per source')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Partial source coverage' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Wyoming Secretary of State' })).toHaveAttribute('href', 'https://sos.wyo.gov/results.pdf');
    expect(screen.getByText('civicAPI, compiled from state and county election offices.', { exact: false })).toBeVisible();
  });

  it('opens a state race page from the state label and retains source-scoped candidate links', async () => {
    const user = userEvent.setup();
    stubResults(vi.fn().mockResolvedValue(response()));
    open();
    const card = await screen.findByRole('article', { name: 'Florida' });
    await user.click(within(card).getByRole('link', { name: 'Florida' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Florida — 2026 Senate Election' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Candidate D' }).getAttribute('href')).toContain('/candidates/22222222-2222-4222-8222-222222222222');
    expect(screen.queryByText(/US elections.*Research workspace/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Special election · Class 3/)).not.toBeInTheDocument();
    expect(screen.queryByText('Snapshot provenance')).not.toBeInTheDocument();
    const map = await screen.findByRole('group', { name: 'Florida 2026 Senate race map' });
    const table = screen.getByRole('table', { name: 'Florida Senate candidate results' });
    expect(map.querySelectorAll('path[data-geoid]')).toHaveLength(1);
    expect(map.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const note = screen.getByText(/Provisional counts can change/);
    expect(table.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.title).toBe('Florida — 2026 Senate Election | Electoral Atlas');
  });

  it('groups small third-party rows with reconciled totals and keeps every candidate on the detailed race page', async () => {
    const body = snapshot();
    body.races[0].total_votes = 100_000;
    body.races[0].candidates = [
      { ...body.races[0].candidates[0], votes: 60_000, share_pct: 60 },
      { ...body.races[0].candidates[1], votes: 39_200, share_pct: 39.2 },
      { name: 'Small independent', party: 'I', votes: 50, share_pct: 0.05, outcome: '', candidacy_id: 'small-one' },
      { name: 'Small Green', party: 'G', votes: 49, share_pct: 0.05, outcome: '', candidacy_id: 'small-two' },
      { name: 'Libertarian', party: 'L', votes: 600, share_pct: 0.6, outcome: '', candidacy_id: 'retained' },
      { name: 'Unknown party', party: '', votes: 1, share_pct: 0, outcome: '', candidacy_id: 'unknown' },
      { name: 'Write-in', party: 'O', votes: 80, share_pct: 0.08, outcome: '', kind: 'aggregate', candidacy_id: null },
      { name: 'OTHER', party: 'O', votes: 20, share_pct: 0.02, outcome: '', kind: 'aggregate', candidacy_id: null },
    ];
    const before = structuredClone(body);
    stubResults(vi.fn().mockResolvedValue(response(body)));
    const user = userEvent.setup();
    open();
    const card = await screen.findByRole('article', { name: 'Florida' });
    const table = within(card).getByRole('table');
    expect(within(table).queryByText('Small independent')).not.toBeInTheDocument();
    expect(within(table).queryByText('Small Green')).not.toBeInTheDocument();
    expect(within(table).getByRole('link', { name: 'Libertarian' })).toBeVisible();
    expect(within(table).getByRole('link', { name: 'Unknown party' })).toBeVisible();
    expect(within(table).getByRole('rowheader', { name: /^Write-in/ })).toBeVisible();
    const other = within(table).getByRole('rowheader', { name: /^Other/ }).closest('tr')!;
    expect(within(other).getByRole('cell', { name: '119' })).toBeVisible();
    expect(within(other).getByRole('cell', { name: '0.12%' })).toBeVisible();
    expect(within(other).queryByRole('link')).not.toBeInTheDocument();
    expect(within(other).queryByText('Incumbent')).not.toBeInTheDocument();
    expect(within(other).queryByText(/Called|Certified/)).not.toBeInTheDocument();
    const rows = [...table.querySelectorAll('tbody tr')];
    expect(rows).toHaveLength(6);
    expect(rows.reduce((sum, row) => sum + Number(row.children[2].textContent?.replaceAll(',', '')), 0)).toBe(100_000);
    expect(within(card).getByText('100,000 votes counted')).toBeVisible();
    expect(within(card).getByText('Incumbent')).toBeVisible();
    expect(within(card).getByText('Called by Call the Map')).toBeVisible();
    await user.click(within(card).getByRole('link', { name: 'Florida' }));
    const detail = await screen.findByRole('table', { name: 'Florida Senate candidate results' });
    expect(detail.querySelectorAll('tbody tr')).toHaveLength(8);
    expect(within(detail).getByRole('link', { name: 'Small independent' })).toBeVisible();
    expect(within(detail).getByRole('link', { name: 'Small Green' })).toBeVisible();
    expect(body).toEqual(before);
  });

  it.each([
    { total: 100_000, votes: 99, grouped: true },
    { total: 100_000, votes: 100, grouped: false },
    { total: 10_000_000, votes: 999, grouped: true },
    { total: 10_000_000, votes: 1000, grouped: false },
  ])('uses the shared strict cutoff for $votes of $total votes in Senate tables', ({ total, votes, grouped }) => {
    const source = snapshot().races[0];
    source.total_votes = total;
    source.candidates = [
      { ...source.candidates[0], votes: total - votes, share_pct: (total - votes) / total * 100 },
      { name: 'Third party', party: 'L', votes, share_pct: Number((votes / total * 100).toFixed(2)), outcome: '' },
    ];
    expect(senateDisplayCandidates(source).map(candidate => candidate.name)).toEqual(['Candidate R', grouped ? 'Other' : 'Third party']);
  });

  it('filters by URL state and status with a fixed 2026 data request', async () => {
    const user = userEvent.setup();
    stubResults(vi.fn().mockResolvedValue(response()));
    open('/senate/2026/results?state_code=WY&status=final&year=2008');
    await screen.findByRole('article', { name: 'Wyoming' });
    expect(screen.queryByRole('article', { name: 'Florida' })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox', { name: 'State' }), 'FL');
    expect(screen.getByRole('heading', { name: 'No matching results' })).toBeVisible();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Result status' }), 'called');
    expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
  });

  it('explains missing-state selections and invalid filters without treating them as zero', async () => {
    stubResults(vi.fn().mockResolvedValue(response()));
    open('/senate/2026/results?state_code=OH');
    expect(await screen.findByRole('heading', { name: 'No matching results' })).toBeVisible();
    expect(screen.getByText(/No cached contest matches these filters/)).toHaveTextContent('Missing returns do not mean zero votes');
  });

  it('clears invalid deep-link filters', async () => {
    const user = userEvent.setup();
    stubResults(vi.fn().mockResolvedValue(response()));
    open('/senate/2026/results?state_code=ZZ&status=projected');
    await screen.findByRole('heading', { name: 'Review your filters' });
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
  });

  it('labels delayed updates while retaining the valid cached counts', async () => {
    stubResults(vi.fn().mockResolvedValue(response({ ...snapshot(), stale: true, refresh_failed: true })));
    open();
    expect(await screen.findByRole('heading', { name: 'Daily update delayed' })).toBeVisible();
    expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
    expect(screen.getByText(/The latest source refresh failed/)).toBeVisible();
  });

  it('shows explicit API failure and retries', async () => {
    const user = userEvent.setup();
    stubResults(vi.fn().mockResolvedValueOnce({ ok: false, status: 503 }).mockResolvedValue(response()));
    open();
    await screen.findByRole('heading', { name: 'Results unavailable' });
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('article', { name: 'Florida' })).toBeVisible();
  });

  it('aborts requests when leaving the page', async () => {
    const fetch = vi.fn().mockImplementation(() => new Promise(() => {})); stubResults(fetch);
    const view = open();
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const signal = fetch.mock.calls[0][1].signal as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });

  it('polls the local cache and retains loaded data on a later API failure', async () => {
    vi.useFakeTimers();
    try {
      const fetch = vi.fn().mockResolvedValueOnce(response()).mockResolvedValue({ ok: false, status: 503 });
      stubResults(fetch);
      open();
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
      await act(async () => { await vi.advanceTimersByTimeAsync(5 * 60 * 1000); });
      expect(fetch).toHaveBeenCalledTimes(2);
      expect(screen.getByRole('heading', { name: 'Showing the last loaded results' })).toBeVisible();
      expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
    } finally { vi.useRealTimers(); }
  });

  it('renders a zero count with an unknown share and refuses unsafe source links', async () => {
    const body = snapshot();
    body.races[0].status = 'counting';
    body.races[0].total_votes = 0;
    body.races[0].source_url = 'javascript:alert(1)';
    body.races[0].candidates = body.races[0].candidates.map(candidate => ({ ...candidate, votes: 0, share_pct: null, outcome: '' }));
    stubResults(vi.fn().mockResolvedValue(response(body)));
    open();
    const race = await screen.findByRole('article', { name: 'Florida' });
    expect(within(race).getByText('0 votes counted')).toBeVisible();
    expect(within(race).queryByRole('link', { name: 'civicAPI' })).not.toBeInTheDocument();
    expect(within(race).queryByText('0.00%')).not.toBeInTheDocument();
  });

  it.each(['wrong year', 'bad votes', 'mismatched total', 'unknown status'])('rejects a malformed response: %s', async failure => {
    const body = snapshot();
    if (failure === 'wrong year') body.year = 2024;
    if (failure === 'bad votes') body.races[0].candidates[0].votes = -1;
    if (failure === 'mismatched total') body.races[0].total_votes = 999;
    if (failure === 'unknown status') body.races[0].status = 'projected' as SenateRace['status'];
    stubResults(vi.fn().mockResolvedValue(response(body)));
    await expect(fetchSenateResults(new AbortController().signal)).rejects.toThrow('Unexpected Senate results response');
  });
});
