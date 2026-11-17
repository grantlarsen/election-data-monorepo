import { lazy, Suspense, useEffect } from 'react';
import { Link, useParams } from 'react-router';
import { Notice } from './components';
import { SenateRaceCard, useSenateResults } from './SenatePage';

const SenateMap = lazy(() => import('./SenateMap'));

export function SenateRacePage() {
  const { stateCode = '' } = useParams();
  const { data, error, retry } = useSenateResults();
  const race = data?.races.find(item => item.state_code === stateCode.toUpperCase());
  const title = race ? `${race.state_name} — 2026 Senate Election` : '2026 Senate Race';
  useEffect(() => { document.title = `${title} | Electoral Atlas`; }, [title]);
  return <div className="senate-page senate-race-page"><header className="page-heading"><h1 id="page-title" tabIndex={-1}>{title}</h1></header>
    <p><Link to={`/senate/2026/results${race ? `?state_code=${race.state_code}` : ''}`}>← Senate election map and all states</Link></p>
    {error && <Notice title="Race results unavailable" error><p>{error}</p><button onClick={retry}>Try again</button></Notice>}
    {!data && !error && <p role="status">Loading Senate race…</p>}
    {data && !race && <Notice title="Senate race not available"><p>No cached race exists for this state. Missing results do not mean zero votes.</p></Notice>}
    {race && <>
      {data!.stale && <Notice title="Daily update delayed"><p>The last valid cached results are shown.</p></Notice>}
      <Suspense fallback={<p role="status">Loading state map…</p>}><SenateMap data={data!} selectedState={race.state_code} raceState={race.state_code}
        onSelect={() => document.getElementById(race.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })} /></Suspense>
      <SenateRaceCard race={race} />
      <p className="data-note">Provisional counts can change. Media calls and certification are labeled separately. Incumbent marks refer to senators entering this election.</p></>}
  </div>;
}
