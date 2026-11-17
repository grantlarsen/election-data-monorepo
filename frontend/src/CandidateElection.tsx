import { lazy, Suspense, useEffect, useState } from 'react';
import { Link } from 'react-router';
import type { CandidateProfile } from './api';
import { fetchCandidate } from './api';
import { Notice, Pagination } from './components';
import { ElectionSourceDetails } from './ElectionSourceDetails';
import { CandidateLink } from './CandidateLink';
import { humanize } from './filters';
import { useElectionMap } from './map/useElectionMap';
import type { MapUnit } from './map/types';
import { candidateDisplayName } from './candidatePresentation';
import { mapCandidateColor } from './map/electionColors';
import { SenateRaceCard } from './SenatePage';
import { HouseRaceCard } from './HousePage';

const GeographyMap = lazy(() => import('./map/GeographyMap').then(module => ({ default: module.GeographyMap })));

export function CandidateElection({ profile, onResultsPageChange }: { profile: CandidateProfile; onResultsPageChange?: (offset: number) => void }) {
  if (profile.provisional_house_election) {
    const election = profile.provisional_house_election;
    return <section id="election-results" className="profile-card profile-election" aria-labelledby="returns-heading">
      <h2 id="returns-heading">Most recent election</h2><p>2026-11-03 · General election · U.S. House · Provisional counts</p>
      <p className="profile-section-note">Source-scoped candidacy. Person and campaign finance identities remain subject to review.</p>
      {election.stale && <Notice title="Daily update delayed"><p>The last valid cached counts are shown.</p></Notice>}
      <HouseRaceCard race={election.race} complete highlightedCandidacyId={profile.id} />
    </section>;
  }
  if (profile.provisional_election) {
    const election = profile.provisional_election;
    return <section id="election-results" className="profile-card profile-election" aria-labelledby="returns-heading">
      <div className="profile-card-heading"><div><h2 id="returns-heading">Most recent election</h2>
        <p>2026-11-03 · {election.race.special ? 'Special' : 'General'} election · U.S. Senate · Provisional counts</p></div></div>
      <p className="profile-section-note">Current source-scoped returns. Person identity and campaign finance links have not been inferred from names.</p>
      {election.stale && <Notice title="Daily update delayed"><p>The last valid cached counts are shown.</p></Notice>}
      <SenateRaceCard race={election.race} highlightedCandidacyId={profile.id} />
      <p className="profile-section-note">Cache checked: {election.checked_at}. Source CSV SHA-256: {election.sha256}</p>
    </section>;
  }
  return <PublishedCandidateElection profile={profile} onResultsPageChange={onResultsPageChange} />;
}

function PublishedCandidateElection({ profile, onResultsPageChange }: { profile: CandidateProfile; onResultsPageChange?: (offset: number) => void }) {
  const election = profile.latest_election === undefined ? { ...profile.contest, candidacy_id: profile.id } : profile.latest_election;
  const query = new URLSearchParams();
  if (election) {
    query.set('year', election.election_date.slice(0, 4));
    query.set('office', election.office_name);
    query.set('stage', election.stage);
    if (election.jurisdiction.state_code) query.set('state_code', election.jurisdiction.state_code);
  }
  const { data, error, retry } = useElectionMap(query.toString(), !!election);
  const [latestProfile, setLatestProfile] = useState<{ id: string; profile?: CandidateProfile; error?: boolean }>();
  const latestId = election?.candidacy_id;
  useEffect(() => {
    if (!latestId || latestId === profile.id) return;
    const controller = new AbortController();
    fetchCandidate(latestId, '', controller.signal).then(value => {
      if (!controller.signal.aborted) setLatestProfile({ id: latestId, profile: value });
    }).catch(() => {
      if (!controller.signal.aborted) setLatestProfile({ id: latestId, error: true });
    });
    return () => controller.abort();
  }, [latestId, profile.id]);
  const [selection, setSelection] = useState<{ contest: string; unit: string }>();
  const units = data?.units.filter(unit => unit.contest_id === election?.id) || [];
  const selected = units.find(unit => selection?.contest === election?.id && unit.id === selection?.unit) || units[0];
  const matchingIds = new Set(units.map(unit => unit.id));
  const fallback = latestId === profile.id ? profile.results : latestProfile?.id === latestId ? latestProfile?.profile?.results : undefined;
  const results = selected?.summary.candidates || [];
  const publications = data?.publications.filter(publication => units.some(unit => unit.publication_batch_id === publication.batch_id)) || [];
  const resultPublications = results.length ? publications : [...new Map((fallback?.items || []).map(row => [row.publication.batch_id, row.publication])).values()];
  const choose = (unit: MapUnit) => setSelection({ contest: election!.id, unit: unit.id });
  return <section id="election-results" className="profile-card profile-election" aria-labelledby="returns-heading">
    <div className="profile-card-heading"><div><h2 id="returns-heading">Most recent election</h2>
      {election && <p>{election.election_date} · {humanize(election.stage)} · {election.office_name} · {election.jurisdiction.name}</p>}</div></div>
    {!election ? <p>No completed election is available for this candidate.</p> : <>
      {error ? <Notice title="Election map could not be loaded" error><p>{error}</p><button onClick={retry}>Try map again</button></Notice>
        : !data ? <p role="status">Loading election map and race results…</p>
        : !data.features.features.some(feature => matchingIds.has(String(feature.id))) ? <p className="profile-section-note">A compatible map is not available for this election.</p>
        : <><Suspense fallback={<p role="status">Loading election map…</p>}><GeographyMap data={data} selectedId={selected?.id} highlightedIds={matchingIds} focusSelection={false} onSelect={unit => { if (matchingIds.has(unit.id)) choose(unit); }} /></Suspense>
          <p className="profile-map-context"><span><i className="profile-map-highlight" aria-hidden="true" />Candidate’s election area highlighted</span><span><i className="profile-map-surroundings" aria-hidden="true" />Surrounding areas · {data.state_code || 'United States'}</span></p></>}
      {units.length > 1 && <label>Reporting unit<select value={selected?.id} onChange={event => { const unit = units.find(item => item.id === event.target.value); if (unit) choose(unit); }}>{units.map(unit => <option key={unit.id} value={unit.id}>{unit.name}</option>)}</select></label>}
      {results.length > 0 ? <>
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Most recent election results"><table>
          <caption className="profile-visually-hidden">Candidate votes and share of reported votes</caption><thead><tr><th scope="col">Candidate / source bucket</th><th scope="col" className="number">Votes</th><th scope="col" className="number">Share</th></tr></thead>
          <tbody>{results.map((candidate, index) => <tr className={candidate.candidacy_id === election.candidacy_id ? 'profile-current-candidate' : undefined} key={`${candidate.label}:${index}`}>
            <th scope="row"><span className="profile-result-dot" style={{ background: mapCandidateColor(candidate) }} aria-hidden="true" /><CandidateLink candidacyId={candidate.candidacy_id}>{candidateDisplayName(candidate.label)}</CandidateLink>{candidate.candidacy_id === election.candidacy_id && <span className="cell-note">This candidate</span>}</th>
            <td className="number">{candidate.votes.toLocaleString('en-US')}</td><td className="number">{candidate.share === null ? 'Unavailable' : `${candidate.share.toFixed(2)}%`}</td></tr>)}</tbody>
        </table></div>
      </> : fallback?.items.length ? <>
        <div className="table-scroll"><table><caption className="profile-visually-hidden">Source-backed votes by reporting unit</caption><thead><tr><th scope="col">Reporting unit</th><th scope="col" className="number">Votes</th></tr></thead><tbody>{fallback.items.map((row, index) => <tr key={index}><th scope="row">{row.jurisdiction.name}</th><td className="number">{row.votes.toLocaleString('en-US')}</td></tr>)}</tbody></table></div>
        {latestId === profile.id && <Pagination page={fallback} onPageChange={onResultsPageChange} />}
      </> : <p>{latestProfile?.id === latestId && latestProfile?.error ? 'Candidate returns could not be loaded.' : 'No published results are available for this election.'}</p>}
      <ElectionSourceDetails publications={resultPublications} />
      <Link className="profile-contest-link" to={`/contests/${election.id}?${query}&reporting_level=${data?.reporting_level === 'congressional_district' || election.office_name.toLowerCase() === 'u.s. house' || election.jurisdiction.level === 'congressional_district' ? 'congressional_district' : 'county'}`}>View this contest’s published returns</Link>
    </>}
  </section>;
}
