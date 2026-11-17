import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { candidateProfile, candidacyId, contest, contestId, page, publication, result } from './fixtures';

function HistoryProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><div data-testid="location">{location.pathname}{location.search}</div><button onClick={() => navigate(-1)}>Browser back</button><button onClick={() => navigate(1)}>Browser forward</button><button onClick={() => navigate('/contests?year=2024')}>Open 2024 contests</button><button onClick={() => navigate('/contests')}>Open all contests</button></>;
}
function open(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App /><HistoryProbe /></MemoryRouter>);
}
function respond(body: unknown, status = 200) {
  return { ok: status === 200, status, json: async () => body } as Response;
}
function mockData() {
  const fetch = vi.fn(async (url: string) => respond(url.startsWith('/api/v1/candidates/') ? candidateProfile : url.startsWith('/api/v1/contests') ? page([contest]) : page([result])));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

describe('research shell', () => {
  it.each(['/map?year=2008', '/contests?year=2024&state_code=NY', '/candidates', '/presidential/2024'])('has no global filtering controls on %s', path => {
    mockData();
    const view = open(path);
    expect(screen.queryByRole('button', { name: /filters/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name:'Filters' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name:'Applied filters' })).not.toBeInTheDocument();
    expect(view.container.querySelector('.nav-chevron')).toBeNull();
  });



  it('opens the landing placeholder without requesting map data', async () => {
    const fetch = mockData();
    open('/');
    expect(screen.getByRole('heading', { name:'Welcome to Electoral Atlas' })).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name:'Electoral Atlas home' })).toHaveAttribute('href','/');
    expect(screen.getByRole('link', { name:'Skip to main content' })).toHaveAttribute('href','#main-content');
  });

  it('starts a fresh section from the header without inherited election context', async () => {
    const fetch=mockData(); const user=userEvent.setup();
    open('/contests?year=2024&office=U.S.+House&state_code=NY');
    await screen.findByRole('heading', { name:contest.office_name });
    await user.click(screen.getByRole('button', { name:'Search' }));
    await user.click(screen.getByRole('link', { name:'Candidates' }));
    await screen.findByRole('table');
    expect(screen.getByTestId('location').textContent).toBe('/candidates');
    const query=new URLSearchParams(fetch.mock.calls.at(-1)![0].split('?')[1]);
    for (const key of ['year','office','state_code']) expect(query.has(key)).toBe(false);
  });

  it('retains page-specific selection through browser history and direct URLs', async () => {
    mockData(); const user=userEvent.setup();
    open('/contests?year=2008&state_code=NY');
    await user.click(screen.getByRole('button', { name:'Open 2024 contests' }));
    expect(screen.getByTestId('location').textContent).toBe('/contests?year=2024');
    await user.click(screen.getByRole('button', { name:'Browser back' }));
    expect(screen.getByTestId('location').textContent).toBe('/contests?year=2008&state_code=NY');
  });

  it('navigates contest to candidacy context and back while preserving filters', async () => {
    const fetch = mockData();
    const user = userEvent.setup();
    open('/contests?year=2008&state_code=NY');
    await user.click(await screen.findByRole('link', { name: 'President of the United States' }));
    await screen.findByRole('heading', { name: 'Contest returns' });
    expect(fetch.mock.calls.at(-1)![0]).toContain(`contest_id=${contestId}`);
    await user.click(await screen.findByRole('link', { name: result.label }));
    expect(screen.getByTestId('location')).toHaveTextContent(`/candidates/${candidacyId}?year=2008&state_code=NY&contest_id=${contestId}`);
    expect(await screen.findByRole('heading', { name: 'Identity & candidacy' })).toBeVisible();
    expect(screen.getByText(/has not been linked to a verified person/)).toBeVisible();
    await user.click(screen.getByRole('link', { name: 'View this contest’s published returns' }));
    await screen.findByRole('table');
    expect(screen.getByTestId('location')).toHaveTextContent('state_code=NY');
  });



  it('shows an accessible unknown-route state', () => {
    open('/unknown?year=2024');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Return to the explorer' })).toHaveAttribute('href', '/map?year=2024');
  });
});

describe('published records and provenance', () => {
  it('shows source versions, partial coverage, correction lineage and publication-wide counts', async () => {
    mockData();
    const user = userEvent.setup();
    open('/contests?year=2008');
    await screen.findByText('Partial publication');
    expect(screen.getByText(/Coverage is incomplete/)).toBeVisible();
    expect(screen.getByText(/County coverage has not been independently verified/)).toBeVisible();
    await user.click(screen.getByText('Source and publication details'));
    expect(screen.getByText(publication.source.sha256)).toBeVisible();
    expect(screen.getByText(/90 accepted \/ 100 input rows; 10 excluded/)).toBeVisible();
    expect(screen.getByText(/Counts describe the entire publication/)).toBeVisible();
    expect(screen.getByRole('link', { name: 'reviewed_county_corrections — source download' })).toHaveAttribute('href', 'https://example.org/corrections');
  });

  it('keeps stored zero votes, anonymous buckets, statistical vintages and result batches distinct', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond(page([result, { ...result, candidacy_id: null,
      label: 'OTHER', basis: 'aggregate', votes: 7, observation_ids: [contestId] }]))));
    open('/candidates?year=2008');
    const table = await screen.findByRole('table');
    expect(within(table).getByText('0')).toBeVisible();
    expect(within(table).getByText('OTHER')).toBeVisible();
    expect(within(table).queryByRole('link', { name: 'OTHER' })).not.toBeInTheDocument();
    expect(within(table).getByText(/Anonymous aggregate bucket/)).toBeVisible();
    expect(within(table).getAllByText('Reference vintage: 2008–2008')).toHaveLength(2);
    expect(screen.getByText(/State authority totals are a separate, non-additive source/)).toBeVisible();
    expect(screen.getByText(/2 matching result records/)).toBeVisible();
  });

  it('labels modeled contests without publications', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond(page([{ ...contest, publications: [] }]))));
    open('/contests');
    expect(await screen.findByText('No published returns')).toBeVisible();
    expect(screen.queryByText('Complete publication')).not.toBeInTheDocument();
  });

  it('paginates with the same filters and never adds a page total', async () => {
    const fetch = vi.fn(async (url: string) => respond(page([result], { total: 26,
      offset: url.includes('offset=25') ? 25 : 0, has_more: !url.includes('offset=25') })));
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    open('/candidates?year=2008&state_code=NY');
    await user.click(await screen.findByRole('link', { name: 'Next page' }));
    await screen.findByText('26–26 of 26 records');
    expect(fetch.mock.calls.at(-1)![0]).toContain('state_code=NY');
    await user.click(screen.getByRole('link', { name: 'Previous page' }));
    await screen.findByText('1–1 of 26 records');
  });
});

describe('loading, errors and missing data', () => {
  it('announces loading and ignores a late response after navigation', async () => {
    let finish!: (response: Response) => void;
    const fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve; }));
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    open('/contests?year=2008');
    expect(screen.getByRole('status')).toHaveTextContent('Loading published data');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await user.click(screen.getByRole('link', { name: 'Map' }));
    const options = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((options.signal as AbortSignal).aborted).toBe(true);
    await act(async () => finish(respond(page([contest]))));
    expect(screen.queryByRole('heading', { name: contest.office_name })).not.toBeInTheDocument();
  });

  it('clears prior records immediately and ignores out-of-order responses for changed filters', async () => {
    let finish!: (response: Response) => void;
    const fetch = vi.fn().mockResolvedValueOnce(respond(page([contest])))
      .mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(respond(page([])));
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    open('/contests?year=2008');
    await screen.findByRole('heading', { name: contest.office_name });
    await user.click(screen.getByRole('button', { name:'Open 2024 contests' }));
    expect(screen.getByRole('status')).toHaveTextContent('Loading published data');
    expect(screen.queryByRole('heading', { name: contest.office_name })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name:'Open all contests' }));
    await screen.findByRole('heading', { name: 'No matching data' });
    await act(async () => finish(respond(page([contest]))));
    expect(screen.getByRole('heading', { name: 'No matching data' })).toBeVisible();
  });

  it.each([503, 422])('shows sanitized HTTP %s errors and retries without losing selection', async status => {
    const fetch = vi.fn().mockResolvedValueOnce(respond({ detail: 'private database failure' }, status))
      .mockResolvedValueOnce(respond(page([contest])));
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    open('/contests?year=2008&state_code=NY');
    expect(await screen.findByRole('alert')).toHaveTextContent('Data could not be loaded');
    expect(screen.queryByText(/private database/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByRole('heading', { name: contest.office_name });
    expect(fetch.mock.calls[1][0]).toBe(fetch.mock.calls[0][0]);
  });

  it.each(['network', 'invalid-json', 'invalid-page'])('handles %s failures accessibly', async failure => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      if (failure === 'network') throw new Error('private network detail');
      if (failure === 'invalid-json') return { ok: true, json: async () => { throw new Error('Bad JSON'); } };
      return respond({ items: 'not an array' });
    }));
    open('/contests');
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load published data');
  });

  it('distinguishes unavailable results from zero-vote returns', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond(page([], { availability: 'no_matching_published_results' }))));
    open('/candidates?year=2024&office=U.S.+House');
    await screen.findByRole('heading', { name: 'No matching data' });
    expect(screen.getByRole('status')).toHaveTextContent('No matching data');
    expect(screen.getByText(/An absent record does not mean zero votes/)).toBeVisible();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('distinguishes an empty page from an empty dataset', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond(page([], { total: 3, offset: 999, availability: 'available' }))));
    open('/contests?year=2008&offset=999');
    expect(await screen.findByRole('heading', { name: 'No records on this page' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'No matching data' })).not.toBeInTheDocument();
  });

  it.each(['/contests?year=invalid', '/candidates?state_code=ZZ', '/contests/bad-id', '/candidates/bad-id'])('rejects invalid deep links without requesting data: %s', async path => {
    const fetch = mockData();
    open(path);
    expect(screen.getByRole('alert')).toBeVisible();
    await waitFor(() => expect(fetch).not.toHaveBeenCalled());
  });
});
