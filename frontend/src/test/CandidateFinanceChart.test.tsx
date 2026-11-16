import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CandidateFinanceChart, financeCsv } from '../CandidateFinanceChart';
import { candidatePortrait } from '../candidatePresentation';
import { candidateProfile, publication } from './fixtures';

describe('candidate finance presentation', () => {
  it('distinguishes zero, negative adjustments and missing values in chart geometry', () => {
    render(<CandidateFinanceChart finance={{ ...candidateProfile.finance, total_raised: '100.00',
      total_spent: '-20.00', cash_on_hand: '0.00', debts: null }} />);
    const chart = screen.getByRole('figure', { name: 'Campaign finance comparison' });
    expect(within(chart).getByText('$0.00')).toBeVisible();
    expect(within(chart).getByText('-$20.00')).toBeVisible();
    const missing = within(chart).getAllByText('Not available');
    expect(missing.length).toBeGreaterThan(0);
    const bars = chart.querySelectorAll<HTMLElement>('.profile-chart-bar');
    expect(bars).toHaveLength(3);
    expect(parseFloat(bars[1].style.left)).toBe(0);
    expect(parseFloat(bars[1].style.width)).toBeGreaterThan(0);
    expect(parseFloat(bars[2].style.width)).toBe(0);
  });

  it('omits chart marks when all amounts are missing', () => {
    render(<CandidateFinanceChart finance={candidateProfile.finance} />);
    expect(screen.queryByRole('figure')).not.toBeInTheDocument();
    expect(screen.getByText(/chart will appear/)).toBeVisible();
  });

  it('exports exact source cents, scope and provenance without turning missing values into zero', () => {
    const csv = financeCsv({ ...candidateProfile.finance, total_raised: '1234567890123456.78',
      total_spent: '0.00', source: publication.source, definition: 'reported_totals' });
    expect(csv).toContain('"Raised","1234567890123456.78","USD","2008"');
    expect(csv).toContain('"Spent","0.00"');
    expect(csv).toContain('"Debts",""');
    expect(csv).toContain(publication.source.sha256);
    expect(csv).toContain('reported_totals');
  });

  it('does not attach a portrait to an unresolved name or an unknown identifier', () => {
    expect(candidatePortrait({ ...candidateProfile,
      finance: { ...candidateProfile.finance, fec_candidate_id: 'H8NY15148' } })).toBeUndefined();
    expect(candidatePortrait({ ...candidateProfile, identity_status: 'resolved',
      person: { id: candidateProfile.id, full_name: 'Different person' },
      finance: { ...candidateProfile.finance, fec_candidate_id: 'H00000001' } })).toBeUndefined();
  });
});
