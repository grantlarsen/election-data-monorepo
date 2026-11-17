import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SenateMap, { senateRaceColor } from '../SenateMap';
import type { SenateRace, SenateResults } from '../senate';
import states from '../geography/data/states.json';
import { indeterminateColor, partyPalette, tieColor } from '../map/electionColors';
import { SenatePopover } from '../SenatePopover';
import { portrait } from './portraitFixtures';

const race: SenateRace = { id: 'SEN-FL', state_code: 'FL', state_name: 'Florida', seat_class: 3, special: true,
  status: 'called', total_votes: 100, summary_status: 'available', leader: 'Candidate R', margin_votes: 20, margin_pct: 20,
  candidates: [
    { name: 'Candidate R', party: 'R', votes: 60, share_pct: 60, outcome: 'won', candidacy_id: 'source-one', incumbent: true },
    { name: 'Candidate D', party: 'D', votes: 40, share_pct: 40, outcome: '', candidacy_id: 'source-two' },
  ], count_updated_at: null, source_read_at: '2026-11-16T13:00:00Z', called_at: null,
  source: 'civicAPI', source_url: 'https://civicapi.org/race/example', page_url: 'https://www.callthemap.com/results/senate/fl' };
const data = { races: [race], missing_states: ['OH'] } as SenateResults;
const props = { data, selectedState: '', onSelect: vi.fn(), onClear: vi.fn() };

describe('Senate state map', () => {
  it('fits an individual race to its own state and retains popover and zoom interactions', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => states }));
    render(<SenateMap {...props} selectedState="FL" raceState="FL" />);
    const map = await screen.findByRole('group', { name: 'Florida 2026 Senate race map' });
    expect(map.querySelectorAll('path[data-geoid]')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Show all states' })).not.toBeInTheDocument();
    const florida = within(map).getByRole('button', { name: /^Florida:/ });
    fireEvent.focus(florida);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Candidate R');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toBeEnabled();
  });
  it('replaces a candidate initial avatar with a sourced thumbnail while retaining links and badges', () => {
    const { container } = render(<SenatePopover race={{ ...race, candidates: [{ ...race.candidates[0], portrait }, race.candidates[1]] }} name="Florida" missing={false} />);
    const image = container.querySelector('.popover-avatar img');
    expect(image).toHaveAttribute('src', portrait.url);
    expect(container.querySelectorAll('.popover-avatar img')).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Candidate R' })).toBeVisible();
    expect(screen.getByText('Projected winner')).toBeVisible();
    expect(screen.getByText('Incumbent')).toBeVisible();
  });
  it('groups small independent and third-party candidates while keeping candidates at the cutoff linked', () => {
    render(<SenatePopover race={{ ...race, total_votes: 100_000, candidates: [
      { ...race.candidates[0], votes: 60_000, share_pct: 60 },
      { ...race.candidates[1], votes: 39_850, share_pct: 39.85 },
      { name: 'Small independent', party: 'I', votes: 49, share_pct: 0.049, outcome: '', candidacy_id: 'small-one' },
      { name: 'Small Green', party: 'G', votes: 1, share_pct: 0.001, outcome: '', candidacy_id: 'small-two' },
      { name: 'At cutoff', party: 'L', votes: 100, share_pct: 0.1, outcome: '', candidacy_id: 'at-cutoff' },
    ] }} name="Florida" missing={false} />);
    expect(screen.queryByText('Small independent')).not.toBeInTheDocument();
    expect(screen.queryByText('Small Green')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'At cutoff' })).toHaveAttribute('href', expect.stringContaining('/candidates/at-cutoff?'));
    const other = screen.getByText('Other').closest('.popover-candidate') as HTMLElement;
    expect(within(other).getByText('50')).toBeVisible();
    expect(within(other).getByText('0.05%')).toBeVisible();
    expect(within(other).queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('Incumbent')).toBeVisible();
    expect(screen.getByText('Projected winner')).toBeVisible();
  });
  it.each(['counting', 'called', 'final'] as const)('uses source outcomes for winner badges in %s races', status => {
    const { container } = render(<SenatePopover race={{ ...race, status }} name="Florida" missing={false} />);
    expect(container.querySelector('.popover-leader')).not.toBeInTheDocument();
    expect(screen.queryByText(/Leading here:/)).not.toBeInTheDocument();
    const badges = container.querySelectorAll('.winner-marker');
    expect(badges).toHaveLength(status === 'counting' ? 0 : 1);
    if (status !== 'counting') expect(badges[0]).toHaveTextContent(status === 'final' ? 'Winner' : 'Projected winner');
    expect(screen.getByText('Incumbent')).toBeVisible();
  });
  it('matches all 51 outlines and separates missing returns from no election', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => states }));
    const { container } = render(<SenateMap {...props} />);
    const map = await screen.findByRole('group', { name: '2026 Senate results map' });
    expect(screen.queryByRole('heading', { name: 'Senate results map' })).not.toBeInTheDocument();
    expect(screen.queryByText('Hover or focus a state for counts. Select a state to view its results below.')).not.toBeInTheDocument();
    expect(container.querySelectorAll('path[data-geoid]')).toHaveLength(51);
    const florida = within(map).getByRole('button', { name: /^Florida:/ });
    expect(florida).toHaveAttribute('data-geoid', '12');
    expect(florida).toHaveAttribute('fill', partyPalette.Republican);
    const ohio = within(map).getByRole('button', { name: 'Ohio: Returns unavailable' });
    const california = within(map).getByRole('img', { name: 'California: No Senate election in 2026' });
    expect(ohio.getAttribute('fill')).not.toBe(california.getAttribute('fill'));
    fireEvent.mouseEnter(florida, { clientX: 200, clientY: 180 });
    expect(await screen.findByRole('tooltip')).toHaveTextContent('special election · Media call · uncertified');
    expect(within(screen.getByRole('tooltip')).getByText('60.00%')).toBeVisible();
    expect(screen.getByRole('tooltip').querySelector('.election-popover')).toBeInTheDocument();
    expect(screen.getByRole('tooltip').querySelector('.popover-share > span')).toHaveStyle({ width: '60%' });
    expect(within(screen.getByRole('tooltip')).getByText('20.00%')).toBeVisible();
    expect(within(screen.getByRole('tooltip')).getByText('Incumbent')).toBeVisible();
    expect(within(screen.getByRole('tooltip')).getByRole('link', { name: 'Florida' })).toHaveAttribute('href', '/senate/2026/races/FL');
    within(screen.getByRole('tooltip')).getAllByRole('link', { name: 'Candidate R' }).forEach(link => expect(link.getAttribute('href')).toContain('/candidates/source-one'));
    expect(screen.getByRole('tooltip')).toHaveTextContent('civicAPI via Call the Map');
    fireEvent.click(florida);
    expect(props.onSelect).toHaveBeenCalledWith('FL');
    fireEvent.keyDown(ohio, { key: 'Enter' });
    expect(props.onSelect).toHaveBeenCalledWith('OH');
    expect(screen.getByRole('link', { name: 'Census 2024 state outlines' })).toHaveAttribute('href', states.source.documentation_url);
    expect(screen.getByText(/not 2026 election-day boundary certification/)).toBeVisible();
  });

  it('does not turn ties or zero counts into a party lead', () => {
    expect(senateRaceColor({ ...race, total_votes: 0 })).toBe(indeterminateColor);
    expect(senateRaceColor({ ...race, candidates: race.candidates.map(candidate => ({ ...candidate, votes: 50 })) })).toBe(tieColor);
    expect(senateRaceColor({ ...race, candidates: [{ ...race.candidates[0], party: 'I' }] })).toBe(partyPalette['Other / independent']);
  });

  it('offers map retry while leaving state results usable after an outline failure', async () => {
    const fetch = vi.fn().mockResolvedValueOnce({ ok: false }).mockResolvedValue({ ok: true, json: async () => states });
    vi.stubGlobal('fetch', fetch);
    render(<SenateMap {...props} />);
    expect(await screen.findByText(/State results remain available below/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Retry map' }));
    expect(await screen.findByRole('group', { name: '2026 Senate results map' })).toBeVisible();
  });
});
