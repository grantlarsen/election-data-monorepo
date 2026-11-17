import { lazy, Suspense, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { sourceUrl } from './api';
import { Notice } from './components';
import { indeterminateColor, partyPalette } from './map/electionColors';
import { fetchSenateResults, senateDisplayCandidates } from './senate';
import type { SenateCandidate, SenateRace, SenateResults } from './senate';
import { senateRaceHref } from './senate';
import { CandidateLink } from './CandidateLink';
import { SenateControl } from './SenateControl';
import { CandidateAvatar } from './CandidateAvatar';
import { cachedPortrait } from './candidateMedia';
import './senate.css';

const SenateMap = lazy(() => import('./SenateMap'));

const format = (value: number) => value.toLocaleString('en-US');
const timestamp = (value: string) => new Date(value).toLocaleString('en-US', {
  timeZone: 'America/New_York', dateStyle: 'medium', timeStyle: 'short',
}) + ' ET';
const statuses = { counting: 'Counting · no call', called: 'Media call · uncertified', final: 'Certified · per source' };
const parties: Record<string, string> = { D: 'Democratic', R: 'Republican', I: 'Independent', L: 'Libertarian', G: 'Green', O: 'Other' };
const color = (party: string) => partyPalette[party === 'D' ? 'Democratic' : party === 'R' ? 'Republican' : party ? 'Other / independent' : 'Party unavailable'];

function EvidenceLink({ url, children }: { url: string; children: React.ReactNode }) {
  const safe = sourceUrl(url);
  return safe ? <a href={safe} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
}

function CandidateRow({ candidate, race, highlighted }: { candidate: SenateCandidate; race: SenateRace; highlighted?: boolean }) {
  const outcome = candidate.outcome === 'won' ? race.status === 'final' ? 'Certified winner per source' : 'Called by Call the Map'
    : candidate.outcome === 'leads' ? 'Leads · no call' : '';
  const portrait = candidate.kind === 'aggregate' ? undefined : cachedPortrait(candidate.portrait);
  return <tr className={highlighted ? 'profile-current-candidate' : undefined}><th scope="row">
    <CandidateAvatar portrait={portrait} name={candidate.name} className={portrait ? 'senate-candidate-avatar' : ''} decorative
      fallback={<span className="senate-party-dot" style={{ background: candidate.kind === 'aggregate' ? indeterminateColor : color(candidate.party) }} />} />
    <CandidateLink candidacyId={candidate.candidacy_id}>{candidate.name}</CandidateLink>
    {candidate.incumbent && <span className="incumbent-marker" title={`Incumbent U.S. senator as of ${candidate.incumbent_evidence?.as_of || 'this election'}`}>Incumbent</span>}
    <small className="senate-mobile-party">{parties[candidate.party] || candidate.party || 'Party unavailable'}</small>
    {outcome && <small className="senate-outcome">{outcome}</small>}</th>
    <td>{parties[candidate.party] || candidate.party || 'Unavailable'}</td><td>{format(candidate.votes)}</td>
    <td>{candidate.share_pct === null ? '—' : `${candidate.share_pct.toFixed(2)}%`}</td></tr>;
}

export function SenateRaceCard({ race, highlightedCandidacyId, groupSmallCandidates = false }: {
  race: SenateRace; highlightedCandidacyId?: string; groupSmallCandidates?: boolean;
}) {
  const candidates = groupSmallCandidates ? senateDisplayCandidates(race) : race.candidates;
  return <article className="senate-race" id={race.id} aria-labelledby={`title-${race.id}`}>
    <div className="senate-race-heading"><h2 id={`title-${race.id}`}><Link to={senateRaceHref(race.state_code)}>{race.state_name}</Link></h2>
      <span className={`badge ${race.status === 'final' ? '' : 'badge-partial'}`}>{statuses[race.status]}</span>
      <p className="senate-total">{format(race.total_votes)} votes counted</p></div>
    <div className="table-scroll"><table className="senate-candidates" aria-label={`${race.state_name} Senate candidate results`}>
      <thead><tr><th scope="col">Candidate</th><th scope="col">Source party</th><th scope="col">Votes</th><th scope="col">Share</th></tr></thead>
      <tbody>{candidates.map((candidate, index) => <CandidateRow key={index} candidate={candidate} race={race} highlighted={!!highlightedCandidacyId && candidate.candidacy_id === highlightedCandidacyId} />)}</tbody>
    </table></div>
    <footer className="senate-race-footer">
      <div className="senate-race-source"><p><EvidenceLink url={race.source_url}>{race.source}</EvidenceLink> via <EvidenceLink url={race.page_url}>Call the Map</EvidenceLink></p></div>
      <div className="senate-update-details"><p>Count updated: {race.count_updated_at ? timestamp(race.count_updated_at) : 'Not supplied'}</p>
        <p>Source read: {timestamp(race.source_read_at)}</p></div>
      {race.called_at && <p className="senate-call-details">Call / certification reported: {timestamp(race.called_at)}</p>}</footer>
  </article>;
}

export function useSenateResults() {
  const [data, setData] = useState<SenateResults>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    fetchSenateResults(controller.signal).then(result => {
      if (current) { setData(result); setError(undefined); }
    }).catch(() => {
      if (current && !controller.signal.aborted) setError('Senate results could not be refreshed. Please try again.');
    });
    // Re-read the local API so an open page picks up the next daily snapshot.
    const timer = window.setTimeout(() => setAttempt(value => value + 1), 5 * 60 * 1000);
    return () => { current = false; controller.abort(); window.clearTimeout(timer); };
  }, [attempt]);
  return { data, error, retry: () => setAttempt(value => value + 1) };
}

export function SenatePage() {
  const [params, setParams] = useSearchParams();
  const { data, error, retry } = useSenateResults();
  const state = params.get('state_code') || '';
  const status = params.get('status') || '';
  const invalid = (state && !data?.races.some(race => race.state_code === state) && !data?.missing_states.includes(state)) ||
    (status && !Object.hasOwn(statuses, status));
  const races = data?.races.filter(race => (!state || race.state_code === state) && (!status || race.status === status)) || [];
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  }
  return <div className="senate-page"><header className="page-heading"><h1 id="page-title" tabIndex={-1}>2026 Senate Election Results</h1>
    </header>
    {error && <Notice title={data ? 'Showing the last loaded results' : 'Results unavailable'} error><p>{error}</p><button onClick={retry}>Try again</button></Notice>}
    {!data && !error && <Notice title="Loading Senate results"><p>Retrieving the latest daily snapshot.</p></Notice>}
    {data && <>
      {(data.stale || data.refresh_failed) && <Notice title="Daily update delayed"><p>The last valid snapshot is shown. {data.refresh_failed ? 'The latest source refresh failed validation or could not be downloaded.' : 'The daily cache is overdue for refresh.'} Counts below may be out of date.</p></Notice>}
      <SenateControl control={data.control} />
      {!!data.missing_states.length && <Notice title="Partial source coverage"><p>No cached returns for: {data.missing_states.join(', ')}. Missing results do not mean zero votes.</p></Notice>}
      <Suspense fallback={<p role="status">Loading state map…</p>}><SenateMap data={data} selectedState={state}
        onSelect={code => { const next = new URLSearchParams(params); next.set('state_code', code); next.delete('status'); setParams(next); }}
        onClear={() => { const next = new URLSearchParams(params); next.delete('state_code'); next.delete('status'); setParams(next); }} /></Suspense>
      <div className="senate-filters"><label>State<select value={state} onChange={event => filter('state_code', event.target.value)}><option value="">All states</option>
        {data.races.map(race => <option key={race.id} value={race.state_code}>{race.state_name}</option>)}
        {data.missing_states.map(code => <option key={code} value={code}>{code} · unavailable</option>)}</select></label>
        <label>Result status<select value={status} onChange={event => filter('status', event.target.value)}><option value="">All statuses</option>
          {Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
      {invalid ? <Notice title="Review your filters"><p>Choose a state on this election’s ballot and a listed result status.</p><button onClick={() => setParams({})}>Clear filters</button></Notice>
        : races.length ? <div className="senate-grid">{races.map(race => <SenateRaceCard key={race.id} race={race} groupSmallCandidates />)}</div>
          : <Notice title="No matching results"><p>No cached contest matches these filters. Missing returns do not mean zero votes.</p></Notice>}
      <section className="source-panel"><h2>Sources and daily updates</h2>
        <p>November 3, 2026 · 33 regular contests and 2 special elections. Statewide counts, cached daily. Counts can change during canvassing and recounts. Media calls are not certification.</p>
        <p>Shares use all reported candidate votes and write-in buckets; they do not measure how much of the expected vote is counted.</p>
        <div className="senate-cache"><p>Cache checked: <time dateTime={data.checked_at}>{timestamp(data.checked_at)}</time> · Source published: {timestamp(data.published_at)}</p>
          <p>Daily refresh due: {timestamp(data.next_refresh_at)}. Media calls by Call the Map; certification status is supplied by the feed.</p></div>
        {data.control && <details><summary>Senate control methodology and sources</summary><p>Retained seats come from the official Senate class rosters, reviewed {data.control.baseline_reviewed_at} for the election on {data.control.baseline_as_of}. The two retained independents caucus with Democrats. Only explicit source winner outcomes in called or certified contests add election seats; leads and missing races remain uncalled. All 100 seats are accounted for. Flips compare called winners with the party holding the same seat entering the election.</p>
          <ul>{data.control.sources.map(url => <li key={url}><EvidenceLink url={url}>{url.includes('dailypress') ? 'Senate Daily Press — party lineup and caucuses' : `Official Senate ${url.includes('Class_III') ? 'Class III' : url.includes('Class_II') ? 'Class II' : 'Class I'} roster`}</EvidenceLink></li>)}</ul></details>}
        <p><a href="https://www.callthemap.com/results">Call the Map</a> compiles state and county election office counts, partly through <a href="https://civicapi.org">civicAPI</a>. Credit: Call the Map; civicAPI, compiled from state and county election offices. Licensed under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.</p>
        <p>State and candidate links open this race and its source-scoped profiles. Person identities and campaign finance links remain subject to review. Anonymous vote buckets have no candidate profile.</p>
        <details><summary>Snapshot provenance</summary><dl>
          <dt>Source download</dt><dd><EvidenceLink url={data.source_url}>Candidate returns CSV</EvidenceLink> · <EvidenceLink url={data.manifest_url}>Checksum manifest</EvidenceLink></dd>
          <dt>Retrieved</dt><dd>{timestamp(data.retrieved_at)}</dd><dt>CSV SHA-256</dt><dd>{data.sha256}</dd>
        </dl><p>Race returns cover this election’s 35 contests; the control bar also includes 65 retained seats. Ranked-choice counts follow the source’s currently published round; no round or winner is inferred.</p></details>
      </section>
    </>}
  </div>;
}
