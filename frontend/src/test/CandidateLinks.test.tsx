import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { CandidateLink } from '../CandidateLink';
import { ElectionMapPage } from '../map/ElectionMapPage';
import { JurisdictionDetail, ResultsTable } from '../map/MapResults';
import { leaderCandidate } from '../map/types';
import type { ElectionMap, MapUnit } from '../map/types';
import { useElectionMap } from '../map/useElectionMap';
import { candidacyId, contestId, publication } from './fixtures';

vi.mock('../map/useElectionMap', () => ({ useElectionMap: vi.fn() }));

const unit: MapUnit = {
  id: '36', geoid: '36', state_code: 'NY', name: 'New York', jurisdiction_id: null,
  contest_id: contestId, publication_batch_id: publication.batch_id, has_geometry: true,
  summary: { status: 'available', total_votes: 100, leader: 'Alice', margin_votes: 50, margin_pp: 50,
    candidates: [
      { label: 'Alice', kind: 'candidate', candidacy_id: candidacyId, votes: 75, share: 75,
        geographic_reference_id: null, observation_ids: [], correction_ids: [] },
      { label: 'OTHER', kind: 'aggregate', candidacy_id: null, votes: 25, share: 25,
        geographic_reference_id: null, observation_ids: [], correction_ids: [] },
    ] },
};
const data: ElectionMap = {
  year: 2008, office: 'U.S. President', stage: 'general', reporting_level: 'state',
  drill_down_level: 'county', state_code: null, selected_jurisdiction_id: null,
  availability: 'available', boundary: null, features: { type: 'FeatureCollection', features: [] },
  units: [unit], publications: [publication], metric_note: '', source_note: '',
  coverage: { boundary_units: 1, units_with_results: 1, missing_results: 0, results_without_geometry: 0 },
};

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

describe('candidate profile navigation', () => {
  it('uses only the candidacy identifier when navigating from filtered results', async () => {
    render(<MemoryRouter initialEntries={['/map?year=2008&state_code=NY&offset=25&map_unit=36&contest_id=old']}>
      <CandidateLink candidacyId={candidacyId}>Alice</CandidateLink><Location />
    </MemoryRouter>);
    await userEvent.click(screen.getByRole('link', { name: 'Alice' }));
    expect(screen.getByTestId('location').textContent).toBe(`/candidates/${candidacyId}`);
    expect(screen.getByTestId('location')).not.toHaveTextContent('offset');
    expect(screen.getByTestId('location')).not.toHaveTextContent('map_unit');
  });

  it('creates identifier-only links outside the router', () => {
    render(<CandidateLink candidacyId={candidacyId}>Alice</CandidateLink>);
    expect(screen.getByRole('link')).toHaveAttribute('href', `/candidates/${candidacyId}`);
  });

  it('keeps anonymous and unresolved source buckets as text', () => {
    render(<MemoryRouter><CandidateLink candidacyId={null}>OTHER</CandidateLink>
      <CandidateLink>Unresolved source name</CandidateLink></MemoryRouter>);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText(/OTHER/)).toHaveTextContent('OTHERUnresolved source name');
  });

  it('links result rows and leader summaries to the same candidacy, without affecting geography selection', async () => {
    const onSelect = vi.fn();
    render(<MemoryRouter initialEntries={['/map?year=2008']}>
      <JurisdictionDetail selected={unit} params={new URLSearchParams('year=2008')} />
      <ResultsTable data={data} units={[unit]} onSelect={onSelect} /><Location />
    </MemoryRouter>);
    const links = screen.getAllByRole('link', { name: 'Alice' });
    expect(links).toHaveLength(4);
    links.forEach(link => expect(link).toHaveAttribute('href', `/candidates/${candidacyId}`));
    expect(screen.queryByRole('link', { name: 'OTHER' })).not.toBeInTheDocument();
    await userEvent.click(links[2]);
    expect(screen.getByTestId('location')).toHaveTextContent(`/candidates/${candidacyId}`);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('links unambiguous candidate legend entries but leaves party and status labels as text', () => {
    vi.mocked(useElectionMap).mockReturnValue({ data, retry: vi.fn() });
    const view = render(<MemoryRouter><ElectionMapPage /></MemoryRouter>);
    const legend = screen.getByRole('list', { name: 'Map legend' });
    expect(within(legend).getByRole('link', { name: 'Alice' })).toHaveAttribute('href', `/candidates/${candidacyId}`);
    expect(within(legend).queryByRole('link', { name: 'Tie' })).not.toBeInTheDocument();
    vi.mocked(useElectionMap).mockReturnValue({ data: { ...data, reporting_level: 'congressional_district' }, retry: vi.fn() });
    view.rerender(<MemoryRouter><ElectionMapPage /></MemoryRouter>);
    expect(within(legend).queryByRole('link')).not.toBeInTheDocument();
  });

  it('does not choose an arbitrary candidacy for a legend shared by multiple contests', () => {
    const other = { ...unit, id: '06', summary: { ...unit.summary,
      candidates: [{ ...unit.summary.candidates[0], candidacy_id: 'another-candidacy' }] } };
    vi.mocked(useElectionMap).mockReturnValue({ data: { ...data, units: [unit, other] }, retry: vi.fn() });
    render(<MemoryRouter><ElectionMapPage /></MemoryRouter>);
    const legend = screen.getByRole('list', { name: 'Map legend' });
    expect(within(legend).getByText('Alice')).toBeVisible();
    expect(within(legend).queryByRole('link')).not.toBeInTheDocument();
  });

  it('does not resolve ambiguous leader labels to an arbitrary candidate', () => {
    expect(leaderCandidate({ ...unit.summary, candidates: [unit.summary.candidates[0],
      { ...unit.summary.candidates[0], candidacy_id: 'another-candidacy' }] })).toBeUndefined();
  });
});
