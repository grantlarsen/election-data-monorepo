export const presidentialYears = [2000, 2004, 2008, 2012, 2016, 2020, 2024] as const;

export function presidentialYear(pathname: string): number | undefined {
  const match = /^\/presidential\/(\d{4})\/?$/.exec(pathname);
  const year = match ? Number(match[1]) : undefined;
  return presidentialYears.find(value => value === year);
}

/** Route context takes precedence over unrelated explorer filters. */
export function presidentialParams(year: number, params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams({ year: String(year), office: 'U.S. President', stage: 'general' });
  for (const key of ['state_code', 'jurisdiction_id', 'reporting_level', 'offset']) {
    for (const value of params.getAll(key)) if (value) next.append(key, value);
  }
  if (!next.has('reporting_level')) next.set('reporting_level', 'state');
  return next;
}
