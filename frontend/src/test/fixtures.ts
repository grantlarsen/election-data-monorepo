import type { CandidateProfile, Contest, Page, Publication, Result } from '../api';

export const contestId = '00000000-0000-4000-8000-000000000001';
export const candidacyId = '00000000-0000-4000-8000-000000000002';
export const jurisdictionId = '00000000-0000-4000-8000-000000000003';
export const publication: Publication = {
  batch_id: '00000000-0000-4000-8000-000000000004',
  scope_key: 'medsl:2008:TOTAL', status: 'PARTIAL', published_at: '2026-11-15T12:00:00Z',
  source: { release_id: '00000000-0000-4000-8000-000000000005', name: 'medsl_presidential_county',
    version: 'V20', sha256: 'a'.repeat(64), url: 'https://example.org/source.csv', retrieved_at: '2026-11-14T12:00:00Z' },
  reporting_levels: ['county'], reporting_modes: ['TOTAL'], reference_release_id: jurisdictionId,
  correction_batch_id: candidacyId,
  correction_source: { release_id: jurisdictionId, name: 'reviewed_county_corrections', version: 'v1',
    sha256: 'b'.repeat(64), url: 'https://example.org/corrections', retrieved_at: '2026-11-15T10:00:00Z' },
  input_rows: 100, accepted_rows: 90, excluded_rows: 10, coverage_scope: 'publication', county_coverage_verified: false,
};
export const contest: Contest = {
  id: contestId, election_id: jurisdictionId, election_date: '2008-11-04', stage: 'general', office_id: null,
  office_name: 'President of the United States',
  jurisdiction: { id: jurisdictionId, name: 'New York', level: 'state', state_code: 'NY' }, publications: [publication],
};
export const result: Result = {
  contest_id: contestId, election_id: jurisdictionId, election_date: '2008-11-04', stage: 'general',
  office_name: contest.office_name, jurisdiction: { id: jurisdictionId, name: 'Example County', level: 'county', state_code: 'NY' },
  reporting_level: 'county', reporting_mode: 'TOTAL', candidacy_id: candidacyId, person_id: null,
  candidate_kind: 'named', label: 'Example candidate', basis: 'candidate_total', votes: 0,
  geographic_reference_id: jurisdictionId, reference_vintage_start: 2008, reference_vintage_end: 2008,
  observation_ids: [jurisdictionId], correction_ids: [candidacyId], publication,
};
export function page<T>(items: T[], overrides: Partial<Page<T>> = {}): Page<T> {
  return { items, total: items.length, limit: 25, offset: 0, has_more: false,
    availability: items.length ? 'available' : 'no_matching_data', ...overrides };
}

export const candidateProfile: CandidateProfile = {
  id: candidacyId, label: result.label, source_label: result.label, candidate_kind: 'candidate',
  person: null, identity_status: 'pending_review', identity_evidence: [], identifiers: [], committees: [],
  contest: { ...contest, election_cycle: 2008 },
  finance: { status: 'identity_unresolved', cycle: 2008, total_raised: null, total_spent: null,
    reported_receipts: null, reported_disbursements: null, transfers_from_authorized: null,
    transfers_to_authorized: null, cash_on_hand: null, debts: null, coverage_end: null,
    definition: null, fec_candidate_id: null, source: null },
  results: { ...page([result]), reporting_level: 'county', reporting_mode: 'TOTAL' },
};
