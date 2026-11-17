import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { HousePopover } from '../HousePopover';
import { snapshot } from './houseFixtures';
import { portrait } from './portraitFixtures';

describe('shared House map popover', () => {
  it('uses reviewed headshots on named rows and keeps aggregate rows anonymous', () => {
    const race = snapshot().races[0];
    race.candidates[0].portrait = portrait;
    race.candidates[2].portrait = portrait;
    const { container } = render(<HousePopover race={race} name="CA-01" dc={false} />);
    expect(container.querySelectorAll('.popover-avatar img')).toHaveLength(1);
    expect(container.querySelector('.popover-avatar img')).toHaveAttribute('src', portrait.url);
  });
  it('uses the shared header, avatars, party colors, share bars and source footer', () => {
    const { container } = render(<MemoryRouter><HousePopover race={snapshot().races[0]} name="CA-01" dc={false} /></MemoryRouter>);
    expect(container.querySelector('.election-popover .popover-head')).toBeVisible();
    expect(container.querySelector('table')).toBeNull();
    expect(container.querySelector('.popover-leader')).toBeNull();
    expect(screen.getByRole('link', { name: 'California District 1' })).toHaveAttribute('href', '/house/2026/races/CA-01');
    expect(screen.getByRole('link', { name: 'View all district results' })).toHaveAttribute('href', '/house/2026/races/CA-01');
    const democrat = screen.getByText('Candidate D').closest('.popover-candidate') as HTMLElement;
    expect(democrat.querySelector('.popover-avatar')).toBeVisible();
    expect(democrat).toHaveStyle({ '--candidate-color': '#3276ac' });
    expect(within(democrat).getByText('60.00%')).toBeVisible();
    expect(democrat.querySelector('.popover-share span')).toHaveStyle({ width: '60%' });
    expect(screen.getByText('Write-in').closest('.popover-candidate')).toHaveTextContent('aggregate vote category');
    expect(screen.getByRole('link', { name: 'Candidate D' })).toHaveAttribute('href', expect.stringContaining('/candidates/11111111-1111-4111-8111-111111111111'));
    expect(screen.getByText('Incumbent')).toBeVisible();
    expect(screen.queryByRole('link', { name: 'Incumbent' })).not.toBeInTheDocument();
    expect(screen.getByText('100 reported votes')).toBeVisible();
    expect(screen.getByText('civicAPI via Call the Map')).toBeVisible();
  });

  it.each(['counting', 'called', 'final'] as const)('preserves source outcome badges for %s races', status => {
    const race = structuredClone(snapshot().races[0]);
    race.status = status;
    race.candidates[0].outcome = status === 'counting' ? 'leads' : 'won';
    const { container } = render(<HousePopover race={race} name="CA-01" dc={false} />);
    const badge = container.querySelector('.winner-marker');
    if (status === 'counting') expect(badge).toBeNull();
    else expect(badge).toHaveTextContent(status === 'final' ? 'Winner' : 'Projected winner');
  });

  it('retains unopposed candidates with unavailable votes without manufacturing zero counts', () => {
    const { container } = render(<HousePopover race={snapshot().races[2]} name="FL-10" dc={false} />);
    const candidate = screen.getByText('Unopposed candidate').closest('.popover-candidate') as HTMLElement;
    expect(within(candidate).getByText('Projected winner')).toBeVisible();
    expect(candidate.querySelector('.popover-numbers')).toHaveTextContent('UnavailableUnavailable');
    expect(candidate.querySelector('.popover-share')).toBeNull();
    expect(screen.getByText('Votes unavailable')).toBeVisible();
    expect(container.textContent).not.toContain('0 reported votes');
  });

  it('preserves stored zero votes as distinct from unavailable counts', () => {
    const race = structuredClone(snapshot().races[0]);
    race.total_votes = 0;
    race.candidates.forEach(c => { c.votes = 0; c.share_pct = null; });
    render(<HousePopover race={race} name="CA-01" dc={false} />);
    expect(screen.getByText('0 reported votes')).toBeVisible();
    expect(screen.getAllByText('0')).toHaveLength(3);
    expect(screen.queryByText('Votes unavailable')).not.toBeInTheDocument();
  });

  it('uses shared minor-candidate grouping and keeps the original source rows unchanged', () => {
    const race = structuredClone(snapshot().races[0]);
    race.total_votes = 100_000;
    race.candidates = [
      { ...race.candidates[0], votes: 60_000, share_pct: 60 },
      { ...race.candidates[1], votes: 39_900, share_pct: 39.9 },
      { ...race.candidates[2], name: 'Small Green', party: 'G', votes: 50, share_pct: .05 },
      { ...race.candidates[2], name: 'Small independent', party: 'I', votes: 50, share_pct: .05 },
    ];
    const before = structuredClone(race);
    render(<HousePopover race={race} name="CA-01" dc={false} />);
    expect(screen.queryByText('Small Green')).not.toBeInTheDocument();
    expect(screen.queryByText('Small independent')).not.toBeInTheDocument();
    const other = screen.getByText('Other').closest('.popover-candidate') as HTMLElement;
    expect(within(other).getByText('100')).toBeVisible();
    expect(within(other).getByText('0.10%')).toBeVisible();
    expect(race).toEqual(before);
  });

  it('keeps meaningful candidates beyond the former five-row cutoff', () => {
    const race = structuredClone(snapshot().races[0]);
    race.total_votes = 600;
    race.candidates = Array.from({ length: 6 }, (_, index) => ({ ...race.candidates[0],
      name: `Candidate ${index + 1}`, party: 'I', votes: 100, share_pct: 100 / 6 }));
    const { container } = render(<HousePopover race={race} name="CA-01" dc={false} />);
    expect(container.querySelectorAll('.popover-candidate')).toHaveLength(6);
    expect(screen.getByText('Candidate 6')).toBeVisible();
  });

  it.each([false, true])('shows explicit unavailable/out-of-scope context for DC=%s', dc => {
    const { container } = render(<HousePopover name="Missing district" dc={dc} />);
    expect(screen.getByText('Votes unavailable')).toBeVisible();
    expect(container.querySelectorAll('.popover-candidate')).toHaveLength(0);
    expect(screen.getByText(dc ? /DC elects a nonvoting delegate/ : /Missing district returns do not mean zero votes/)).toBeVisible();
    expect(screen.queryByText('0 reported votes')).not.toBeInTheDocument();
  });
});
