import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import type { PresidentialCoverage, StateResult } from '../api';
import { presidentialYears } from '../presidential';
import { contestId, jurisdictionId, page, publication, result } from './fixtures';

function Probe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><div data-testid="location">{location.pathname}{location.search}</div><button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate(1)}>Forward</button></>;
}
function open(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App /><Probe /></MemoryRouter>);
}
function respond(body: unknown, status = 200) {
  return { ok: status === 200, status, json: async () => body } as Response;
}
function coverage(year: number): PresidentialCoverage {
  return { year, election_date: `${year}-11-04`, county_coverage_verified: false,
    county: { availability: 'published', status: 'PARTIAL', source_release_id: publication.source.release_id,
      matches_active_source: true, accepted_rows: 30, excluded_rows: 5, missing_states: ['AK'],
      exclusions: [{ state_code: 'NY', code: 'unsupported_mode', rows: 5 }] },
    state: { availability: 'published' }, limitations: ['Excluded modes are not allocated.'],
    states: [{ state_code: 'NY', county: { rows: 3, votes: 110, reporting_units: 1 },
      official_votes: 100, state_minus_published_county_votes: -10 },
    { state_code: 'AK', county: null, official_votes: 0, state_minus_published_county_votes: 0 }] };
}
function stateResult(year: number): StateResult {
  return { contest_id: contestId, election_id: jurisdictionId, election_date: `${year}-11-04`,
    jurisdiction: { id: jurisdictionId, name: 'New York', state_code: 'NY', level: 'state' },
    candidate_bucket: `Source nominee ${year}`, bucket_kind: 'source_candidate', votes: 0,
    source_locator: 'Official worksheet, row 2', source_adjustment: null,
    publication: { ...publication, scope_key: `president:general:${year}:state:TOTAL`, status: 'COMPLETE',
      reporting_levels: ['state'], correction_batch_id: null, correction_source: null,
      source: { ...publication.source, name: 'fec_presidential_state', version: `fec-${year}` } } };
}
function wireCoverage(year: number) {
  const item = coverage(year);
  return { ...item, states: item.states.map(state => ({ ...state,
    county: state.county ? { ...state.county, votes: String(state.county.votes) } : null,
    state_minus_published_county_votes: String(state.state_minus_published_county_votes),
  })) };
}
function mockData() {
  const fetch = vi.fn(async (url: string) => {
    if (url === '/api/v1/presidential-coverage') return respond({ elections: presidentialYears.map(wireCoverage) });
    const query = new URLSearchParams(url.split('?')[1]);
    const year = Number(query.get('year'));
    if (url.startsWith('/api/v1/state-results')) return respond(page([stateResult(year)]));
    if (url.startsWith('/api/v1/results')) return respond(page([{ ...result, election_date: `${year}-11-04`, label: `County nominee ${year}` }]));
    if (url.startsWith('/api/v1/election-map')) return respond({ year, office: 'U.S. President', stage: 'general',
      reporting_level: 'state', drill_down_level: 'county', state_code: null, selected_jurisdiction_id: null,
      availability: 'boundaries_unavailable', boundary: null, features: { type: 'FeatureCollection', features: [] },
      units: [], publications: [], coverage: { boundary_units: 0, units_with_results: 0, missing_results: 0, results_without_geometry: 0 },
      metric_note: '', source_note: '' });
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

describe('presidential election discovery and URLs', () => {
  it('links all seven pages from primary navigation and discovery', async () => {
    const fetch = mockData();
    const user = userEvent.setup();
    open('/presidential');
    expect(within(screen.getByRole('navigation', { name: 'Primary navigation' })).getByRole('link', { name: 'Presidential' })).toHaveAttribute('aria-current', 'page');
    for (const year of presidentialYears) expect(screen.getByRole('link', { name: String(year) })).toHaveAttribute('href', expect.stringContaining(`/presidential/${year}?`));
    expect(fetch).not.toHaveBeenCalled();
    await user.click(screen.getByRole('link', { name: '2020' }));
    await screen.findByText('Source nominee 2020');
  });

  it.each(presidentialYears)('loads and remounts %s directly with pinned election filters', async year => {
    const fetch = mockData();
    const mounted = open(`/presidential/${year}?year=1996&office=U.S.+House&stage=primary`);
    await screen.findByText(`Source nominee ${year}`);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(`${year} presidential election`);
    expect(document.title).toContain(String(year));
    expect(screen.getByRole('link', { name: String(year) })).toHaveAttribute('aria-current', 'page');
    const requests = fetch.mock.calls.filter(([url]) => url.startsWith('/api/v1/state-results'));
    expect(requests.length).toBeGreaterThan(0);
    for (const [url] of requests) {
      const query = new URLSearchParams(url.split('?')[1]);
      expect(query.get('year')).toBe(String(year));
      expect(query.get('office')).toBe('U.S. President');
      expect(query.get('stage')).toBe('general');
      expect(query.has('reporting_level')).toBe(false);
    }
    const saved = screen.getByTestId('location').textContent!;
    mounted.unmount();
    open(saved);
    await screen.findByText(`Source nominee ${year}`);
  });

  it('drills into counties and preserves state and year through pagination, history and reload', async () => {
    const fetch = mockData();
    const user = userEvent.setup();
    const mounted = open('/presidential/2024');
    await user.click(await screen.findByRole('link', { name: 'New York' }));
    await screen.findByText('County nominee 2024');
    expect(fetch.mock.calls.at(-1)![0]).toContain('reporting_level=county');
    expect(fetch.mock.calls.at(-1)![0]).toContain('state_code=NY');
    expect(fetch.mock.calls.at(-1)![0]).toContain('reporting_mode=TOTAL');
    const saved = screen.getByTestId('location').textContent!;
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await screen.findByText('Source nominee 2024');
    await user.click(screen.getByRole('button', { name: 'Forward' }));
    await screen.findByText('County nominee 2024');
    mounted.unmount();
    open(saved);
    await screen.findByText('County nominee 2024');
  });

  it('changes years without carrying an exact jurisdiction or page offset', async () => {
    const fetch = mockData();
    const user = userEvent.setup();
    open(`/presidential/2008?state_code=NY&reporting_level=county&jurisdiction_id=${jurisdictionId}&offset=25`);
    await screen.findByText('County nominee 2008');
    await user.click(screen.getByRole('link', { name: '2024' }));
    await screen.findByText('County nominee 2024');
    expect(screen.getByTestId('location')).not.toHaveTextContent('jurisdiction_id=');
    expect(screen.getByTestId('location')).not.toHaveTextContent('offset=');
    expect(fetch.mock.calls.at(-1)![0]).toContain('state_code=NY');
    expect(screen.queryByText('County nominee 2008')).not.toBeInTheDocument();
  });

  it('uses contextual shared filters and clears back to the same presidential year', async () => {
    mockData();
    const user = userEvent.setup();
    open(`/presidential/2008?state_code=NY&jurisdiction_id=${jurisdictionId}&offset=25`);
    await screen.findByText('Source nominee 2008');
    await user.click(screen.getByRole('button', { name: 'Show filters' }));
    expect(screen.queryByLabelText('Office')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Election year'), '2016');
    await user.selectOptions(screen.getByLabelText('Reporting level'), 'county');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await screen.findByText('County nominee 2016');
    expect(screen.getByTestId('location')).toHaveTextContent('/presidential/2016?');
    expect(screen.getByTestId('location')).not.toHaveTextContent('jurisdiction_id=');
    expect(screen.getByTestId('location')).not.toHaveTextContent('offset=');
    await user.click(screen.getByRole('button', { name: 'Show filters' }));
    await user.click(screen.getByRole('link', { name: 'Clear filters' }));
    await screen.findByText('Source nominee 2016');
    expect(screen.getByTestId('location')).not.toHaveTextContent('state_code=');
  });

  it('leaves state authority pages for the existing county browser with valid filters', async () => {
    const fetch = mockData();
    const user = userEvent.setup();
    open('/presidential/2024?state_code=NY');
    await screen.findByText('Source nominee 2024');
    await user.click(screen.getByRole('link', { name: 'Candidates' }));
    await screen.findByText('County nominee 2024');
    expect(fetch.mock.calls.at(-1)![0]).toContain('reporting_level=county');
  });

  it.each(['/presidential/1996', '/presidential/2023', '/presidential/nope'])('explains unsupported years without requests: %s', path => {
    const fetch = mockData();
    open(path);
    expect(screen.getByRole('heading', { name: 'Presidential election not available' })).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(['state_code=ZZ', 'reporting_level=precinct', 'reporting_level=county&reporting_level=state', 'offset=-1'])('rejects invalid selection without data requests: %s', query => {
    const fetch = mockData();
    open(`/presidential/2024?${query}`);
    expect(screen.getByRole('alert')).toHaveTextContent('Review your filters');
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe('presidential coverage, sources and missing data', () => {
  it('displays source versions and partial coverage, keeps zero distinct from missing, and preserves signed differences', async () => {
    mockData();
    const user = userEvent.setup();
    open('/presidential/2024');
    await screen.findByText('Source nominee 2024');
    expect(screen.getByText(/County returns: partial publication/)).toBeVisible();
    expect(screen.getByText(/County coverage has not been independently verified/)).toBeVisible();
    const table = screen.getByRole('region', { name: 'State totals table' });
    expect(within(table).getByText('0')).toBeVisible();
    expect(within(table).queryByRole('link', { name: 'Source nominee 2024' })).not.toBeInTheDocument();
    await user.click(screen.getByText('Source and publication details'));
    expect(screen.getByText(/Version fec-2024/)).toBeVisible();
    await user.click(screen.getByText('County gaps and state comparison'));
    const comparison = screen.getByRole('region', { name: 'State and county coverage comparison' });
    expect(within(comparison).getByText('Unavailable')).toBeVisible();
    expect(within(comparison).getByText('-10')).toBeVisible();
    expect(screen.getByText(/unsupported mode: 5 rows/)).toBeVisible();
    expect(screen.getByText(/States without published county returns: AK/)).toBeVisible();
  });

  it('announces independent loading and retryable coverage errors while showing returns', async () => {
    const base = mockData();
    let fail = true;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('presidential-coverage') && fail
      ? respond({ detail: 'private detail' }, 503) : base(url)));
    const user = userEvent.setup();
    open('/presidential/2024');
    expect(screen.getAllByRole('status').map(node => node.textContent).join(' ')).toContain('Loading election coverage');
    await screen.findByText('Source nominee 2024');
    expect(screen.getByRole('alert')).toHaveTextContent('Coverage could not be loaded');
    expect(screen.queryByText('private detail')).not.toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Retry coverage' }));
    await screen.findByText(/County returns: partial publication/);
  });

  it.each(['missing-year', 'malformed'])('handles %s coverage without hiding available results', async failure => {
    const base = mockData();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('presidential-coverage')
      ? respond({ elections: failure === 'missing-year' ? [] : [{ year: 2024 }] }) : base(url)));
    open('/presidential/2024');
    await screen.findByText('Source nominee 2024');
    expect(screen.getByRole('heading', { name: failure === 'missing-year' ? 'Coverage not available' : 'Coverage could not be loaded' })).toBeVisible();
  });

  it.each(['9007199254740993', '10.5', '-1'])('rejects unsafe or invalid county vote strings: %s', async votes => {
    const base = mockData();
    const item = wireCoverage(2024);
    item.states[0].county!.votes = votes;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('presidential-coverage')
      ? respond({ elections: [item] }) : base(url)));
    open('/presidential/2024');
    await screen.findByText('Source nominee 2024');
    expect(screen.getByRole('heading', { name: 'Coverage could not be loaded' })).toBeVisible();
  });

  it('distinguishes empty state results and retries sanitized result failures', async () => {
    const base = mockData();
    let fail = true;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('state-results')
      ? (fail ? respond({ detail: 'private database detail' }, 503) : respond(page([]))) : base(url)));
    const user = userEvent.setup();
    open('/presidential/2024');
    expect(await screen.findByRole('alert')).toHaveTextContent('Data could not be loaded');
    expect(screen.queryByText('private database detail')).not.toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByRole('heading', { name: 'No matching data' });
    expect(screen.getByText(/An absent record does not mean zero votes/)).toBeVisible();
  });

  it('aborts both prior requests and ignores late results and coverage after changing years', async () => {
    const base = mockData();
    const pending: { resolve: (value: Response) => void; signal: AbortSignal; url: string }[] = [];
    let hold = true;
    vi.stubGlobal('fetch', vi.fn((url: string, options: RequestInit) => hold
      ? new Promise<Response>(resolve => pending.push({ resolve, signal: options.signal as AbortSignal, url })) : base(url)));
    const user = userEvent.setup();
    open('/presidential/2008');
    expect(pending).toHaveLength(2);
    hold = false;
    await user.click(screen.getByRole('link', { name: '2024' }));
    await screen.findByText('Source nominee 2024');
    expect(pending.every(request => request.signal.aborted)).toBe(true);
    await act(async () => { for (const request of pending) request.resolve(respond(request.url.includes('coverage')
      ? { elections: [coverage(2008)] } : page([stateResult(2008)]))); });
    expect(screen.queryByText('Source nominee 2008')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Election coverage/ })).toHaveTextContent('2024');
  });

  it('paginates state totals without sending county-only parameters', async () => {
    const base = mockData();
    const fetch = vi.fn(async (url: string) => url.includes('state-results') ? respond(page([stateResult(2024)], {
      total: 26, offset: url.includes('offset=25') ? 25 : 0, has_more: !url.includes('offset=25'),
    })) : base(url));
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    open('/presidential/2024?state_code=NY');
    await user.click(await screen.findByRole('link', { name: 'Next page' }));
    await screen.findByText('26–26 of 26 records');
    const query = new URLSearchParams(fetch.mock.calls.at(-1)![0].split('?')[1]);
    expect(query.get('state_code')).toBe('NY');
    expect(query.get('year')).toBe('2024');
    expect(query.has('reporting_mode')).toBe(false);
    expect(query.has('reporting_level')).toBe(false);
  });

  it.each(presidentialYears)('opens the correct %s map and explains unavailable shapes', async year => {
    const fetch = mockData();
    const user = userEvent.setup();
    open(`/presidential/${year}`);
    await screen.findByText(`Source nominee ${year}`);
    await user.click(screen.getByRole('link', { name: 'Open election map' }));
    await screen.findByRole('heading', { name: 'Map boundaries are not available yet' });
    const mapRequest = fetch.mock.calls.find(([url]) => url.includes('election-map'))![0];
    expect(new URLSearchParams(mapRequest.split('?')[1]).get('year')).toBe(String(year));
    expect(screen.queryByRole('img', { name: /map/i })).not.toBeInTheDocument();
  });
});
