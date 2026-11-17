import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { fetchHouseResults } from '../house';
import { snapshot } from './houseFixtures';
import { boundarySnapshot } from './houseMapFixtures';
import { portrait } from './portraitFixtures';
import { HouseRaceCard } from '../HousePage';

const response = (body = snapshot()) => ({ ok: true, json: async () => body });
function open(path = '/house/2026/results?view=grid') { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); }

describe('2026 House results', () => {
  it('uses reviewed table thumbnails for named candidates and preserves initials if an image fails', async () => {
    const body = snapshot();
    body.races[0].candidates[0].portrait = portrait;
    body.races[0].candidates[2].portrait = portrait;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    open('/house/2026/results?view=grid');
    const card = await screen.findByRole('article', { name: 'California District 1' });
    const images = card.querySelectorAll('tbody img');
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute('src', portrait.url);
    expect(images[0]).toHaveAttribute('title', expect.stringContaining(portrait.credit));
    fireEvent.error(images[0]);
    expect(card.querySelectorAll('tbody img')).toHaveLength(0);
    expect(card.querySelector('.senate-candidate-avatar')).toHaveTextContent('CD');
  });
  it('links named candidates and marks incumbents in compact and complete tables without linking categories', () => {
    const race = snapshot().races[0];
    const view = render(<MemoryRouter><HouseRaceCard race={race} /></MemoryRouter>);
    expect(screen.getByRole('link', { name: 'Candidate D' })).toHaveAttribute('href', expect.stringContaining('/candidates/11111111-1111-4111-8111-111111111111'));
    expect(screen.getByText('Incumbent')).toBeVisible();
    expect(screen.queryByRole('link', { name: 'Incumbent' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Write-in' })).not.toBeInTheDocument();
    view.rerender(<MemoryRouter><HouseRaceCard race={race} complete highlightedCandidacyId={race.candidates[0].candidacy_id!} /></MemoryRouter>);
    expect(screen.getByRole('link', { name: 'Candidate D' }).closest('tr')).toHaveClass('profile-current-candidate');
  });
  it('toggles grid/map through the URL, preserves selections and retains the view when clearing filters', async () => {
    const user = userEvent.setup();
    const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true,
      json: async () => url.endsWith('/boundaries') ? boundarySnapshot() : snapshot() }));
    vi.stubGlobal('fetch', fetch);
    open('/house/2026/results?state_code=CA&district=CA-01');
    const map = await screen.findByRole('group', { name: '2026 House results map' }, { timeout: 5000 });
    expect(map.querySelectorAll('path[data-geoid]')).toHaveLength(52);
    expect(screen.getByRole('button', { name: /^Map$/ })).toHaveAttribute('aria-pressed', 'true');
    expect(within(screen.getByRole('group', { name: 'Results view' })).getAllByRole('button').map(button => button.textContent)).toEqual(['Map', 'Tile grid']);
    const totals = screen.getByRole('img', { name: /433 uncalled/ }).getAttribute('aria-label');
    await user.click(screen.getByRole('button', { name: 'Tile grid' }));
    expect(screen.getByRole('button', { name: /^California District 1:/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('group', { name: '2026 House results map' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Map$/ }));
    await screen.findByRole('group', { name: '2026 House results map' });
    await user.click(screen.getByRole('button', { name: 'Show all districts' }));
    expect(screen.getByRole('button', { name: /^Map$/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('group', { name: '2026 House results map' }).querySelectorAll('path[data-geoid]')).toHaveLength(436);
    expect(screen.getByRole('img', { name: /433 uncalled/ })).toHaveAttribute('aria-label', totals);
    expect(screen.getAllByRole('article')).toHaveLength(3);
  });
  it('opens the working House header link and shows the complete counts and attribution', async () => {
    const user = userEvent.setup();
    const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true,
      json: async () => url.endsWith('/boundaries') ? boundarySnapshot() : snapshot() }));
    vi.stubGlobal('fetch', fetch);
    open('/');
    await user.click(screen.getByRole('button', { name: 'House' }));
    const link = screen.getByRole('link', { name: '2026 Election Results' });
    expect(link).toHaveAttribute('href', '/house/2026/results');
    expect(within(link).queryByText('Coming soon')).not.toBeInTheDocument();
    await user.click(link);
    expect(await screen.findByRole('article', { name: 'California District 1' })).toBeVisible();
    expect(document.title).toBe('2026 House of Representatives Election Results | Electoral Atlas');
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/house/2026/results');
    expect(screen.getByRole('article', { name: 'Florida District 10' })).toHaveTextContent('Vote counts unavailable');
    expect(screen.getByRole('article', { name: 'Wyoming at-large' })).toHaveTextContent('Certified · per source');
    expect(screen.getByRole('article', { name: 'California District 1' })).not.toHaveTextContent('Projected winner');
    expect(screen.getByRole('link', { name: 'CC BY 4.0' })).toBeVisible();
    expect(await screen.findByRole('group', { name: '2026 House results map' }, { timeout: 5000 })).toBeVisible();
    expect(screen.getByRole('button', { name: /^Map$/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('selects districts, keeps national totals during filtering, and clears filters', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response()));
    const user = userEvent.setup(); open('/house/2026/results?view=grid&status=counting');
    const bar = await screen.findByRole('img', { name: /433 uncalled/ });
    const accounting = bar.getAttribute('aria-label');
    await user.click(screen.getByRole('button', { name: /^Wyoming at-large:/ }));
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(screen.getByRole('article', { name: 'Wyoming at-large' })).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Result status' })).toHaveValue('');
    expect(screen.getByRole('region', { name: '2026 House district selector' }).querySelectorAll('button')).toHaveLength(1);
    expect(bar).toHaveAttribute('aria-label', accounting);
    await user.click(screen.getByRole('button', { name: 'Show all districts' }));
    expect(screen.getAllByRole('article')).toHaveLength(3);
    fireEvent.change(screen.getByRole('combobox', { name: 'Result status' }), { target: { value: 'counting' } });
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });

  it('opens an independent district page with every source row', async () => {
    const body = snapshot();
    body.races[0].candidates.push({ name: 'Tiny candidate', party: 'O', votes: 0, share_pct: 0, outcome: '', source_row_number: 5 });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    open('/house/2026/races/CA-01');
    const card = await screen.findByRole('article', { name: 'California District 1' });
    expect(within(card).getByText('Tiny candidate')).toBeVisible();
    expect(within(card).getByText('Write-in')).toBeVisible();
    expect(within(card).getAllByRole('row')).toHaveLength(5);
    expect(screen.getByRole('link', { name: 'All House results' })).toHaveAttribute('href', '/house/2026/results');
  });

  it('handles stale snapshots, bad filters, missing districts and retry', async () => {
    const user = userEvent.setup();
    const body = snapshot(); body.stale = true;
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(response(body)));
    open('/house/2026/results?view=grid&district=bad');
    expect(await screen.findByRole('heading', { name: 'Results unavailable' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Daily update delayed' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Review your filters' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getAllByRole('article')).toHaveLength(3);
    expect(screen.getByRole('heading', { name: 'Partial source coverage' })).toBeVisible();
  });

  it('polls the local API for daily updates on an open page', async () => {
    vi.useFakeTimers();
    try {
      const fetch = vi.fn().mockResolvedValue(response()); vi.stubGlobal('fetch', fetch);
      open();
      await act(async () => { await Promise.resolve(); });
      expect(fetch).toHaveBeenCalledTimes(1);
      await act(async () => { await vi.advanceTimersByTimeAsync(5 * 60 * 1000); });
      expect(fetch).toHaveBeenCalledTimes(2);
    } finally { vi.useRealTimers(); }
  });

  it.each(['reconciliation', 'duplicates', 'missing_counts', 'false_control', 'winner', 'year'])('rejects invalid API data: %s', async failure => {
    const body = snapshot();
    if (failure === 'reconciliation') body.races[0].total_votes = 101;
    if (failure === 'duplicates') body.races.push(body.races[0]);
    if (failure === 'missing_counts') body.races[2].candidates[0].votes = 0;
    if (failure === 'false_control') body.control.called.D = 220;
    if (failure === 'winner') body.races[0].candidates[0].outcome = 'won';
    if (failure === 'year') body.year = 2024;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(body)));
    await expect(fetchHouseResults(new AbortController().signal)).rejects.toThrow();
  });
});
