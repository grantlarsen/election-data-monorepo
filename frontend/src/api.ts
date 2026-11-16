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

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  availability: 'available' | 'no_matching_data' | 'no_matching_published_results';
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

export async function fetchPage<T>(endpoint: 'contests' | 'results', query: string, signal: AbortSignal): Promise<Page<T>> {
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

/** Only public web links from source metadata become clickable. */
export function sourceUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
  } catch { return undefined; }
}
