import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { fetchGovernorResults, governorStates } from '../governor';
import type { GovernorRace, GovernorResults } from '../governor';
import states from '../geography/data/states.json';
import { portrait } from './portraitFixtures';

function snapshot(): GovernorResults {
  const race: GovernorRace = { id: 'GOV-FL', state_code: 'FL', state_name: 'Florida', status: 'called', total_votes: 100,
    candidates: [
      { name: 'Candidate R', party: 'R', votes: 60, share_pct: 60, outcome: 'won', source_row_number: 1 },
      { name: 'Candidate D', party: 'D', votes: 35, share_pct: 35, outcome: '', source_row_number: 2 },
      { name: 'Write-in', party: 'O', votes: 5, share_pct: 5, outcome: '', source_row_number: 3 },
    ], count_updated_at: '2026-11-16T12:00:00Z', source_read_at: '2026-11-16T13:00:00Z', called_at: null,
    source: 'civicAPI', source_url: 'https://civicapi.org/race/example', page_url: 'https://www.callthemap.com/results/governor/fl' };
  return { year: 2026, election_date: '2026-11-03', expected_contests: 36,
    races: [race, { ...race, id: 'GOV-WY', state_code: 'WY', state_name: 'Wyoming', status: 'final',
      candidates: race.candidates.map(c => ({ ...c, name: `WY ${c.name}` })) }],
    missing_states: governorStates.filter(s => s !== 'FL' && s !== 'WY'),
    checked_at: '2026-11-17T12:00:00Z', retrieved_at: '2026-11-17T12:00:00Z', published_at: '2026-11-16T15:00:00Z',
    next_refresh_at: '2026-11-18T12:00:00Z', stale: false, refresh_failed: false, sha256: 'a'.repeat(64),
    source_url: 'https://www.callthemap.com/results/data/2026/races.csv', manifest_url: 'https://www.callthemap.com/results/data/2026/manifest.json' };
}
const response = (body = snapshot()) => ({ ok: true, json: async () => body });
function stubResults(resultFetch = vi.fn().mockResolvedValue(response())) {
  vi.stubGlobal('fetch', (url: string, options?: RequestInit) => String(url).includes('states.json')
    ? Promise.resolve({ ok: true, json: async () => states }) : resultFetch(url, options));
  return resultFetch;
}
function open(path = '/governor/2026/results') {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

describe('Governor results', () => {
  it('uses sourced thumbnails in tables and popovers and keeps aggregate rows photo-free', async () => {
    const body = snapshot();
    body.races[0].candidates[0].portrait = portrait;
    body.races[0].candidates[2].portrait = portrait;
    body.races[0].candidates[2].kind = 'aggregate';
    stubResults(vi.fn().mockResolvedValue(response(body))); open();
    const table = await screen.findByRole('table', { name: 'Florida Governor candidate results' });
    expect(table.querySelectorAll('img')).toHaveLength(1);
    const image = table.querySelector('img')!;
    expect(image).toHaveAttribute('src', portrait.url);
    expect(image).toHaveAttribute('loading', 'lazy');
    expect(image).toHaveAttribute('title', expect.stringContaining(portrait.credit));
    fireEvent.error(image);
    expect(table.querySelectorAll('img')).toHaveLength(0);
    expect(within(table).getByText('Candidate R').closest('th')?.querySelector('.senate-party-dot')).toBeVisible();
    const map = await screen.findByRole('group', { name: '2026 Governor results map' });
    fireEvent.mouseEnter(within(map).getByRole('button', { name: /^Florida:/ }));
    const tooltip = await screen.findByRole('tooltip');
    expect(tooltip.querySelectorAll('img')).toHaveLength(1);
    expect(tooltip.querySelector('img')).toHaveAttribute('src', portrait.url);
    fireEvent.error(tooltip.querySelector('img')!);
    expect(tooltip.querySelectorAll('img')).toHaveLength(0);
    expect(within(tooltip).getByText('CR')).toBeVisible();
  });

  it('links named candidates and marks the same incumbent in tables and popovers', async () => {
    const body = snapshot();
    const id = '11111111-1111-4111-8111-111111111111';
    Object.assign(body.races[0].candidates[0], { candidacy_id: id, incumbent: true,
      incumbent_evidence: { url: 'https://www.nga.org/governors/elections/', as_of: '2026-11-03', reviewed_at: '2026-11-17' } });
    body.races[0].candidates[2].kind = 'aggregate';
    // Anonymous source categories never receive links, even if an erroneous ID arrives.
    body.races[0].candidates[2].candidacy_id = id;
    stubResults(vi.fn().mockResolvedValue(response(body))); open();
    const table = await screen.findByRole('table', { name: 'Florida Governor candidate results' });
    expect(within(table).getByRole('link', { name: 'Candidate R' })).toHaveAttribute('href', `/candidates/${id}`);
    expect(within(table).getByText('Incumbent')).toHaveAttribute('title', 'Incumbent Governor as of 2026-11-03');
    expect(within(table).queryByRole('link', { name: 'Write-in' })).not.toBeInTheDocument();
    const map = await screen.findByRole('group', { name: '2026 Governor results map' });
    fireEvent.mouseEnter(within(map).getByRole('button', { name: /^Florida:/ }));
    const tooltip = await screen.findByRole('tooltip');
    expect(within(tooltip).getByRole('link', { name: 'Candidate R' })).toHaveAttribute('href', `/candidates/${id}`);
    expect(within(tooltip).getByText('Incumbent')).toBeVisible();
    expect(within(tooltip).queryByRole('link', { name: 'Write-in' })).not.toBeInTheDocument();
  });

  it('hatches called party flips and explains the previous-election comparison', async () => {
    const body = snapshot();
    body.races[0].flipped = true;
    body.races[0].previous_election = { year: 2022, party: 'D', winner_name: 'Previous Governor',
      source_url: 'https://www.nga.org/governors/elections/', source_sha256: 'b'.repeat(64), reviewed_at: '2026-11-17' };
    body.races[1].flipped = false;
    stubResults(vi.fn().mockResolvedValue(response(body))); open();
    const map = await screen.findByRole('group', { name: '2026 Governor results map' });
    const florida = within(map).getByRole('button', { name: /^Florida:/ });
    expect(florida.getAttribute('fill')).toMatch(/^url\(#state-flip-/);
    const patternId = florida.getAttribute('fill')!.slice(5, -1);
    const pattern = document.getElementById(patternId)!;
    expect(pattern.tagName.toLowerCase()).toBe('pattern');
    expect(pattern.querySelector('rect')).toHaveAttribute('fill', '#bd5548');
    expect(within(map).getByRole('button', { name: /^Wyoming:/ }).getAttribute('fill')).not.toMatch(/^url/);
    expect(florida).toHaveAccessibleName(/party flipped from the previous election/);
    expect(screen.getByText('Party flipped from previous election (called or certified)')).toBeVisible();
    expect(screen.getByText(/Party flip: Democratic/)).toBeVisible();
    fireEvent.mouseEnter(florida);
    expect(within(await screen.findByRole('tooltip')).getByText(/Party flipped from Democratic \(2022\)/)).toBeVisible();
  });

  it('keeps counting leads unshaded even with a previous party available', async () => {
    const body = snapshot(); body.races[0].status = 'counting';
    body.races[0].candidates[0].outcome = 'leads'; body.races[0].flipped = null;
    body.races[0].previous_election = { year: 2022, party: 'D', winner_name: 'Previous Governor',
      source_url: 'https://www.nga.org/governors/elections/', source_sha256: 'b'.repeat(64), reviewed_at: '2026-11-17' };
    stubResults(vi.fn().mockResolvedValue(response(body))); open();
    const map = await screen.findByRole('group', { name: '2026 Governor results map' });
    expect(within(map).getByRole('button', { name: /^Florida:/ }).getAttribute('fill')).not.toMatch(/^url/);
    expect(screen.queryByText(/Party flip:/)).not.toBeInTheDocument();
  });

  it('opens the real results page from the Governor header', async () => {
    const user = userEvent.setup();
    const fetch = stubResults(); open('/');
    await user.click(screen.getByRole('button', { name: 'Governor' }));
    const link = screen.getByRole('link', { name: '2026 Election Results' });
    expect(link).toHaveAttribute('href', '/governor/2026/results');
    expect(within(link).queryByText('Coming soon')).not.toBeInTheDocument();
    await user.click(link);
    expect(await screen.findByRole('heading', { name: 'Florida' })).toBeVisible();
    expect(document.title).toBe('2026 Governor Election Results | Electoral Atlas');
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/governor/2026/results');
  });

  it('retains counts, evidence, status distinctions and snapshot provenance', async () => {
    stubResults(); open();
    const florida = await screen.findByRole('article', { name: 'Florida' });
    expect(within(florida).getByText('Media call · uncertified')).toBeVisible();
    expect(within(florida).getByRole('table', { name: 'Florida Governor candidate results' })).toBeVisible();
    expect(within(florida).getByText('60.00%')).toBeVisible();
    expect(within(florida).getByText('100 votes counted')).toBeVisible();
    expect(within(florida).getByText(/Source read:/)).toBeVisible();
    expect(within(florida).getByRole('link', { name: 'civicAPI' })).toHaveAttribute('href', 'https://civicapi.org/race/example');
    expect(within(screen.getByRole('article', { name: 'Wyoming' })).getByText('Certified · per source')).toBeVisible();
    expect(screen.getByText(/Territorial elections are outside/)).toBeVisible();
    await userEvent.click(screen.getByText('Snapshot provenance'));
    expect(screen.getByText('a'.repeat(64))).toBeVisible();
  });

  it('filters by URL and map selection without changing national win accounting', async () => {
    stubResults(); open('/governor/2026/results?state_code=WY&status=final');
    const map = await screen.findByRole('group', { name: '2026 Governor results map' });
    expect(screen.getByRole('article', { name: 'Wyoming' })).toBeVisible();
    expect(screen.queryByRole('article', { name: 'Florida' })).not.toBeInTheDocument();
    const summary = screen.getByRole('img', { name: /0 Democratic wins, 2 Republican wins/ });
    expect(screen.queryByRole('button', { name: 'Show all states' })).not.toBeInTheDocument();
    const filters = screen.getByRole('combobox', { name: 'State' }).closest('.governor-filters')!;
    expect(within(filters as HTMLElement).getByRole('button', { name: 'Clear filters' })).toBeVisible();
    const florida = within(map).getByRole('button', { name: /^Florida:/ });
    fireEvent.keyDown(florida, { key: 'Enter' });
    expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Result status' })).toHaveValue('');
    expect(summary).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getAllByRole('article', { name: /Florida|Wyoming/ })).toHaveLength(2);
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'State' })).toHaveValue('');
    expect(screen.getByRole('combobox', { name: 'Result status' })).toHaveValue('');
    expect(within(map).getByRole('img', { name: /New Jersey: No Governor election/ })).toBeVisible();
  });

  it('shows Clear filters for a status-only filter and removes it after clearing', async () => {
    stubResults(); open('/governor/2026/results?status=final');
    expect(await screen.findByRole('article', { name: 'Wyoming' })).toBeVisible();
    expect(screen.queryByRole('article', { name: 'Florida' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Show all states' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Result status' })).toHaveValue('');
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument();
  });

  it('keeps counting leads out of win totals and exposes stale and missing coverage', async () => {
    const body = snapshot(); body.stale = true; body.refresh_failed = true;
    body.races[0].status = 'counting'; body.races[0].candidates[0].outcome = 'leads';
    stubResults(vi.fn().mockResolvedValue(response(body))); open();
    expect(await screen.findByRole('heading', { name: 'Daily update delayed' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Partial source coverage' })).toBeVisible();
    expect(screen.getByRole('img', { name: /0 Democratic wins, 1 Republican wins, 0 other wins, 35 uncalled/ })).toBeVisible();
  });

  it('keeps null vote counts unavailable while retaining a source winner', async () => {
    const body = snapshot(); body.races[0].total_votes = null;
    body.races[0].candidates.forEach(c => { c.votes = null; c.share_pct = null; });
    stubResults(vi.fn().mockResolvedValue(response(body))); open();
    const florida = await screen.findByRole('article', { name: 'Florida' });
    expect(within(florida).getByText('Vote counts unavailable')).toBeVisible();
    expect(within(florida).getAllByText('Unavailable')).toHaveLength(3);
    expect(screen.getByRole('img', { name: /2 Republican wins/ })).toBeVisible();
    const map = await screen.findByRole('group', { name: '2026 Governor results map' });
    fireEvent.mouseEnter(within(map).getByRole('button', { name: /^Florida:/ }));
    expect(await screen.findByRole('heading', { name: 'Florida', level: 3 })).toBeVisible();
    expect(screen.getAllByText('Candidate R').length).toBeGreaterThan(1);
  });

  it('loads a full state race directly and preserves every candidate line', async () => {
    const body = snapshot();
    body.races[0].candidates[0].votes = 59; body.races[0].candidates[0].share_pct = 59;
    body.races[0].candidates.push({ name: 'Small candidate', party: 'L', votes: 1, share_pct: 1, outcome: '', source_row_number: 4 });
    stubResults(vi.fn().mockResolvedValue(response(body))); open('/governor/2026/races/FL');
    expect(await screen.findByRole('heading', { name: 'Florida — 2026 Governor Election' })).toBeVisible();
    expect(screen.getByText('Small candidate')).toBeVisible();
    expect(screen.getByRole('table').querySelectorAll('tbody tr')).toHaveLength(4);
    expect(screen.queryByRole('article', { name: 'Wyoming' })).not.toBeInTheDocument();
  });

  it('shows invalid filters and missing cached races explicitly', async () => {
    stubResults(); open('/governor/2026/results?state_code=NJ');
    expect(await screen.findByRole('heading', { name: 'Review your filters' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'State' }), 'AK');
    expect(screen.getByRole('heading', { name: 'No matching results' })).toBeVisible();
  });

  it('retries unavailable results', async () => {
    const fetch = stubResults(vi.fn().mockResolvedValueOnce({ ok: false, status: 503 }).mockResolvedValue(response()));
    open(); expect(await screen.findByRole('heading', { name: 'Results unavailable' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('article', { name: 'Florida' })).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('polls the local API and preserves loaded counts when that request fails', async () => {
    const fetch = stubResults(); vi.useFakeTimers();
    try {
      open(); await act(async () => { await Promise.resolve(); });
      fetch.mockRejectedValue(new Error('offline'));
      await act(async () => { await vi.advanceTimersByTimeAsync(5 * 60 * 1000); });
      expect(fetch).toHaveBeenCalledTimes(2);
      expect(screen.getByRole('heading', { name: 'Showing the last loaded results' })).toBeVisible();
      expect(screen.getByRole('article', { name: 'Florida' })).toBeVisible();
    } finally { vi.useRealTimers(); }
  });

  it.each(['duplicate', 'wrong_scope', 'bad_total', 'bad_winner', 'bad_timestamp', 'missing_counts'])('rejects malformed API data: %s', async fault => {
    const body = snapshot();
    if (fault === 'duplicate') body.missing_states[0] = 'FL';
    if (fault === 'wrong_scope') body.missing_states[0] = 'NJ';
    if (fault === 'bad_total') body.races[0].total_votes = 101;
    if (fault === 'bad_winner') body.races[0].candidates[0].outcome = '';
    if (fault === 'bad_timestamp') body.checked_at = 'invalid';
    if (fault === 'missing_counts') body.races[0].candidates[0].votes = null;
    stubResults(vi.fn().mockResolvedValue(response(body)));
    await expect(fetchGovernorResults(new AbortController().signal)).rejects.toThrow('Unexpected Governor results response');
  });
});
