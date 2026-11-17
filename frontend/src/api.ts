/** Public read models mirror backend/app/api/election_schemas.py. */
export interface Geography {
  id: string;
  name: string;
  level: string;
  state_code: string | null;
}

export interface Source {
  release_id: string;
  name: string;
  version: string;
  sha256: string;
  url: string;
  retrieved_at: string;
}

export interface Publication {
  batch_id: string;
  scope_key: string;
  status: 'COMPLETE' | 'PARTIAL';
  published_at: string;
  source: Source;
  reporting_levels: string[];
  reporting_modes: string[];
  reference_release_id: string | null;
  correction_batch_id: string | null;
  correction_source: Source | null;
  input_rows: number | null;
  accepted_rows: number | null;
  excluded_rows: number | null;
  coverage_scope: 'publication';
  county_coverage_verified: boolean;
}

export interface Contest {
  id: string;
  election_id: string;
  election_date: string;
  stage: string;
  office_id: string | null;
  office_name: string;
  jurisdiction: Geography;
  publications: Publication[];
}

export interface Result {
  contest_id: string;
  election_id: string;
  election_date: string;
  stage: string;
  office_name: string;
  jurisdiction: Geography;
  reporting_level: string;
  reporting_mode: string;
  candidacy_id: string | null;
  person_id: string | null;
  candidate_kind: string;
  label: string;
  basis: 'candidate_total' | 'ballot_line' | 'write_in' | 'aggregate';
  votes: number;
  geographic_reference_id: string;
  reference_vintage_start: number;
  reference_vintage_end: number;
  observation_ids: string[];
  correction_ids: string[];
  publication: Publication;
}

/** State authority buckets are separate from canonical candidate identities. */
export interface StateResult {
  contest_id: string;
  election_id: string;
  election_date: string;
  jurisdiction: Geography;
  candidate_bucket: string;
  bucket_kind: 'source_candidate' | 'aggregate';
  votes: number;
  source_locator: string;
  source_adjustment: number | null;
  publication: Publication;
}

/** Read-only subset of /api/v1/presidential-coverage used by election pages. */
export interface PresidentialCoverage {
  year: number;
  election_date: string;
  county_coverage_verified: boolean;
  county: {
    availability: 'published' | 'missing_publication';
    status: 'COMPLETE' | 'PARTIAL' | null;
    source_release_id: string | null;
    matches_active_source: boolean;
    accepted_rows: number;
    excluded_rows: number | null;
    missing_states: string[];
    exclusions: { state_code: string; code: string; rows: number }[];
  };
  state: { availability: 'published' | 'missing_publication' };
  states: {
    state_code: string;
    county: { rows: number; votes: number; reporting_units: number } | null;
    official_votes: number | null;
    state_minus_published_county_votes: number | null;
  }[];
  limitations: string[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  availability: 'available' | 'no_matching_data' | 'no_matching_published_results';
}

export interface CandidateProfile {
  provisional_house_election?: import('./house').ProvisionalHouseElection | null;
  provisional_election?: import('./senate').ProvisionalSenateElection | null;
  id: string;
  label: string | null;
  source_label: string | null;
  candidate_kind: string;
  person: { id: string; full_name: string } | null;
  identity_status: 'resolved' | 'pending_review' | 'unresolved';
  identity_evidence: { status: string; confidence: string; evidence: Record<string, unknown>;
    decision_evidence: string | null; decided_at: string | null; record_id: string | null;
    fec_candidate_id: string | null; source: Source }[];
  identifiers: { namespace: string; identifier_type: string; value: string; evidence: string | null; source: Source | null; source_id: string }[];
  contest: { id: string; election_id: string; election_date: string; stage: string; election_cycle: number; office_name: string; jurisdiction: Geography };
  latest_election?: CandidateProfile['contest'] & { candidacy_id: string } | null;
  committees: { id: string; name: string; role: string; cycle: number; fec_ids: string[]; evidence: string | null; source: Source | null; source_id: string }[];
  finance: {
    status: 'available' | 'partial' | 'missing' | 'identity_unresolved' | 'ambiguous';
    cycle: number;
    total_raised: string | null;
    total_spent: string | null;
    reported_receipts: string | null;
    reported_disbursements: string | null;
    transfers_from_authorized: string | null;
    transfers_to_authorized: string | null;
    cash_on_hand: string | null;
    debts: string | null;
    coverage_end: string | null;
    definition: string | null;
    fec_candidate_id: string | null;
    source: Source | null;
  };
  results: Page<Result> & { reporting_level: string; reporting_mode: string };
}

export async function fetchCandidate(id: string, query: string, signal: AbortSignal): Promise<CandidateProfile> {
  const response = await fetch(`/api/v1/candidates/${id}?${query}`, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new ApiError(response.status, response.status === 404
    ? 'This candidacy was not found. Check the profile address or browse published returns.'
    : 'The candidate profile is temporarily unavailable. Please try again.');
  const profile: CandidateProfile = await response.json();
  if (profile.id?.toLowerCase() !== id.toLowerCase() || !profile.contest || !profile.finance || !profile.results ||
      !Array.isArray(profile.results.items) || !Array.isArray(profile.committees) ||
      !Array.isArray(profile.identifiers) || !Array.isArray(profile.identity_evidence)) throw new Error('Unexpected candidate profile response');
  return profile;
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

export async function fetchPage<T>(endpoint: 'contests' | 'results' | 'state-results', query: string, signal: AbortSignal): Promise<Page<T>> {
  const response = await fetch(`/api/v1/${endpoint}?${query}`, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) {
    throw new ApiError(response.status, response.status === 422
      ? 'The API could not accept these filters. Review your selection.'
      : 'Published data is temporarily unavailable. Please try again.');
  }
  const page: Page<T> = await response.json();
  if (!Array.isArray(page.items) || !Number.isInteger(page.total) || page.total < 0 ||
      !Number.isInteger(page.limit) || page.limit < 1 || !Number.isInteger(page.offset) ||
      page.offset < 0 || typeof page.has_more !== 'boolean' ||
      !['available', 'no_matching_data', 'no_matching_published_results'].includes(page.availability)) {
    throw new Error('Unexpected API response');
  }
  return page;
}

export async function fetchPresidentialCoverage(signal: AbortSignal): Promise<PresidentialCoverage[]> {
  const response = await fetch('/api/v1/presidential-coverage', { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new ApiError(response.status, 'Presidential coverage is temporarily unavailable. Please try again.');
  const body = await response.json();
  const count = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
  // PostgreSQL SUM(bigint) is Decimal; FastAPI encodes these inventory values as strings.
  // Accept integer strings only, and validate safety before converting for presentation.
  const numeric = (value: unknown) => typeof value === 'string' && /^-?\d+$/.test(value) ? Number(value) : value;
  if (!Array.isArray(body?.elections) || body.elections.some((item: PresidentialCoverage) =>
    !item || !Number.isInteger(item.year) || typeof item.election_date !== 'string' ||
    !item.county || !item.state || !['published', 'missing_publication'].includes(item.county.availability) ||
    !['published', 'missing_publication'].includes(item.state.availability) ||
    ![null, 'COMPLETE', 'PARTIAL'].includes(item.county.status) ||
    typeof item.county.matches_active_source !== 'boolean' || typeof item.county_coverage_verified !== 'boolean' ||
    !count(item.county.accepted_rows) || !(item.county.excluded_rows === null || count(item.county.excluded_rows)) ||
    !Array.isArray(item.county.missing_states) || item.county.missing_states.some(state => typeof state !== 'string') ||
    !Array.isArray(item.county.exclusions) || item.county.exclusions.some(exclusion =>
      !exclusion || typeof exclusion.code !== 'string' || typeof exclusion.state_code !== 'string' || !count(exclusion.rows)) ||
    !Array.isArray(item.limitations) || item.limitations.some(note => typeof note !== 'string') ||
    !Array.isArray(item.states) || item.states.some(state => !state || typeof state.state_code !== 'string' ||
      !(state.official_votes === null || count(state.official_votes)) ||
      !(state.state_minus_published_county_votes === null || Number.isSafeInteger(numeric(state.state_minus_published_county_votes))) ||
      !(state.county === null || (state.county && count(numeric(state.county.votes)) && count(state.county.rows) && count(state.county.reporting_units))))) ||
    new Set(body.elections.map((item: PresidentialCoverage) => item.year)).size !== body.elections.length) {
    throw new Error('Unexpected presidential coverage response');
  }
  return body.elections.map((item: PresidentialCoverage) => ({ ...item, states: item.states.map(state => ({ ...state,
    county: state.county ? { ...state.county, votes: Number(state.county.votes) } : null,
    state_minus_published_county_votes: state.state_minus_published_county_votes === null
      ? null : Number(state.state_minus_published_county_votes),
  })) }));
}

/** Only public web links from source metadata become clickable. */
export function sourceUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
  } catch { return undefined; }
}
