import { Link, useInRouterContext } from 'react-router';
import { ElectionTooltip } from './map/ElectionTooltip';
import type { TooltipCandidate } from './map/ElectionTooltip';
import type { MapCandidate, MapUnit } from './map/types';
import { houseCandidateKind, houseParties, houseRaceHref, houseRaceTitle, houseStatuses } from './house';
import type { HouseRace } from './house';

/** Source adapter over the same candidate cards used by Senate and President. */
export function HousePopover({ race, name, dc }: { race?: HouseRace; name: string; dc: boolean }) {
  const inRouter = useInRouterContext();
  const title = race ? houseRaceTitle(race) : dc ? 'District of Columbia' : name;
  const href = race ? houseRaceHref(race.id) : undefined;
  const raceLink = (label: string) => href
    ? inRouter ? <Link to={href}>{label}</Link> : <a href={href}>{label}</a>
    : label;
  const candidates: TooltipCandidate[] = race?.candidates.map(candidate => ({
    label: candidate.name, kind: houseCandidateKind(candidate), votes: candidate.votes,
    share: candidate.share_pct, party_labels: candidate.party ? [(houseParties[candidate.party] || candidate.party).toUpperCase()] : [],
    candidacy_id: houseCandidateKind(candidate) === 'candidate' ? candidate.candidacy_id || null : null,
    portrait: houseCandidateKind(candidate) === 'candidate' ? candidate.portrait : undefined,
    incumbent: houseCandidateKind(candidate) === 'candidate' ? candidate.incumbent : undefined,
    geographic_reference_id: null, observation_ids: [], correction_ids: [],
    result_badge: candidate.outcome === 'won' ? race.status === 'final' ? 'Winner' : race.status === 'called' ? 'Projected winner' : undefined : undefined,
  })) || [];
  const counted = candidates.filter((candidate): candidate is MapCandidate => candidate.votes !== null);
  const unit: Pick<MapUnit, 'summary' | 'publication_batch_id' | 'name' | 'state_code' | 'contest_id'> | undefined = race ? {
    name: title, state_code: race.state_code, contest_id: race.contest_id || null, publication_batch_id: null,
    summary: { status: race.total_votes === null ? 'no_results' : race.total_votes ? 'indeterminate' : 'zero_total',
      total_votes: race.total_votes, leader: null, margin_votes: null, margin_pp: null, candidates: counted },
  } : undefined;
  const unavailable = dc ? 'Outside voting-seat scope' : 'Returns unavailable';
  return <ElectionTooltip data={{ year: 2026, office: 'U.S. House', stage: 'general',
    reporting_level: 'congressional_district', publications: [] }} unit={unit} name={title} heading={raceLink(title)}
    showLeader={false}
    candidateRows={candidates.some(candidate => candidate.votes === null) ? candidates : undefined}
    contextLabel={race ? houseStatuses[race.status] : unavailable}
    sourceLabel={race ? `${race.source} via Call the Map` : unavailable}
    footerNote={race ? <>Counts can change during canvassing. {raceLink('View all district results')}</> :
      dc ? 'DC elects a nonvoting delegate, outside this 435 voting-seat feed.' : 'Missing district returns do not mean zero votes.'} />;
}
