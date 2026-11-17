import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { CandidateElection } from '../CandidateElection';
import { useElectionMap } from '../map/useElectionMap';
import type { ElectionMap } from '../map/types';
import { candidateProfile, candidacyId, contestId, publication } from './fixtures';

vi.mock('../map/useElectionMap', () => ({ useElectionMap: vi.fn() }));
vi.mock('../map/GeographyMap', () => ({ GeographyMap: ({ data, highlightedIds, focusSelection }: { data: ElectionMap; highlightedIds?: ReadonlySet<string>; focusSelection?: boolean }) => <div aria-label="Embedded election map" data-highlighted={Array.from(highlightedIds || []).join(',')} data-focus-selection={String(focusSelection)}>{data.units.map(unit => unit.name).join(', ')}</div> }));

const map: ElectionMap = {
  year: 2024, office: 'U.S. House', stage: 'general', reporting_level: 'congressional_district',
  availability: 'available', publications: [publication],
  drill_down_level: null, state_code: 'NY', selected_jurisdiction_id: null, boundary: null,
  coverage: { boundary_units: 2, units_with_results: 2, missing_results: 0, results_without_geometry: 0 }, metric_note: '', source_note: '',
  features: { type: 'FeatureCollection', features: [{ type: 'Feature', id: '3614', properties: { geoid: '3614', name: 'District 14', state_code: 'NY' }, geometry: { type: 'Polygon', coordinates: [] } }] },
  units: [{ id: '3614', geoid: '3614', state_code: 'NY', jurisdiction_id: null, has_geometry: true, name: 'District 14', contest_id: contestId, publication_batch_id: publication.batch_id,
    summary: { status: 'available', leader: 'ALICE', total_votes: 100, margin_votes: 20, margin_pp: 20, candidates: [
      { label: 'ALICE', candidacy_id: candidacyId, kind: 'candidate', party_labels: ['DEMOCRATIC'], votes: 60, share: 60, geographic_reference_id: null, observation_ids: [], correction_ids: [] },
      { label: 'BOB', candidacy_id: null, kind: 'candidate', party_labels: ['REPUBLICAN'], votes: 40, share: 40, geographic_reference_id: null, observation_ids: [], correction_ids: [] },
    ] } }, { id: '3601', geoid: '3601', state_code: 'NY', jurisdiction_id: null, has_geometry: false, publication_batch_id: null, name: 'Other contest', contest_id: 'other', summary: { status: 'no_results', total_votes: null, leader: null, margin_votes: null, margin_pp: null, candidates: [] } }],
};

describe('most recent candidate election', () => {
  it('retains geographic context while highlighting only the latest contest and keeping its results scoped', async () => {
    vi.mocked(useElectionMap).mockReturnValue({ data: map, retry: vi.fn() });
    render(<MemoryRouter><CandidateElection profile={{ ...candidateProfile,
      latest_election: { ...candidateProfile.contest, candidacy_id: candidacyId, election_date: '2024-11-05', office_name: 'U.S. House' },
    }} /></MemoryRouter>);
    expect(await screen.findByLabelText('Embedded election map')).toHaveTextContent('District 14');
    expect(screen.getByLabelText('Embedded election map')).toHaveTextContent('Other contest');
    expect(screen.getByLabelText('Embedded election map')).toHaveAttribute('data-highlighted', '3614');
    expect(screen.getByLabelText('Embedded election map')).toHaveAttribute('data-focus-selection', 'false');
    expect(screen.getByRole('table', { name: 'Candidate votes and share of reported votes' })).toHaveTextContent('60.00%');
    expect(screen.getByText('Bob')).toBeVisible();
    expect(screen.getByText('Alice').closest('th')!.querySelector('.profile-result-dot')).toHaveStyle({ background:'#3276ac' });
    expect(screen.getByText('Bob').closest('th')!.querySelector('.profile-result-dot')).toHaveStyle({ background:'#bd5548' });
    expect(screen.getByRole('link', { name: 'Alice' })).toHaveAttribute('href', `/candidates/${candidacyId}?contest_id=${contestId}`);
    expect(screen.queryByRole('link', { name: 'Bob' })).not.toBeInTheDocument();
    expect(screen.getByText('This candidate')).toBeVisible();
    await userEvent.setup().click(screen.getByText('Source and publication details'));
    const sources = screen.getByText('Source and publication details').closest('details')!;
    expect(within(sources).getByRole('link', { name: 'MIT Election Data and Science Lab' })).toHaveAttribute('href', publication.source.url);
    for (const value of [publication.batch_id, publication.scope_key, publication.source.release_id,
      publication.source.sha256, publication.source.retrieved_at, 'Release', 'Retrieved', 'SHA-256', 'Batch', 'Publication coverage']) {
      expect(sources).not.toHaveTextContent(value);
    }
    expect(within(sources).getByText('Partial publication')).toBeVisible();
    expect(within(sources).getByText(/Coverage is incomplete/)).toBeVisible();
    const query = new URLSearchParams(vi.mocked(useElectionMap).mock.calls.at(-1)![0]);
    expect(query.get('year')).toBe('2024');
    expect(query.get('office')).toBe('U.S. House');
  });

  it('retains published candidate returns when the map request fails', () => {
    vi.mocked(useElectionMap).mockReturnValue({ error: 'Map unavailable', retry: vi.fn() });
    render(<MemoryRouter><CandidateElection profile={candidateProfile} /></MemoryRouter>);
    expect(screen.getByText('Election map could not be loaded')).toBeVisible();
    expect(screen.getByRole('table', { name: 'Source-backed votes by reporting unit' })).toHaveTextContent('0');
  });

  it('does not imply a completed election when none is known', () => {
    vi.mocked(useElectionMap).mockReturnValue({ retry: vi.fn() });
    render(<MemoryRouter><CandidateElection profile={{ ...candidateProfile, latest_election: null }} /></MemoryRouter>);
    expect(screen.getByText('No completed election is available for this candidate.')).toBeVisible();
    expect(vi.mocked(useElectionMap).mock.calls.at(-1)![1]).toBe(false);
  });

  it('loads the latest candidacy returns rather than older profile votes when its map fails', async () => {
    const latestId = '00000000-0000-4000-8000-000000000099';
    vi.mocked(useElectionMap).mockReturnValue({ error: 'Map unavailable', retry: vi.fn() });
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...candidateProfile, id: latestId,
      results: { ...candidateProfile.results, items: [{ ...candidateProfile.results.items[0], votes: 777 }] },
    }) })));
    render(<MemoryRouter><CandidateElection profile={{ ...candidateProfile,
      latest_election: { ...candidateProfile.contest, candidacy_id: latestId, election_date: '2024-11-05' },
    }} /></MemoryRouter>);
    expect(await screen.findByRole('table', { name: 'Source-backed votes by reporting unit' })).toHaveTextContent('777');
  });
});
