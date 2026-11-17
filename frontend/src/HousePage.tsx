import { lazy, Suspense, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { sourceUrl } from './api';
import { Notice } from './components';
import { fetchHouseResults, houseCandidateKind, houseDisplayCandidates, houseRaceHref, houseRaceTitle, houseParties, houseStatuses } from './house';
import { CandidateLink } from './CandidateLink';
import type { HouseRace, HouseResults } from './house';
import { HouseDistrictTile } from './HouseDistrictTile';
import { CandidateAvatar } from './CandidateAvatar';
import { cachedPortrait } from './candidateMedia';
import './senate.css';
import './house.css';

const format = (value: number | null) => value === null ? 'Unavailable' : value.toLocaleString('en-US');
const timestamp = (value: string) => new Date(value).toLocaleString('en-US', {
  timeZone: 'America/New_York', dateStyle: 'medium', timeStyle: 'short',
}) + ' ET';
const statuses = houseStatuses;
const parties = houseParties;
const HouseMap = lazy(() => import('./HouseMap'));

function EvidenceLink({ url, children }: { url: string; children: React.ReactNode }) {
  const safe = sourceUrl(url);
  return safe ? <a href={safe} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
}

function useHouseResults() {
  const [data, setData] = useState<HouseResults>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    fetchHouseResults(controller.signal).then(result => {
      if (current) { setData(result); setError(undefined); }
    }).catch(() => {
      if (current && !controller.signal.aborted) setError('House results could not be refreshed. Please try again.');
    });
    const timer = window.setTimeout(() => setAttempt(value => value + 1), 5 * 60 * 1000);
    return () => { current = false; controller.abort(); window.clearTimeout(timer); };
  }, [attempt]);
  return { data, error, retry: () => setAttempt(value => value + 1) };
}

function HouseControl({ data }: { data: HouseResults }) {
  const c = data.control;
  const segments = [{ seats: c.called.D, name: 'Democratic seats', style: 'control-democratic' },
    { seats: c.unresolved, name: 'Uncalled seats', style: 'control-uncalled' },
    { seats: c.called.other, name: 'Other seats', style: 'control-other' },
    { seats: c.called.R, name: 'Republican seats', style: 'control-republican' }];
  return <section className="senate-control" aria-label="Projected House control">
    <div className="control-totals"><div className="control-democratic-total"><strong>{c.called.D}</strong>
      {c.control === 'D' && <span className="control-check" aria-label="Projected Democratic majority">✓</span>}
      <span className="control-party">Democratic seats</span></div>
      <div className="control-republican-total"><strong>{c.called.R}</strong>
        {c.control === 'R' && <span className="control-check" aria-label="Projected Republican majority">✓</span>}
        <span className="control-party">Republican seats</span></div></div>
    <div className="control-bar-wrap"><div className="control-half">218 to a majority<span>▼</span></div>
      <div className="control-bar" role="img" aria-label={`${c.called.D} Democratic seats, ${c.called.R} Republican seats, ${c.called.other} other seats, ${c.unresolved} uncalled. 218 seats needed for a majority.`}>
        {segments.filter(s => s.seats > 0).map(s => <span key={s.name} className={s.style} style={{ width: `${s.seats / 435 * 100}%` }} title={`${s.seats} ${s.name}`} />)}
      </div></div>
    <p className="control-context">Projected control · {c.unresolved} uncalled · {c.called.other} independent/other seats. Only explicit source winners in called or certified races earn seats; leads do not. All 435 voting seats are included.</p>
  </section>;
}

export function HouseRaceCard({ race, complete = false, highlightedCandidacyId }: { race: HouseRace; complete?: boolean; highlightedCandidacyId?: string }) {
  const candidates = complete ? race.candidates : houseDisplayCandidates(race);
  return <article className="senate-race" id={race.id} aria-labelledby={`title-${race.id}`}>
    <div className="senate-race-heading"><h2 id={`title-${race.id}`}><Link to={houseRaceHref(race.id)}>{houseRaceTitle(race)}</Link></h2>
      <span className={`badge ${race.status === 'final' ? '' : 'badge-partial'}`}>{statuses[race.status]}</span>
      <p className="senate-total">{race.total_votes === null ? 'Vote counts unavailable' : `${format(race.total_votes)} votes counted`}</p></div>
    <div className="table-scroll"><table className="senate-candidates" aria-label={`${houseRaceTitle(race)} candidate results`}>
      <thead><tr><th scope="col">Candidate / category</th><th scope="col">Source party</th><th scope="col">Votes</th><th scope="col">Share</th></tr></thead>
      <tbody>{candidates.map((candidate, index) => <tr key={index} className={highlightedCandidacyId && candidate.candidacy_id === highlightedCandidacyId ? 'profile-current-candidate' : undefined}><th scope="row">
        {houseCandidateKind(candidate) === 'candidate' && cachedPortrait(candidate.portrait) && <CandidateAvatar
          portrait={cachedPortrait(candidate.portrait)} name={candidate.name} className="senate-candidate-avatar" decorative
          fallback={<span aria-hidden="true">{candidate.name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('')}</span>} />}
        <CandidateLink candidacyId={houseCandidateKind(candidate) === 'candidate' ? candidate.candidacy_id : undefined}>{candidate.name}</CandidateLink>
        {candidate.incumbent && houseCandidateKind(candidate) === 'candidate' && <span className="incumbent-marker" title={`Incumbent U.S. representative as of ${candidate.incumbent_evidence?.as_of || 'this election'}`}>Incumbent</span>}
        <small className="senate-mobile-party">{parties[candidate.party] || candidate.party || 'Unavailable'}</small>
        {candidate.outcome === 'won' && <small className="senate-outcome">{race.status === 'final' ? 'Winner' : 'Projected winner'}</small>}</th>
        <td>{parties[candidate.party] || candidate.party || 'Unavailable'}</td><td>{format(candidate.votes)}</td>
        <td>{candidate.share_pct === null ? '—' : `${candidate.share_pct.toFixed(2)}%`}</td></tr>)}</tbody>
    </table></div>
    {!complete && candidates.length !== race.candidates.length && <p className="house-all-rows"><Link to={houseRaceHref(race.id)}>View all {race.candidates.length} source candidates and categories</Link></p>}
    <footer className="senate-race-footer"><div className="senate-race-source"><p><EvidenceLink url={race.source_url}>{race.source}</EvidenceLink> via <EvidenceLink url={race.page_url}>Call the Map</EvidenceLink></p></div>
      <div className="senate-update-details"><p>Count updated: {race.count_updated_at ? timestamp(race.count_updated_at) : 'Not supplied'}</p><p>Source read: {timestamp(race.source_read_at)}</p></div>
      {race.called_at && <p className="senate-call-details">Call / certification reported: {timestamp(race.called_at)}</p>}</footer>
  </article>;
}

function HouseSources({ data }: { data: HouseResults }) {
  return <section className="source-panel"><h2>Sources and daily updates</h2>
    <p>November 3, 2026 · 435 voting House districts. Counts can change during canvassing and recounts. Media calls are not certification; certified status is reported by the feed.</p>
    <p><a href="https://www.callthemap.com/results/data">Call the Map</a> compiles state and county election office counts, partly through <a href="https://civicapi.org">civicAPI</a>. Credit: Call the Map; civicAPI, compiled from state and county election offices. Licensed under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.</p>
    <p>Cache checked: {timestamp(data.checked_at)} · Source published: {timestamp(data.published_at)}<br />Daily refresh due: {timestamp(data.next_refresh_at)}. The page checks the local snapshot every five minutes.</p>
    <p>Shares include every reported candidate and write-in category. Missing counts stay unavailable, including unopposed races; they never become zero. Ranked-choice rounds are not identified by the source. Counts follow its currently published round.</p>
    <p>District numbers refer to the 2026 election. Map outlines use Census 2026 TIGER/Line 120th Congress districts, including the corrected Missouri release. Delegates, resident commissioners and separate special elections are outside this feed’s 435-seat scope. Candidate labels preserve the source; canonical identity matching remains subject to review.</p>
    <details><summary>Snapshot provenance</summary><dl><dt>Source download</dt><dd><EvidenceLink url={data.source_url}>Candidate returns CSV</EvidenceLink> · <EvidenceLink url={data.manifest_url}>Checksum manifest</EvidenceLink></dd>
      <dt>Retrieved</dt><dd>{timestamp(data.retrieved_at)}</dd><dt>CSV SHA-256</dt><dd>{data.sha256}</dd></dl>
      <p>Compact tables group small other-party candidates for display. Each district page preserves every source row.</p></details>
  </section>;
}

function HouseLegend() {
  return <ul className="senate-map-legend" aria-label="House result colors"><li><span className="control-democratic" />Democratic winner</li><li><span className="control-republican" />Republican winner</li><li><span className="control-other" />Other winner</li><li><span className="control-uncalled" />Uncalled</li><li><span className="house-seat-missing" />Unavailable</li></ul>;
}

export function HousePage() {
  const [params, setParams] = useSearchParams();
  const { data, error, retry } = useHouseResults();
  const state = params.get('state_code') || '';
  const status = params.get('status') || '';
  const district = params.get('district') || '';
  const view = params.get('view') === 'grid' ? 'grid' : 'map';
  const invalid = data && ((state && !data.races.some(r => r.state_code === state) && !data.missing_districts.some(id => id.startsWith(`${state}-`))) ||
    (status && !Object.hasOwn(statuses, status)) || (district && !data.races.some(r => r.id === district) && !data.missing_districts.includes(district)));
  const races = data?.races.filter(r => (!state || r.state_code === state) && (!status || r.status === status) && (!district || r.id === district)) || [];
  const stateName = (code: string) => data?.races.find(r => r.state_code === code)?.state_name || code;
  const states = data ? [...new Set([...data.races.map(r => r.state_code), ...data.missing_districts.map(id => id.slice(0, 2))])]
    .sort((a, b) => stateName(a).localeCompare(stateName(b))) : [];
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key === 'state_code') next.delete('district');
    setParams(next);
  }
  function clearFilters() {
    const next = new URLSearchParams(params);
    for (const key of ['state_code', 'status', 'district']) next.delete(key);
    setParams(next);
  }
  function selectDistrict(race: HouseRace) {
    const next = new URLSearchParams(params);
    next.set('state_code', race.state_code);
    next.set('district', race.id);
    next.delete('status');
    setParams(next);
    requestAnimationFrame(() => document.getElementById('house-results')?.scrollIntoView?.({ block: 'start' }));
  }
  return <div className="senate-page house-page"><header className="page-heading"><h1 id="page-title" tabIndex={-1}>2026 House of Representatives Election Results</h1></header>
    {error && <Notice title={data ? 'Showing the last loaded results' : 'Results unavailable'} error><p>{error}</p><button onClick={retry}>Try again</button></Notice>}
    {!data && !error && <Notice title="Loading House results"><p>Retrieving the latest daily snapshot.</p></Notice>}
    {data && <>
      {(data.stale || data.refresh_failed) && <Notice title="Daily update delayed"><p>The last valid snapshot is shown. Counts may be out of date because the daily refresh is overdue or failed.</p></Notice>}
      <HouseControl data={data} />
      {!!data.missing_districts.length && <Notice title="Partial source coverage"><p>No cached returns for: {data.missing_districts.join(', ')}. Missing results do not mean zero votes.</p></Notice>}
      <div className="house-view-toggle" role="group" aria-label="Results view">
        <button aria-pressed={view === 'map'} onClick={() => filter('view', '')}>Map</button>
        <button aria-pressed={view === 'grid'} onClick={() => filter('view', 'grid')}>Tile grid</button>
      </div>
      {view === 'map' ? <section className="house-map-panel" aria-label="House geographic results">
        <Suspense fallback={<p role="status">Loading House map…</p>}><HouseMap data={data} selectedState={state} selectedDistrict={district} onSelect={selectDistrict} /></Suspense>
        <HouseLegend />
      </section> :
      <section className="house-seats" aria-label="2026 House district selector"><h2>Explore the districts</h2>
        <p>Each tile is one voting seat. Colors show called winners; striped tiles remain uncalled. Select a district to see its counts.</p>
        <div className="house-seat-states">{states.filter(code => !state || code === state).map(code => <div key={code} className="house-seat-state"><h3>{stateName(code)}</h3>
          <div className="house-seat-tiles">{data.races.filter(r => r.state_code === code).map(race =>
            <HouseDistrictTile key={race.id} race={race} id={race.id} selected={district === race.id} onSelect={selectDistrict} />
          )}{data.missing_districts.filter(id => id.startsWith(`${code}-`)).map(id => <HouseDistrictTile id={id} key={id} selected={false} onSelect={selectDistrict} />)}</div></div>)}</div>
        <HouseLegend />
      </section>}
      <div className="senate-filters"><label>State<select value={state} onChange={e => filter('state_code', e.target.value)}><option value="">All states</option>{states.map(code => <option key={code} value={code}>{stateName(code)}</option>)}</select></label>
        <label>Result status<select value={status} onChange={e => filter('status', e.target.value)}><option value="">All statuses</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {(state || status || district) && <button onClick={clearFilters}>Show all districts</button>}</div>
      <div id="house-results">{invalid ? <Notice title="Review your filters"><p>Choose a listed state, district and result status.</p><button onClick={clearFilters}>Clear filters</button></Notice> :
        races.length ? <div className="senate-grid">{races.map(race => <HouseRaceCard key={race.id} race={race} />)}</div> : <Notice title="No matching results"><p>Missing returns do not mean zero votes.</p></Notice>}</div>
      <HouseSources data={data} />
    </>}
  </div>;
}

export function HouseRacePage() {
  const { raceId } = useParams();
  const { data, error, retry } = useHouseResults();
  const race = data?.races.find(r => r.id === raceId);
  return <div className="house-page"><header className="page-heading"><h1 id="page-title" tabIndex={-1}>2026 House district results</h1></header>
    <p><Link to="/house/2026/results">All House results</Link></p>
    {error && <Notice title="Results unavailable" error><p>{error}</p><button onClick={retry}>Try again</button></Notice>}
    {!data && !error && <p role="status">Loading district results…</p>}
    {data && <>{(data.stale || data.refresh_failed) && <Notice title="Daily update delayed"><p>The last valid snapshot is shown; counts may be out of date.</p></Notice>}
      {race ? <HouseRaceCard race={race} complete /> : <Notice title="District results unavailable"><p>No cached returns match this district. Missing results do not mean zero votes.</p></Notice>}
      <HouseSources data={data} /></>}
  </div>;
}
