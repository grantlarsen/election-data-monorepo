import { SiteHeader } from './SiteHeader';
import { navigation } from './navigation';
import { PlannedPage } from './PlannedPage';
import { PresidentialHistory } from './PresidentialHistory';
import { ElectionMapPage } from './map/ElectionMapPage';
import { CandidatePage } from './CandidatePage';
import { ResultsPage } from './ResultsPage';
import { PresidentialPage, PresidentialDiscovery } from './PresidentialPage';
import { Route, Routes, useLocation, useSearchParams } from 'react-router';
import type { Contest } from './api';
import { apiQuery, humanize, validateSearch } from './filters';
import { DataState, FilterLink, Notice, Pagination, Provenance, RouteFocus, Title, usePage } from './components';

function ContestPage() {
  const [params] = useSearchParams();
  const error = validateSearch(params);
  const data = usePage<Contest>('contests', apiQuery(params, 'contests'), !error);
  return <><Title title="Contests">Discover election contests. Publication labels describe the source coverage behind each record.</Title>
    {error ? <Notice title="Review your filters" error><p>{error}</p></Notice> : <DataState {...data} empty="No modeled contests match this selection.">{page => <>
      <p className="result-count">{page.total.toLocaleString('en-US')} matching contests</p>
      <div className="record-list">{page.items.map(contest => <article className="record" key={contest.id}>
        <div className="record-heading"><div><p className="eyebrow">{contest.election_date} Â· {humanize(contest.stage)}</p><h2><FilterLink to={`/contests/${contest.id}`}>{contest.office_name}</FilterLink></h2><p>{contest.jurisdiction.name} Â· {humanize(contest.jurisdiction.level)}</p></div><span className="record-type">Contest</span></div>
        <Provenance publications={contest.publications} />
      </article>)}</div><Pagination page={page} />
    </>}</DataState>}
  </>;
}

function NotFound() {
  return <><Title title="Page not found">This address does not match a research page.</Title><FilterLink to="/map">Return to the explorer</FilterLink></>;
}

export function App() {
  const location = useLocation();
  return <>
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <SiteHeader />
    <div className="workspace">
      <main id="main-content" className={location.pathname === '/map' ? 'map-page' : location.pathname.startsWith('/candidates/') ? 'candidate-page' : undefined} tabIndex={-1}><RouteFocus />
      <Routes>
        <Route path="/" element={<PlannedPage title="Welcome to Electoral Atlas" />} />
        <Route path="/presidential/history" element={<PresidentialHistory />} />
        {navigation.flatMap(group => group.items.filter(item=>item.planned).map(item=><Route key={item.to} path={item.to} element={<PlannedPage title={item.label} section={group.label} />} />))}
        <Route path="/presidential" element={<PresidentialDiscovery />} />
        <Route path="/presidential/:year" element={<PresidentialPage />} />
        <Route path="/map" element={<ElectionMapPage />} />
        <Route path="/contests" element={<ContestPage />} />
        <Route path="/contests/:contestId" element={<ResultsPage />} />
        <Route path="/candidates" element={<ResultsPage />} />
        <Route path="/candidates/:candidacyId" element={<CandidatePage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>

    </main></div>
    <footer className="site-footer">Election research with historical geography and source context. Missing records never imply zero votes.</footer>
  </>;
}
