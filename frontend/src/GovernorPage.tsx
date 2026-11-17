import { lazy, Suspense, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { sourceUrl } from './api';
import { Notice } from './components';
import { CandidateLink } from './CandidateLink';
import { CandidateAvatar } from './CandidateAvatar';
import { cachedPortrait } from './candidateMedia';
import { partyPalette } from './map/electionColors';
import { fetchGovernorResults, governorCandidateKind, governorDisplayCandidates, governorParties, governorRaceHref, governorStatuses, governorWinner } from './governor';
import type { GovernorRace, GovernorResults } from './governor';
import './senate.css';

const GovernorMap = lazy(() => import('./GovernorMap'));
const format = (value: number | null) => value === null ? 'Unavailable' : value.toLocaleString('en-US');
const timestamp = (value: string) => new Date(value).toLocaleString('en-US', {
  timeZone: 'America/New_York', dateStyle: 'medium', timeStyle: 'short',
}) + ' ET';
function EvidenceLink({ url, children }: { url: string; children: React.ReactNode }) {
  const safe = sourceUrl(url);
  return safe ? <a href={safe} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
}

export function GovernorRaceCard({ race, compact = false, highlightedCandidacyId }: { race: GovernorRace; compact?: boolean; highlightedCandidacyId?: string }) {
  const candidates = compact ? governorDisplayCandidates(race) : race.candidates;
  return <article className="senate-race" id={race.id} aria-labelledby={`title-${race.id}`}>
    <div className="senate-race-heading"><h2 id={`title-${race.id}`}><Link to={governorRaceHref(race.state_code)}>{race.state_name}</Link></h2>
      <span className={`badge ${race.status === 'final' ? '' : 'badge-partial'}`}>{governorStatuses[race.status]}</span>
      <p className="senate-total">{race.total_votes === null ? 'Vote counts unavailable' : `${format(race.total_votes)} votes counted`}</p></div>
    <div className="table-scroll"><table className="senate-candidates" aria-label={`${race.state_name} Governor candidate results`}>
      <thead><tr><th scope="col">Candidate</th><th scope="col">Source party</th><th scope="col">Votes</th><th scope="col">Share</th></tr></thead>
      <tbody>{candidates.map((c, index) => {
        const portrait = governorCandidateKind(c) === 'candidate' ? cachedPortrait(c.portrait) : undefined;
        return <tr key={index} className={highlightedCandidacyId && c.candidacy_id === highlightedCandidacyId ? 'profile-current-candidate' : undefined}><th scope="row">
        <CandidateAvatar portrait={portrait} name={c.name} className={portrait ? 'senate-candidate-avatar' : ''} decorative
          fallback={<span className="senate-party-dot" style={{
        background: partyPalette[c.party === 'D' ? 'Democratic' : c.party === 'R' ? 'Republican' : c.party ? 'Other / independent' : 'Party unavailable'],
      }} />} /><CandidateLink candidacyId={governorCandidateKind(c) === 'aggregate' ? null : c.candidacy_id}>{c.name}</CandidateLink>
        {c.incumbent && c.kind !== 'aggregate' && <span className="incumbent-marker" title={`Incumbent Governor as of ${c.incumbent_evidence?.as_of || 'this election'}`}>Incumbent</span>}
        <small className="senate-mobile-party">{governorParties[c.party] || c.party || 'Party unavailable'}</small>
        {c.outcome && <small className="senate-outcome">{c.outcome === 'won' ? race.status === 'final' ? 'Certified winner per source' : 'Called by Call the Map' : 'Leads · no call'}</small>}</th>
        <td>{governorParties[c.party] || c.party || 'Unavailable'}</td><td>{format(c.votes)}</td><td>{c.share_pct === null ? '—' : `${c.share_pct.toFixed(2)}%`}</td></tr>;
      })}</tbody>
    </table></div>
    {race.flipped && race.previous_election && <p className="data-note">Party flip: {governorParties[race.previous_election.party] || race.previous_election.party} → {governorParties[governorWinner(race)?.party || ''] || governorWinner(race)?.party}. Previous election: <EvidenceLink url={race.previous_election.source_url}>{race.previous_election.year}</EvidenceLink>. {race.status === 'final' ? 'Certified per source.' : 'Media call; uncertified.'}</p>}
    {compact && candidates.length < race.candidates.length && <p className="data-note"><Link to={governorRaceHref(race.state_code)}>View all {race.candidates.length} source candidate lines</Link></p>}
    <footer className="senate-race-footer">
      <div className="senate-race-source"><p><EvidenceLink url={race.source_url}>{race.source}</EvidenceLink> via <EvidenceLink url={race.page_url}>Call the Map</EvidenceLink></p></div>
      <div className="senate-update-details"><p>Count updated: {race.count_updated_at ? timestamp(race.count_updated_at) : 'Not supplied'}</p><p>Source read: {timestamp(race.source_read_at)}</p></div>
      {race.called_at && <p className="senate-call-details">Call / certification reported: {timestamp(race.called_at)}</p>}</footer>
  </article>;
}

function useGovernorResults() {
  const [data, setData] = useState<GovernorResults>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    fetchGovernorResults(controller.signal).then(result => {
      if (current) { setData(result); setError(undefined); }
    }).catch(() => {
      if (current && !controller.signal.aborted) setError('Governor results could not be refreshed. Please try again.');
    });
    const timer = window.setTimeout(() => setAttempt(value => value + 1), 5 * 60 * 1000);
    return () => { current = false; controller.abort(); window.clearTimeout(timer); };
  }, [attempt]);
  return { data, error, retry: () => setAttempt(value => value + 1) };
}

function GovernorSummary({ data }: { data: GovernorResults }) {
  const called = { D: 0, R: 0, other: 0 };
  data.races.forEach(race => { const winner = governorWinner(race); if (winner) called[winner.party === 'D' ? 'D' : winner.party === 'R' ? 'R' : 'other']++; });
  const unresolved = data.expected_contests - called.D - called.R - called.other;
  const segments = [
    { count: called.D, name: 'Democratic', css: 'control-democratic' },
    { count: unresolved, name: 'Uncalled', css: 'control-uncalled' },
    { count: called.other, name: 'Other / independent', css: 'control-other' },
    { count: called.R, name: 'Republican', css: 'control-republican' },
  ];
  return <section className="senate-control" aria-label="Governor election outcomes">
    <div className="control-totals"><div className="control-democratic-total"><strong>{called.D}</strong><span className="control-party">Democratic wins</span></div>
      <div className="control-republican-total"><strong>{called.R}</strong><span className="control-party">Republican wins</span></div></div>
    <div className="control-bar" role="img" aria-label={`${called.D} Democratic wins, ${called.R} Republican wins, ${called.other} other wins, ${unresolved} uncalled. 36 state elections.`}>
      {segments.filter(s => s.count > 0).map(s => <span key={s.name} className={s.css} style={{ width: `${100 * s.count / data.expected_contests}%` }} title={`${s.count} ${s.name}`} />)}</div>
  </section>;
}

/** Both routes use the same snapshot; the state route retains every candidate line. */
export function GovernorPage() {
  const { stateCode } = useParams();
  const raceState = stateCode?.toUpperCase();
  const [params, setParams] = useSearchParams();
  const { data, error, retry } = useGovernorResults();
  const state = raceState || params.get('state_code') || '';
  const status = raceState ? '' : params.get('status') || '';
  const selectedRace = data?.races.find(r => r.state_code === raceState);
  const title = raceState ? selectedRace ? `${selectedRace.state_name} — 2026 Governor Election` : '2026 Governor Race' : '2026 Governor Election Results';
  useEffect(() => { document.title = `${title} | Electoral Atlas`; }, [title]);
  const invalid = (state && !data?.races.some(r => r.state_code === state) && !data?.missing_states.includes(state)) ||
    (status && !Object.hasOwn(governorStatuses, status));
  const races = data?.races.filter(r => (!state || r.state_code === state) && (!status || r.status === status)) || [];
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  }
  function clearFilters() {
    const next = new URLSearchParams(params);
    next.delete('state_code');
    next.delete('status');
    setParams(next);
  }
  return <div className={`senate-page${raceState ? ' senate-race-page' : ''}`}><header className="page-heading"><h1 id="page-title" tabIndex={-1}>{title}</h1></header>
    {raceState && <p><Link to="/governor/2026/results">← Governor election map and all states</Link></p>}
    {error && <Notice title={data ? 'Showing the last loaded results' : 'Results unavailable'} error><p>{error}</p><button onClick={retry}>Try again</button></Notice>}
    {!data && !error && <Notice title="Loading Governor results"><p>Retrieving the latest daily snapshot.</p></Notice>}
    {data && <>
      {(data.stale || data.refresh_failed) && <Notice title="Daily update delayed"><p>The last valid snapshot is shown. {data.refresh_failed ? 'The latest source refresh failed validation or could not be downloaded.' : 'The daily cache is overdue for refresh.'} Counts below may be out of date.</p></Notice>}
      {!raceState && <GovernorSummary data={data} />}
      {!!data.missing_states.length && <Notice title="Partial source coverage"><p>No cached returns for: {data.missing_states.join(', ')}. Missing results do not mean zero votes.</p></Notice>}
      {(!raceState || selectedRace) && <Suspense fallback={<p role="status">Loading state map…</p>}><GovernorMap data={data} selectedState={state} raceState={raceState}
        onSelect={code => { if (raceState) return; const next = new URLSearchParams(params); next.set('state_code', code); next.delete('status'); setParams(next); }} /></Suspense>}
      {!raceState && <div className="senate-filters governor-filters"><label>State<select value={state} onChange={e => filter('state_code', e.target.value)}><option value="">All states</option>
        {data.races.map(r => <option key={r.id} value={r.state_code}>{r.state_name}</option>)}{data.missing_states.map(code => <option key={code} value={code}>{code} · unavailable</option>)}</select></label>
        <label>Result status<select value={status} onChange={e => filter('status', e.target.value)}><option value="">All statuses</option>
          {Object.entries(governorStatuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {(state || status) && <button onClick={clearFilters}>Clear filters</button>}</div>}
      {invalid ? <Notice title="Review your filters"><p>Choose a state on this election’s ballot and a listed result status.</p></Notice>
        : races.length ? <div className={raceState ? undefined : 'senate-grid'}>{races.map(r => <GovernorRaceCard key={r.id} race={r} compact={!raceState} />)}</div>
          : <Notice title="No matching results"><p>No cached contest matches this selection. Missing returns do not mean zero votes.</p></Notice>}
      <section className="source-panel"><h2>Sources and daily updates</h2>
        <p>November 3, 2026 · 36 state gubernatorial general elections. Territorial elections are outside this feed’s coverage. <EvidenceLink url="https://www.nga.org/governors/elections/">NGA election calendar</EvidenceLink>.</p>
        <p>Statewide counts are cached daily and can change during canvassing and recounts. Media calls are not certification. Ranked-choice rounds are not identified by this feed; no rounds or winners are reconstructed.</p>
        <p>Shares use all reported candidate votes and write-in buckets; they do not measure how much of the expected vote is counted. Source candidate and party labels are preserved. Full race pages retain every source line.</p>
        <p>Incumbent badges identify Governors holding this office entering the November 3 election, based on the reviewed <EvidenceLink url="https://www.nga.org/governors/elections/">NGA election roster</EvidenceLink>. Candidate links open source-scoped profiles. Anonymous vote categories have no profile.</p>
        <p>Diagonal shading marks a called or certified winner whose party differs from the previous Governor election winner: 2024 in New Hampshire and Vermont, 2022 elsewhere. Leads alone are never marked as flips. Prior winners and parties come from the NGA election archive.</p>
        <div className="senate-cache"><p>Cache checked: <time dateTime={data.checked_at}>{timestamp(data.checked_at)}</time> · Source published: {timestamp(data.published_at)}</p>
          <p>Daily refresh due: {timestamp(data.next_refresh_at)}. Media calls by Call the Map; certification status is supplied by the feed.</p></div>
        <p><a href="https://www.callthemap.com/results">Call the Map</a> compiles state and county election office counts, partly through <a href="https://civicapi.org">civicAPI</a>. Credit: Call the Map; civicAPI, compiled from state and county election offices. Licensed under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.</p>
        <details><summary>Snapshot provenance</summary><dl><dt>Source download</dt><dd><EvidenceLink url={data.source_url}>Candidate returns CSV</EvidenceLink> · <EvidenceLink url={data.manifest_url}>Checksum manifest</EvidenceLink></dd>
          <dt>Retrieved</dt><dd>{timestamp(data.retrieved_at)}</dd><dt>CSV SHA-256</dt><dd>{data.sha256}</dd></dl></details>
      </section></>}
  </div>;
}
