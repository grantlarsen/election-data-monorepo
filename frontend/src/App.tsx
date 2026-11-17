import { ElectionMapPage } from './map/ElectionMapPage';
import { CandidatePage } from './CandidatePage';
import { ResultsPage } from './ResultsPage';
import { PresidentialPage, PresidentialDiscovery } from './PresidentialPage';
import { presidentialParams, presidentialYear } from './presidential';
import { useEffect, useState } from 'react';
import { Link, Navigate, NavLink, Route, Routes, useLocation, useSearchParams } from 'react-router';
import type { Contest } from './api';
import { apiQuery, filterSearch, humanize, validateSearch } from './filters';
import { DataState, FilterLink, Filters, Notice, Pagination, Provenance, RouteFocus, Title, usePage } from './components';

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

function NotFound() {
  return <><Title title="Page not found">This address does not match a research page.</Title><FilterLink to="/map">Return to the explorer</FilterLink></>;
}

export function App() {
  const [urlParams] = useSearchParams();
  const location = useLocation();
  const year = presidentialYear(location.pathname);
  const params = year ? presidentialParams(year, urlParams) : urlParams;
  const [filterPanel, setFilterPanel] = useState({ locationKey: location.key, open: false });
  const filtersOpen = filterPanel.locationKey === location.key && filterPanel.open;
  useEffect(() => {
    setFilterPanel({ locationKey: location.key, open: false });
  }, [location.key]);
  const shared = new URLSearchParams(params);
  // General returns use county/district grain; state authority is separate.
  if (year && shared.get('reporting_level') === 'state') shared.delete('reporting_level');
  const search = filterSearch(shared);
  return <>
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <header className="site-header"><Link className="brand" to={`/map${search}`} aria-label="Electoral Atlas home"><span className="brand-mark" aria-hidden="true">E/A</span><span>Electoral Atlas</span></Link>
      <div className="header-actions"><nav className="primary-nav" aria-label="Primary navigation">{[['/map', 'Map'], ['/presidential', 'Presidential'], ['/contests', 'Contests'], ['/candidates', 'Candidates']].map(([to, label]) => <NavLink key={to} to={`${to}${search}`}>{label}</NavLink>)}</nav>
        <button type="button" className="filter-toggle" aria-expanded={filtersOpen} aria-controls="election-filters" onClick={() => setFilterPanel({ locationKey: location.key, open: !filtersOpen })}>{filtersOpen ? 'Hide filters' : 'Show filters'}</button>
      </div>
    </header>
    <div className={`workspace${filtersOpen ? ' filters-open' : ''}`}>
      <Filters open={filtersOpen} /><main id="main-content" className={location.pathname === '/map' ? 'map-page' : location.pathname.startsWith('/candidates/') ? 'candidate-page' : undefined} tabIndex={-1}><RouteFocus />
      <Routes>
        <Route path="/" element={<Navigate to={`/map${search || '?year=2008'}`} replace />} />
        <Route path="/presidential" element={<PresidentialDiscovery />} />
        <Route path="/presidential/:year" element={<PresidentialPage />} />
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
