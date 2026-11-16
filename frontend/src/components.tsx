import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router';
import { ApiError, fetchPage, sourceUrl } from './api';
import type { Page, Publication, Source } from './api';
import { filterKeys, filterSearch, humanize, levels, stages, states } from './filters';

export function Filters({ open }: { open: boolean }) {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const key of filterKeys) {
      const value = String(form.get(key) ?? '').trim();
      if (value) next.set(key, key === 'state_code' ? value.toUpperCase() : value);
    }
    navigate(`/${location.pathname.split('/')[1]}?${next}`);
  }
  return <aside id="election-filters" className="filter-panel" hidden={!open} aria-labelledby="filters-heading">
    <div className="panel-heading"><h2 id="filters-heading">Filters</h2></div>
    <form key={params.toString()} onSubmit={apply}>
      <label>Election year<input type="number" name="year" min="1" max="9998" step="1" placeholder="All years" defaultValue={params.get('year') ?? ''} /></label>
      <label>Office<input name="office" list="offices" maxLength={200} placeholder="All offices" defaultValue={params.get('office') ?? ''} aria-describedby="office-help" /></label>
      <datalist id="offices"><option value="U.S. President" /><option value="U.S. House" /></datalist>
      <p className="field-help" id="office-help">Use the exact office name shown on a contest.</p>
      <label>Election stage<select name="stage" defaultValue={params.get('stage') ?? ''}><option value="">All stages</option>{stages.map(stage => <option key={stage} value={stage}>{humanize(stage)}</option>)}</select></label>
      <label>State or DC<select name="state_code" defaultValue={params.get('state_code')?.toUpperCase() ?? ''}><option value="">All states and DC</option>{states.map(state => <option key={state}>{state}</option>)}</select></label>
      <label>Reporting level<select name="reporting_level" defaultValue={params.get('reporting_level') ?? 'county'}>{levels.map(level => <option key={level} value={level}>{humanize(level)}</option>)}</select></label>
      {location.pathname !== '/map' && <details><summary>Specific reporting unit</summary><label>Jurisdiction UUID<input name="jurisdiction_id" defaultValue={params.get('jurisdiction_id') ?? ''} placeholder="Optional canonical UUID" /></label><p className="field-help">Selects an exact reporting unit for returns. State selection scopes discovery without aggregating counties.</p></details>}
      <button type="submit">Apply filters</button>
      <Link className="reset-link" to={location.pathname.split('/').slice(0, 2).join('/')}>Clear filters</Link>
    </form>
    <p className="filter-note">Year refers to the election date. Changing filters returns to the section overview.</p>
  </aside>;
}

export function RouteFocus() {
  const { pathname } = useLocation();
  const previous = useRef(pathname);
  useEffect(() => {
    document.title = `${pathname.startsWith('/contests') ? 'Contests' : pathname.startsWith('/candidates') ? 'Candidates' : 'Map'} | Electoral Atlas`;
    if (previous.current !== pathname) document.getElementById('page-title')?.focus();
    previous.current = pathname;
  }, [pathname]);
  return null;
}

type LoadState<T> = { key: string; page?: Page<T>; error?: string };

export function usePage<T>(endpoint: 'contests' | 'results', query: string, enabled = true) {
  const [attempt, setAttempt] = useState(0);
  const key = `${endpoint}?${query}&attempt=${attempt}`;
  const [state, setState] = useState<LoadState<T>>({ key: '' });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let current = true;
    fetchPage<T>(endpoint, query, controller.signal).then(page => {
      if (current) setState({ key, page });
    }).catch(error => {
      if (current && !controller.signal.aborted) setState({ key, error: error instanceof ApiError
        ? error.message : 'Unable to load published data. Check your connection and try again.' });
    });
    return () => { current = false; controller.abort(); };
  }, [endpoint, query, key, enabled]);
  return { page: state.key === key ? state.page : undefined,
    error: state.key === key ? state.error : undefined,
    retry: () => setAttempt(value => value + 1) };
}

export function FirstPageLink() {
  const [params] = useSearchParams();
  const next = new URLSearchParams(params);
  next.delete('offset');
  return <Link to={`?${next}`}>Return to the first page</Link>;
}

export function Notice({ title, children, error = false }: { title: string; children: React.ReactNode; error?: boolean }) {
  return <section className={`notice ${error ? 'notice-error' : ''}`} role={error ? 'alert' : 'status'}>
    <h2>{title}</h2>{children}
  </section>;
}

function SourceDetails({ source }: { source: Source }) {
  const url = sourceUrl(source.url);
  return <div className="source-details">
    <p>{url ? <a href={url} target="_blank" rel="noreferrer">{source.name} — source download</a> : source.name} · Version {source.version}</p>
    <dl><dt>Release</dt><dd>{source.release_id}</dd><dt>Retrieved</dt><dd>{source.retrieved_at}</dd><dt>SHA-256</dt><dd>{source.sha256}</dd></dl>
  </div>;
}

export function Provenance({ publications }: { publications: Publication[] }) {
  if (!publications.length) return <p className="coverage-label">No published returns</p>;
  return <div className="provenance">{publications.map(publication => <div key={publication.batch_id}>
    <p className="coverage-label"><span className={`badge ${publication.status === 'PARTIAL' ? 'badge-partial' : ''}`}>{publication.status === 'PARTIAL' ? 'Partial publication' : 'Complete publication'}</span> {publication.source.name} · {publication.source.version}</p>
    {publication.status === 'PARTIAL' && <p className="coverage-warning">Coverage is incomplete. Missing returns are not zero votes.</p>}
    {publication.reporting_levels.includes('county') && !publication.county_coverage_verified && <p className="coverage-warning">County coverage has not been independently verified.</p>}
    <details><summary>Source and publication details</summary>
      <SourceDetails source={publication.source} />
      <dl><dt>Published</dt><dd>{publication.published_at}</dd><dt>Batch</dt><dd>{publication.batch_id}</dd><dt>Scope</dt><dd>{publication.scope_key}</dd><dt>Reporting</dt><dd>{publication.reporting_levels.join(', ')} · {publication.reporting_modes.join(', ')}</dd>
        {publication.reference_release_id && <><dt>Geographic reference release</dt><dd>{publication.reference_release_id}</dd></>}
        {publication.input_rows !== null && <><dt>Publication coverage</dt><dd>{publication.accepted_rows?.toLocaleString('en-US')} accepted / {publication.input_rows.toLocaleString('en-US')} input rows; {publication.excluded_rows?.toLocaleString('en-US')} excluded. Counts describe the entire publication, across all filters and pages.</dd></>}
        {publication.correction_batch_id && <><dt>Correction batch</dt><dd>{publication.correction_batch_id}</dd></>}
      </dl>
      {publication.correction_source && <><h3>Reviewed correction source</h3><SourceDetails source={publication.correction_source} /></>}
    </details>
  </div>)}</div>;
}

export function Pagination({ page }: { page: Page<unknown> }) {
  const [params] = useSearchParams();
  function target(offset: number) {
    const next = new URLSearchParams(params);
    if (offset) next.set('offset', String(offset)); else next.delete('offset');
    return `?${next}`;
  }
  return <nav className="pagination" aria-label="Results pages">
    {page.offset > 0 && <Link to={target(Math.max(0, page.offset - page.limit))}>Previous page</Link>}
    <span>{page.items.length ? `${page.offset + 1}–${page.offset + page.items.length}` : '0'} of {page.total.toLocaleString('en-US')} records</span>
    {page.has_more && <Link to={target(page.offset + page.limit)}>Next page</Link>}
  </nav>;
}

export function FilterLink({ to, children }: { to: string; children: React.ReactNode }) {
  const [params] = useSearchParams();
  return <Link to={`${to}${filterSearch(params)}`}>{children}</Link>;
}
