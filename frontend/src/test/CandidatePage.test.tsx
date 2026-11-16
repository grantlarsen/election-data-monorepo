import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { dollars } from '../CandidatePage';
import { candidateProfile, candidacyId, publication } from './fixtures';

function open(path = `/candidates/${candidacyId}`) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}
function response(body: unknown, status = 200) {
  return { ok: status === 200, status, json: async () => body } as Response;
}

describe('candidate profiles', () => {
  it('loads a shareable profile without requiring explorer filters', async () => {
    const fetch = vi.fn(async () => response({ ...candidateProfile, identity_evidence: [{
      status: 'pending', confidence: '0.800', evidence: {}, decision_evidence: null, decided_at: null,
      record_id: candidacyId, fec_candidate_id: 'H00000001', source: publication.source,
    }] }));
    vi.stubGlobal('fetch', fetch);
    open();
    expect(await screen.findByRole('heading', { name: candidateProfile.label! })).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(`/api/v1/candidates/${candidacyId}?`, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByRole('heading', { name: 'Identity & candidacy' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Summary' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Most recent election' })).toBeVisible();
    expect(screen.getByText('Total Raised')).toBeVisible();
    expect(screen.getByText('Total Spent')).toBeVisible();
    expect(screen.getByText(/Missing figures are not zero/)).toBeVisible();
    expect(screen.getByText('Partial publication')).not.toBeVisible();
    expect(screen.queryByText(/Newer elections may not yet be available/)).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByText('Source and publication details'));
    expect(screen.getByText('Partial publication')).toBeVisible();
    expect(screen.getByRole('link', { name: 'MIT Election Data and Science Lab' })).toBeVisible();
    expect(screen.getByRole('table', { name: 'Source-backed votes by reporting unit' })).toHaveTextContent('0');
    expect(screen.getByRole('navigation', { name: 'Candidate profile sections' })).toBeVisible();
    await userEvent.setup().click(screen.getByText('Identity review evidence'));
    const evidence = screen.getByText('Identity review evidence').closest('details')!;
    expect(within(evidence).getByText(/FEC candidate: H00000001/)).toBeVisible();
    expect(within(evidence).getByText(publication.source.sha256)).toBeVisible();
  });

  it('renders sourced finance, committees and exact zero amounts for the profile cycle', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ ...candidateProfile,
      person: { id: candidacyId, full_name: 'Alex Smith' }, identity_status: 'resolved',
      committees: [{ id: candidacyId, name: 'Alex for Congress', role: 'principal_campaign',
        cycle: 2024, fec_ids: ['C00000001'], evidence: 'Official candidate master', source: publication.source }],
      finance: { ...candidateProfile.finance, status: 'available', cycle: 2024,
        total_raised: '1234567890123456.78', total_spent: '0.00', reported_receipts: '1234567890123466.78',
        reported_disbursements: '10.00', transfers_from_authorized: '10.00', transfers_to_authorized: '10.00',
        definition: 'reported_totals_less_authorized_transfers', coverage_end: '2024-12-31',
        fec_candidate_id: 'H00000001', source: publication.source },
    })));
    open(`/candidates/${candidacyId}?year=2008`);
    const headline = await screen.findByRole('region', { name: 'Campaign finance headline totals' });
    expect(within(headline).getByText('$1,234,567,890,123,456.78')).toBeVisible();
    expect(within(headline).getByText('$0.00')).toBeVisible();
    expect(screen.getByText(/FEC cycle 2024/)).toBeVisible();
    await userEvent.setup().click(screen.getByText('Financial source & calculation details'));
    expect(screen.getByText(/following FEC guidance/)).toBeVisible();
    const financialDetails = screen.getByText('Financial source & calculation details').closest('details')!;
    expect(within(financialDetails).queryByText(publication.source.release_id)).not.toBeInTheDocument();
    expect(within(financialDetails).queryByText(publication.source.sha256)).not.toBeInTheDocument();
    expect(within(financialDetails).queryByText('Retrieved')).not.toBeInTheDocument();
    expect(financialDetails).not.toHaveTextContent('H00000001');
    const sourceLink = within(financialDetails).getByRole('link', { name: 'Federal Election Commission — source download' });
    expect(sourceLink).toHaveAttribute('href', publication.source.url);
    expect(sourceLink.compareDocumentPosition(within(financialDetails).getByText(/following FEC guidance/)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Alex for Congress' })).toBeVisible();
    expect(screen.getAllByText(publication.source.sha256).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Through 2024-12-31/)[0]).toBeVisible();
    // The contest link uses its own actual year/grain, independently of explorer filters.
    const contestLink = screen.getByRole('link', { name: 'View this contest’s published returns' });
    expect(contestLink.getAttribute('href')).toContain('reporting_level=county');
  });

  it('uses the provided portrait only for a resolved authoritative identifier', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ ...candidateProfile,
      person: { id: candidacyId, full_name: 'OCASIO-CORTEZ, ALEXANDRIA' },
      label: 'OCASIO-CORTEZ, ALEXANDRIA', identity_status: 'resolved',
      finance: { ...candidateProfile.finance, fec_candidate_id: 'H8NY15148' },
    })));
    open();
    expect(await screen.findByRole('heading', { name: 'Alexandria Ocasio-Cortez' })).toBeVisible();
    expect(screen.getByRole('img', { name: 'Portrait of Alexandria Ocasio-Cortez' })).toBeVisible();
  });

  it('distinguishes not found from temporary failure and retries', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({}, 503)).mockResolvedValueOnce(response(candidateProfile));
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    open();
    expect(await screen.findByRole('heading', { name: 'Profile could not be loaded' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Identity & candidacy' })).toBeVisible();
  });

  it('shows a 404 without inventing a candidate identity', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({}, 404)));
    open();
    expect(await screen.findByRole('heading', { name: 'Candidate not found' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
  });

  it('requests bounded result pages using the reporting level', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ ...candidateProfile,
      results: { ...candidateProfile.results, total: 51, has_more: true, limit: 50 } }))
      .mockResolvedValue(response(candidateProfile));
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    open(`/candidates/${candidacyId}?reporting_level=congressional_district`);
    await user.click(await screen.findByRole('link', { name: 'Next page' }));
    expect(fetch.mock.calls.some(call => call[0] === `/api/v1/candidates/${candidacyId}?reporting_level=congressional_district&offset=50`)).toBe(true);
  });

  it('formats exact decimal cents and distinguishes missing from zero', () => {
    expect(dollars(null)).toBe('Not available');
    expect(dollars('0.00')).toBe('$0.00');
    expect(dollars('-1234.5')).toBe('-$1,234.50');
  });

  it('accepts uppercase UUID deep links and preserves the real House contest context', async () => {
    const id = 'abcdefab-abcd-4abc-8abc-abcdefabcdef';
    vi.stubGlobal('fetch', vi.fn(async () => response({ ...candidateProfile, id,
      contest: { ...candidateProfile.contest, election_date: '2024-11-05', election_cycle: 2024, office_name: 'U.S. House' },
      results: { ...candidateProfile.results, reporting_level: 'congressional_district' } })));
    open(`/candidates/${id.toUpperCase()}?year=2008`);
    await screen.findByRole('heading', { name: 'Identity & candidacy' });
    const link = screen.getByRole('link', { name: 'View this contest’s published returns' });
    expect(link.getAttribute('href')).toContain('year=2024');
    expect(link.getAttribute('href')).toContain('reporting_level=congressional_district');
  });
});
