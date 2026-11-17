import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router';
import { ApiError, fetchPage, sourceUrl } from './api';
import type { Page, Publication, Source } from './api';
import { filterSearch } from './filters';
import { presidentialYear } from './presidential';

export function RouteFocus() {
  const { pathname } = useLocation();
  const previous = useRef(pathname);
  useEffect(() => {
    document.title = `${document.getElementById('page-title')?.textContent || (pathname.startsWith('/presidential') ? `${presidentialYear(pathname) || ''} Presidential elections`.trim() : pathname.startsWith('/contests') ? 'Contests' : pathname.startsWith('/candidates') ? 'Candidates' : 'Map')} | Electoral Atlas`;
    if (previous.current !== pathname) document.getElementById('page-title')?.focus();
    previous.current = pathname;
  }, [pathname]);
  return null;
}

type LoadState<T> = { key: string; page?: Page<T>; error?: string };

export function usePage<T>(endpoint: 'contests' | 'results' | 'state-results', query: string, enabled = true) {
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

export function SourceDetails({ source }: { source: Source }) {
  const url = sourceUrl(source.url);
  return <div className="source-details">
    <p>{url ? <a href={url} target="_blank" rel="noreferrer">{source.name} — source download</a> : source.name} · Version {source.version}</p>
    <dl><dt>Release</dt><dd>{source.release_id}</dd><dt>Retrieved</dt><dd>{source.retrieved_at}</dd><dt>SHA-256</dt><dd>{source.sha256}</dd></dl>
  </div>;
}

export function Provenance({ publications, collapsible = true }: { publications: Publication[]; collapsible?: boolean }) {
  const Details = collapsible ? 'details' : 'div';
  if (!publications.length) return <p className="coverage-label">No published returns</p>;
  return <div className="provenance">{publications.map(publication => <div key={publication.batch_id}>
    <p className="coverage-label"><span className={`badge ${publication.status === 'PARTIAL' ? 'badge-partial' : ''}`}>{publication.status === 'PARTIAL' ? 'Partial publication' : 'Complete publication'}</span> {publication.source.name} · {publication.source.version}</p>
    {publication.status === 'PARTIAL' && <p className="coverage-warning">Coverage is incomplete. Missing returns are not zero votes.</p>}
    {publication.reporting_levels.includes('county') && !publication.county_coverage_verified && <p className="coverage-warning">County coverage has not been independently verified.</p>}
    <Details>{collapsible && <summary>Source and publication details</summary>}
      <SourceDetails source={publication.source} />
      <dl><dt>Published</dt><dd>{publication.published_at}</dd><dt>Batch</dt><dd>{publication.batch_id}</dd><dt>Scope</dt><dd>{publication.scope_key}</dd><dt>Reporting</dt><dd>{publication.reporting_levels.join(', ')} · {publication.reporting_modes.join(', ')}</dd>
        {publication.reference_release_id && <><dt>Geographic reference release</dt><dd>{publication.reference_release_id}</dd></>}
        {publication.input_rows !== null && <><dt>Publication coverage</dt><dd>{publication.accepted_rows?.toLocaleString('en-US')} accepted / {publication.input_rows.toLocaleString('en-US')} input rows; {publication.excluded_rows?.toLocaleString('en-US')} excluded. Counts describe the entire publication, across all filters and pages.</dd></>}
        {publication.correction_batch_id && <><dt>Correction batch</dt><dd>{publication.correction_batch_id}</dd></>}
      </dl>
      {publication.correction_source && <><h3>Reviewed correction source</h3><SourceDetails source={publication.correction_source} /></>}
    </Details>
  </div>)}</div>;
}

export function Pagination({ page, onPageChange }: { page: Page<unknown>; onPageChange?: (offset: number) => void }) {
  const [params] = useSearchParams();
  function target(offset: number) {
    const next = new URLSearchParams(params);
    if (offset) next.set('offset', String(offset)); else next.delete('offset');
    return `?${next}`;
  }
  return <nav className="pagination" aria-label="Results pages">
    {page.offset > 0 && (onPageChange
      ? <button onClick={() => onPageChange(Math.max(0, page.offset - page.limit))}>Previous page</button>
      : <Link to={target(Math.max(0, page.offset - page.limit))}>Previous page</Link>)}
    <span>{page.items.length ? `${page.offset + 1}–${page.offset + page.items.length}` : '0'} of {page.total.toLocaleString('en-US')} records</span>
    {page.has_more && (onPageChange
      ? <button onClick={() => onPageChange(page.offset + page.limit)}>Next page</button>
      : <Link to={target(page.offset + page.limit)}>Next page</Link>)}
  </nav>;
}

export function FilterLink({ to, children }: { to: string; children: React.ReactNode }) {
  const [params] = useSearchParams();
  return <Link to={`${to}${filterSearch(params)}`}>{children}</Link>;
}

export function Title({ title, children }: { title: string; children: React.ReactNode }) {
  return <header className="page-heading"><p className="eyebrow">US elections · Research workspace</p><h1 id="page-title" tabIndex={-1}>{title}</h1><p>{children}</p></header>;
}

export function DataState<T>({ page, error, retry, empty, children }: {
  page?: Page<T>; error?: string; retry: () => void; empty: string; children: (page: Page<T>) => React.ReactNode;
}) {
  if (error) return <Notice title="Data could not be loaded" error><p>{error}</p><button onClick={retry}>Try again</button></Notice>;
  if (!page) return <Notice title="Loading published data"><p>Please wait while we retrieve the current publication.</p></Notice>;
  if (page.total === 0) return <Notice title="No matching data"><p>{empty}</p><p>Try a different year, office or geography. An absent record does not mean zero votes.</p></Notice>;
  if (!page.items.length) return <><Notice title="No records on this page"><p>The page offset is beyond the matching records.</p><FirstPageLink /></Notice><Pagination page={page} /></>;
  return children(page);
}
