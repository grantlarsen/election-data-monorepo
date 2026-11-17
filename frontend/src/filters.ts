export const states = ('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY').split(' ');
export const stages = ['general', 'primary', 'runoff', 'special', 'special_primary', 'special_runoff', 'other'];
export const levels = ['state', 'county', 'congressional_district', 'legislative_district', 'precinct', 'place'];
export const filterKeys = ['year', 'office', 'stage', 'state_code', 'jurisdiction_id', 'reporting_level'] as const;
export const isUuid = (value: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export const humanize = (value: string) => value.replaceAll('_', ' ');

/** Shared selection excludes page offsets and selected contest/candidacy context. */
export function filterSearch(params: URLSearchParams): string {
  const shared = new URLSearchParams();
  for (const key of filterKeys) {
    const value = params.get(key);
    if (value) shared.set(key, value);
  }
  return shared.size ? `?${shared}` : '';
}

export function validateSearch(params: URLSearchParams): string | null {
  const year = params.get('year');
  if (year && (!/^\d{1,4}$/.test(year) || +year < 1 || +year > 9998)) return 'Year must be between 1 and 9998.';
  const office = params.get('office');
  if (office && (!office.trim() || office.trim().length > 200)) return 'Office must contain 1 to 200 characters.';
  const state = params.get('state_code');
  if (state && !states.includes(state.toUpperCase())) return 'Choose a valid state or DC.';
  const stage = params.get('stage');
  if (stage && !stages.includes(stage)) return 'Choose a supported election stage.';
  const level = params.get('reporting_level');
  if (level && !levels.includes(level)) return 'Choose a supported reporting level.';
  for (const field of ['jurisdiction_id', 'contest_id']) {
    const value = params.get(field);
    if (value && !isUuid(value)) return 'Geographic and contest identifiers must be valid UUIDs.';
  }
  const offset = params.get('offset');
  if (offset && (!/^\d+$/.test(offset) || !Number.isSafeInteger(+offset))) return 'Page offset must be a nonnegative integer.';
  for (const key of [...filterKeys, 'contest_id', 'offset']) {
    if (params.getAll(key).length > 1) return 'Each filter must appear only once in the URL.';
  }
  return null;
}

export function apiQuery(params: URLSearchParams, endpoint: 'contests' | 'results', contestId?: string): string {
  const query = new URLSearchParams(filterSearch(params).slice(1));
  query.delete('reporting_level');
  if (endpoint === 'results') {
    query.set('reporting_level', params.get('reporting_level') || 'county');
    query.set('reporting_mode', 'TOTAL');
  }
  if (contestId) query.set('contest_id', contestId);
  query.set('limit', '25');
  query.set('offset', params.get('offset') || '0');
  return query.toString();
}
