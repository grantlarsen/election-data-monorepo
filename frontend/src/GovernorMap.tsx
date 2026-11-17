import { Link } from 'react-router';
import StateResultsMap from './StateResultsMap';
import { ElectionTooltip } from './map/ElectionTooltip';
import type { TooltipCandidate } from './map/ElectionTooltip';
import type { MapCandidate, MapUnit } from './map/types';
import type { GovernorRace, GovernorResults } from './governor';
import { governorCandidateKind, governorParties, governorRaceHref, governorStatuses } from './governor';

function GovernorPopover({ race, name, missing }: { race?: GovernorRace; name: string; missing: boolean }) {
  const candidates: TooltipCandidate[] = race?.candidates.map(c => ({ label: c.name,
    kind: governorCandidateKind(c), votes: c.votes,
    share: c.share_pct, party_labels: c.party ? [(governorParties[c.party] || c.party).toUpperCase()] : [],
    candidacy_id: governorCandidateKind(c) === 'candidate' ? c.candidacy_id || null : null,
    incumbent: governorCandidateKind(c) === 'candidate' ? c.incumbent : undefined,
    portrait: governorCandidateKind(c) === 'candidate' ? c.portrait : undefined,
    geographic_reference_id: null, observation_ids: [], correction_ids: [],
    result_badge: c.outcome === 'won' ? race.status === 'final' ? 'Winner' : 'Projected winner' : undefined,
  })) || [];
  const unit: MapUnit | undefined = race ? {
    id: race.id, geoid: null, name, state_code: race.state_code, jurisdiction_id: null,
    contest_id: race.contest_id || null, publication_batch_id: null, has_geometry: true,
    summary: { status: race.total_votes === null ? 'no_results' : race.total_votes ? 'available' : 'zero_total',
      total_votes: race.total_votes, leader: null, margin_votes: null, margin_pp: null,
      candidates: candidates.filter((c): c is MapCandidate => c.votes !== null) },
  } : undefined;
  const context = race ? governorStatuses[race.status] : missing ? 'Returns unavailable' : 'No Governor election in 2026';
  return <ElectionTooltip data={{ year: 2026, office: 'Governor', stage: 'general', reporting_level: 'state', publications: [] }}
    unit={unit} name={name} heading={race ? <Link to={governorRaceHref(race.state_code)}>{name}</Link> : name}
    headerLayout="split" showLeader={false} contextLabel={context}
    candidateRows={candidates.some(c => c.votes === null) ? candidates : undefined}
    sourceLabel={race ? `${race.source} via Call the Map` : context}
    footerNote={race && <>{race.flipped && race.previous_election && <>Party flipped from {governorParties[race.previous_election.party] || race.previous_election.party} ({race.previous_election.year}); {race.status === 'final' ? 'certified per source' : 'media call, uncertified'}. </>}Counts can change during canvassing. <Link to={governorRaceHref(race.state_code)}>View this Governor race</Link></>} />;
}

export default function GovernorMap(props: {
  data: GovernorResults; selectedState: string; onSelect: (state: string) => void; raceState?: string;
}) {
  return <StateResultsMap {...props} office="Governor"
    flipped={race => race.flipped === true}
    tooltip={(race, name, missing) => <GovernorPopover race={race} name={name} missing={missing} />} />;
}
