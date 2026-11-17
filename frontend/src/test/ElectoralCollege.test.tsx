import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ElectoralCollegeCounter, electoralAllocation, PresidentialMapLabels } from '../map/ElectoralCollege';
import type { ElectionMap } from '../map/types';

describe('official electoral vote presentation', () => {
  it.each([2000,2004,2008,2012,2016,2020,2024])('reconciles %s to 538 electors and source-backed national totals', year => {
    const data = electoralAllocation(year)!;
    expect(Object.keys(data.states)).toHaveLength(51);
    expect(Object.values(data.states).reduce((n,s)=>n+s.electors,0)).toBe(538);
    expect(data.candidates.reduce((n,c)=>n+c.votes,0)+data.other).toBe(538);
    data.candidates.forEach((candidate,i)=>expect(Object.values(data.states).reduce((n,s)=>n+s.votes[i],0)).toBe(candidate.votes));
    expect(data.source.sha256).toMatch(/^[a-f0-9]{64}$/);
    render(<ElectoralCollegeCounter year={year} />);
    expect(screen.getByRole('img')).toHaveAccessibleName(/270 electoral votes needed to win/);
  });
  it('matches the reference 2012 count and preserves splits, faithless votes and abstentions', () => {
    expect(electoralAllocation(2012)!.candidates.map(c=>c.votes)).toEqual([332,206]);
    expect(electoralAllocation(2020)!.states.ME.votes).toEqual([3,1]);
    expect(electoralAllocation(2020)!.states.NE.votes).toEqual([1,4]);
    expect(electoralAllocation(2016)!.other).toBe(7);
    expect(electoralAllocation(2004)!.other).toBe(1);
    expect(electoralAllocation(2000)!.other_label).toBe('Abstained');
    expect(electoralAllocation(2000)!.other).toBe(1);
    expect(electoralAllocation(2000)!.states.CA.electors).toBe(54);
    expect(electoralAllocation(2024)!.states.CA.electors).toBe(54);
    expect(electoralAllocation(2012)!.states.CA.electors).toBe(55);
  });
  it('offers keyboard-accessible small-state county drill-down without altering national totals', async () => {
    const unit = {state_code:'RI'};
    const select = vi.fn();
    render(<PresidentialMapLabels data={{year:2012,office:'U.S. President',stage:'general',reporting_level:'state',state_code:null,units:[unit]} as ElectionMap} onSelect={select}><div>Map</div></PresidentialMapLabels>);
    await userEvent.setup().click(screen.getByRole('button',{name:'RHODE ISLAND: 4 electoral votes; view county results'}));
    expect(select).toHaveBeenCalledWith(unit);
  });
  it('does not show electoral allocations for unsupported years or House maps', () => {
    const view=render(<ElectoralCollegeCounter year={1996} />);
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    view.rerender(<PresidentialMapLabels data={{year:2024,office:'U.S. House',stage:'general',reporting_level:'congressional_district'} as ElectionMap} onSelect={vi.fn()}><div>House map</div></PresidentialMapLabels>);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
