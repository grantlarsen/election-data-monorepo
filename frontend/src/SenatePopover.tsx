import { Link, useInRouterContext } from 'react-router';
import { ElectionTooltip } from './map/ElectionTooltip';
import type { MapUnit } from './map/types';
import type { SenateRace } from './senate';
import { senateCandidateSearch, senateRaceHref } from './senate';

const parties: Record<string, string> = { D: 'DEMOCRATIC', R: 'REPUBLICAN', I: 'INDEPENDENT', L: 'LIBERTARIAN', G: 'GREEN', O: 'OTHER' };
const statuses = { counting: 'Counting · no call', called: 'Media call · uncertified', final: 'Certified · per source' };

/** Source adapter over the same tooltip used by the presidential map. */
export function SenatePopover({ race, name, missing }: { race?: SenateRace; name: string; missing: boolean }) {
  const inRouter = useInRouterContext();
  const href = race ? senateRaceHref(race.state_code) : undefined;
  const heading = href ? inRouter ? <Link to={href}>{name}</Link> : <a href={href}>{name}</a> : name;
  const unit: MapUnit | undefined = race ? {
    id: race.id, geoid: null, name, state_code: race.state_code, jurisdiction_id: null,
    contest_id: race.contest_id || null, publication_batch_id: null, has_geometry: true,
    summary: { status: race.summary_status || (race.total_votes ? 'available' : 'zero_total'),
      total_votes: race.total_votes, leader: race.leader || null, margin_votes: race.margin_votes ?? null,
      margin_pp: race.margin_pct ?? null, candidates: race.candidates.map(candidate => ({
        label: candidate.name, kind: candidate.kind || 'source_candidate', votes: candidate.votes,
        share: candidate.share_pct, party_labels: candidate.party ? [parties[candidate.party] || candidate.party] : [],
        candidacy_id: candidate.candidacy_id || null, incumbent: candidate.incumbent,
        portrait: candidate.portrait,
        result_badge: candidate.outcome === 'won' ? race.status === 'final' ? 'Winner' : race.status === 'called' ? 'Projected winner' : undefined : undefined,
        geographic_reference_id: null, observation_ids: [], correction_ids: [],
      })) },
  } : undefined;
  return <ElectionTooltip data={{ year: 2026, office: 'U.S. Senate', stage: race?.special ? 'special' : 'general',
    reporting_level: 'state', publications: [] }} unit={unit} name={name} heading={heading} headerLayout="split" showLeader={false}
    contextLabel={race ? statuses[race.status] : missing ? 'Returns unavailable' : 'No Senate election in 2026'}
    sourceLabel={race ? `${race.source} via Call the Map` : missing ? 'Returns unavailable' : 'No Senate election in 2026'}
    candidateSearch={race ? senateCandidateSearch(race) : undefined}
    footerNote={race && <>Counts can change during canvassing. <a href={href}>View this Senate race</a></>} />;
}
