import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SenateControl } from '../SenateControl';
import type { SenateControl as Control } from '../senate';

const control: Control = { total_seats: 100, majority_threshold: 51, seats_up: 35,
  retained: { D: 32, R: 31, I: 2, O: 0 }, called: { D: 22, R: 13, I: 0, O: 0 },
  totals: { D: 54, R: 44, I: 2, O: 0 }, unresolved: 0, democratic_aligned: 56,
  retained_democratic_aligned: 34, independent_democratic_caucus: 2, other_unaligned: 0,
  certified_contests: 1, control: 'D', gains: { D: 9, R: 0 }, net_change: { D: 9, R: -9 },
  baseline_as_of: '2026-11-03', baseline_reviewed_at: '2026-11-17', sources: [] };

describe('Senate control indicator', () => {
  it('accounts for all 100 seats and labels independent caucusing without changing party identity', () => {
    const { container } = render(<SenateControl control={control} />);
    expect(screen.getByText('56')).toBeVisible();
    expect(screen.getByText('44')).toBeVisible();
    expect(screen.getByText(/54 Democrats \+ 2 independents caucusing with Democrats/)).toBeVisible();
    expect(screen.getByLabelText('Projected Democratic-aligned majority')).toBeVisible();
    expect(screen.getByText('Flipped 9 seats (+9 net gain)')).toBeVisible();
    expect(screen.getByText('35 up for election')).toBeVisible();
    const seats = Array.from(container.querySelectorAll<HTMLElement>('.control-bar > span')).reduce((sum, el) => sum + parseFloat(el.style.width), 0);
    expect(seats).toBe(100);
    expect(container.querySelector('.control-election-bracket')).toHaveStyle({ left: '34%', width: '35%' });
  });

  it('does not show a majority check for an uncalled chamber', () => {
    const { container } = render(<SenateControl control={{ ...control, control: null, democratic_aligned: 34,
      totals: { D: 32, R: 31, I: 2, O: 0 }, called: { D: 0, R: 0, I: 0, O: 0 }, unresolved: 35 }} />);
    expect(container.querySelector('.control-check')).not.toBeInTheDocument();
    expect(container.querySelector('.control-uncalled')).toHaveStyle({ width: '35%' });
    expect(screen.getByRole('img')).toHaveAccessibleName(/35 uncalled/);
  });

  it('uses the Republican majority indicator when the projected tally crosses 51', () => {
    render(<SenateControl control={{ ...control, control: 'R', democratic_aligned: 47,
      called: { D: 13, R: 22, I: 0, O: 0 }, totals: { D: 45, R: 53, I: 2, O: 0 } }} />);
    expect(screen.getByLabelText('Projected Republican majority')).toBeVisible();
    expect(screen.queryByLabelText('Projected Democratic-aligned majority')).not.toBeInTheDocument();
  });

  it('explains missing control data without showing invented totals', () => {
    render(<SenateControl />);
    expect(screen.getByRole('status')).toHaveTextContent('Senate control data is unavailable');
  });
});
