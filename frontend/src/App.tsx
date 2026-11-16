import { ElectionMapPage } from './map/ElectionMapPage';
import { useEffect, useState } from 'react';
import { Link, Navigate, NavLink, Route, Routes, useLocation, useParams, useSearchParams } from 'react-router';
import type { Contest, Page, Result } from './api';
import { apiQuery, filterSearch, humanize, isUuid, validateSearch } from './filters';
import { FilterLink, Filters, FirstPageLink, Notice, Pagination, Provenance, RouteFocus, usePage } from './components';

function Title({ title, children }: { title: string; children: React.ReactNode }) {
  return <header className="page-heading"><p className="eyebrow">US elections · Research workspace</p><h1 id="page-title" tabIndex={-1}>{title}</h1><p>{children}</p></header>;
}

function DataState<T>({ page, error, retry, empty, children }: {
  page?: Page<T>; error?: string; retry: () => void; empty: string; children: (page: Page<T>) => React.ReactNode;
}) {
  if (error) return <Notice title="Data could not be loaded" error><p>{error}</p><button onClick={retry}>Try again</button></Notice>;
  if (!page) return <Notice title="Loading published data"><p>Please wait while we retrieve the current publication.</p></Notice>;
  if (page.total === 0) return <Notice title="No matching data"><p>{empty}</p><p>Try a different year, office or geography. An absent record does not mean zero votes.</p></Notice>;
  if (!page.items.length) return <><Notice title="No records on this page"><p>The page offset is beyond the matching records.</p><FirstPageLink /></Notice><Pagination page={page} /></>;
  return children(page);
}

function ContestPage() {
  const [params] = useSearchParams();
  const error = validateSearch(params);
  const data = usePage<Contest>('contests', apiQuery(params, 'contests'), !error);
  return <><Title title="Contests">Discover election contests. Publication labels describe the source coverage behind each record.</Title>
    {error ? <Notice title="Review your filters" error><p>{error}</p></Notice> : <DataState {...data} empty="No modeled contests match this selection.">{page => <>
      <p className="result-count">{page.total.toLocaleString('en-US')} matching contests</p>
      <div className="record-list">{page.items.map(contest => <article className="record" key={contest.id}>
        <div className="record-heading"><div><p className="eyebrow">{contest.election_date} · {humanize(contest.stage)}</p><h2><FilterLink to={`/contests/${contest.id}`}>{contest.office_name}</FilterLink></h2><p>{contest.jurisdiction.name} · {humanize(contest.jurisdiction.level)}</p></div><span className="record-type">Contest</span></div>
        <Provenance publications={contest.publications} />
      </article>)}</div><Pagination page={page} />
    </>}</DataState>}
  </>;
}

function ResultsPage() {
  const { contestId } = useParams();
  const [params] = useSearchParams();
  const error = validateSearch(params) || (contestId && !isUuid(contestId) ? 'The contest identifier must be a valid UUID.' : null);
  const data = usePage<Result>('results', apiQuery(params, 'results', contestId), !error);
  return <><Title title={contestId ? 'Contest returns' : 'Candidates & returns'}>Published returns at one reporting level. Each row belongs to a specific reporting unit.</Title>
    {contestId && <div className="selection-context"><FilterLink to="/contests">← All contests</FilterLink><p>Contest ID: <code>{contestId}</code></p></div>}
    <p className="data-note">Showing {humanize(params.get('reporting_level') || 'county')} returns in TOTAL mode. State authority totals are a separate, non-additive source. No cross-geography totals are calculated here.</p>
    {error ? <Notice title="Review your filters" error><p>{error}</p></Notice> : <DataState {...data} empty="No published returns match this selection. A contest may exist without published results.">{page => {
      const publications = [...new Map(page.items.map(item => [item.publication.batch_id, item.publication])).values()];
      return <>
        <p className="result-count">{page.total.toLocaleString('en-US')} matching result records · candidate names can appear in multiple reporting units</p>
        <section className="source-panel" aria-labelledby="sources-heading"><h2 id="sources-heading">Sources on this page</h2><p>Coverage counts apply to entire publications. Separate pages can reflect newer publications if source pointers change.</p><Provenance publications={publications} /></section>
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Published returns table"><table>
          <caption>Published {humanize(params.get('reporting_level') || 'county')} returns — individual reporting units</caption>
          <thead><tr><th scope="col">Candidate / source bucket</th><th scope="col">Contest & geography</th><th scope="col" className="number">Votes</th><th scope="col">Reference & lineage</th></tr></thead>
          <tbody>{page.items.map(item => {
            const candidateQuery = new URLSearchParams(filterSearch(params).slice(1));
            candidateQuery.set('contest_id', item.contest_id);
            return <tr key={`${item.publication.batch_id}:${item.contest_id}:${item.jurisdiction.id}:${item.candidacy_id ?? item.observation_ids.join(',')}`}>
              <th scope="row">{item.candidacy_id ? <Link to={`/candidates/${item.candidacy_id}?${candidateQuery}`}>{item.label}</Link> : <>{item.label}<span className="cell-note">Anonymous {humanize(item.basis)} bucket · no person identity</span></>}<span className="cell-note">{humanize(item.basis)}</span></th>
              <td><FilterLink to={`/contests/${item.contest_id}`}>{item.office_name}</FilterLink><span className="cell-note">{item.election_date} · {humanize(item.stage)}</span><span className="cell-note">{item.jurisdiction.name} ({item.jurisdiction.state_code}) · {humanize(item.reporting_level)}</span></td>
              <td className="number">{item.votes.toLocaleString('en-US')}</td>
              <td><span>Reference vintage: {item.reference_vintage_start}–{item.reference_vintage_end}</span><span className="cell-note">Statistical reference; legal boundary dates may differ.</span>
                <details><summary>Record identifiers</summary><dl><dt>Geographic reference</dt><dd>{item.geographic_reference_id}</dd><dt>Jurisdiction</dt><dd>{item.jurisdiction.id}</dd><dt>Publication batch</dt><dd>{item.publication.batch_id}</dd><dt>Observations</dt><dd>{item.observation_ids.join(', ')}</dd>{item.correction_ids.length > 0 && <><dt>Corrections</dt><dd>{item.correction_ids.join(', ')}</dd></>}</dl></details>
              </td>
            </tr>;
          })}</tbody>
        </table></div>
        <Pagination page={page} />
      </>;
    }}</DataState>}
  </>;
}

function CandidatePage() {
  const { candidacyId = '' } = useParams();
  const [params] = useSearchParams();
  const contestId = params.get('contest_id');
  const error = validateSearch(params) || (!isUuid(candidacyId) ? 'The candidacy identifier must be a valid UUID.' : null);
  return <><Title title="Candidate selection">A candidacy identifies a candidate in one contest. It is distinct from a person or campaign committee.</Title>
    {error ? <Notice title="Invalid selection" error><p>{error}</p></Notice> : <>
      <div className="selection-context"><p>Candidacy ID: <code>{candidacyId}</code></p>{contestId && <FilterLink to={`/contests/${contestId}`}>View this contest’s published returns</FilterLink>}</div>
      <Notice title="Full candidate profile is not available yet"><p>This selection preserves the candidacy and your filters. The identifier has not been verified against a published profile record.</p><p>Person identity, linked committees and campaign finance will appear when source-backed profiles are available.</p><FilterLink to="/candidates">Browse published candidate returns</FilterLink></Notice>
    </>}
  </>;
}

function NotFound() {
  return <><Title title="Page not found">This address does not match a research page.</Title><FilterLink to="/map">Return to the explorer</FilterLink></>;
}

export function App() {
  const [params] = useSearchParams();
  const location = useLocation();
  const [filterPanel, setFilterPanel] = useState({ locationKey: location.key, open: false });
  const filtersOpen = filterPanel.locationKey === location.key && filterPanel.open;
  useEffect(() => {
    setFilterPanel({ locationKey: location.key, open: false });
  }, [location.key]);
  const search = filterSearch(params);
  return <>
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <header className="site-header"><Link className="brand" to={`/map${search}`} aria-label="Electoral Atlas home"><span className="brand-mark" aria-hidden="true">E/A</span><span>Electoral Atlas</span></Link>
      <div className="header-actions"><nav className="primary-nav" aria-label="Primary navigation">{[['/map', 'Map'], ['/contests', 'Contests'], ['/candidates', 'Candidates']].map(([to, label]) => <NavLink key={to} to={`${to}${search}`}>{label}</NavLink>)}</nav>
        <button type="button" className="filter-toggle" aria-expanded={filtersOpen} aria-controls="election-filters" onClick={() => setFilterPanel({ locationKey: location.key, open: !filtersOpen })}>{filtersOpen ? 'Hide filters' : 'Show filters'}</button>
      </div>
    </header>
    <div className={`workspace${filtersOpen ? ' filters-open' : ''}`}>
      <Filters open={filtersOpen} /><main id="main-content" className={location.pathname === '/map' ? 'map-page' : undefined} tabIndex={-1}><RouteFocus />
      <Routes>
        <Route path="/" element={<Navigate to={`/map${search || '?year=2008'}`} replace />} />
        <Route path="/map" element={<ElectionMapPage />} />
        <Route path="/contests" element={<ContestPage />} />
        <Route path="/contests/:contestId" element={<ResultsPage />} />
        <Route path="/candidates" element={<ResultsPage />} />
        <Route path="/candidates/:candidacyId" element={<CandidatePage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      <div className="selection-strip" role="group" aria-label="Applied filters"><span>{params.get('year') || 'All years'}</span><span>{params.get('office') || 'All offices'}</span><span>{params.get('state_code')?.toUpperCase() || 'All states and DC'}</span><span>{humanize(params.get('stage') || 'All stages')}</span><span>{humanize(params.get('reporting_level') || 'county')} reporting</span></div>
    </main></div>
    <footer className="site-footer">Election research with historical geography and source context. Missing records never imply zero votes.</footer>
  </>;
}
