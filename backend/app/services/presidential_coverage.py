"""Seven-year source/publication inventory; state and county scopes stay separate."""
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import DataSource, Jurisdiction
from app.models.election import CanonicalMaterializationIssue, CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn
from app.models.ingestion import ElectionResultObservation, SourceActiveYear, SourceRelease
from app.models.state_results import StateResultPublication
from app.services.canonical_results import state_totals
from ingestion.canonical_medsl import DATES
from ingestion.medsl import STATE_NAMES
from ingestion.presidential_state_returns import scope


def inventory(session: Session) -> dict:
    source = session.scalar(select(DataSource).where(DataSource.name == 'medsl_presidential_county'))
    years = []
    for year in sorted(DATES):
        active = session.get(SourceActiveYear, (source.id, year)) if source else None
        release = session.get(SourceRelease, active.release_id) if active else None
        modes = []
        if release:
            modes = [dict(mode=mode, rows=count) for mode, count in session.execute(
                select(ElectionResultObservation.mode_normalized, func.count())
                .where(ElectionResultObservation.release_id == release.id, ElectionResultObservation.year == year)
                .group_by(ElectionResultObservation.mode_normalized).order_by(ElectionResultObservation.mode_normalized))]
        pointer = session.get(CanonicalPublication, f'medsl_presidential_county:{year}:county_total')
        batch = session.get(CanonicalResultBatch, pointer.batch_id) if pointer else None
        counties = {}
        exclusions = []
        if batch:
            counties = {st: dict(rows=count, votes=votes, reporting_units=units) for st, count, votes, units in session.execute(
                select(Jurisdiction.state_code, func.count(), func.sum(CanonicalVoteReturn.votes),
                       func.count(func.distinct(CanonicalVoteReturn.jurisdiction_id)))
                .join(Jurisdiction, Jurisdiction.id == CanonicalVoteReturn.jurisdiction_id)
                .where(CanonicalVoteReturn.batch_id == batch.id).group_by(Jurisdiction.state_code))}
            exclusions = [dict(state_code=st, code=code, rows=count) for st, code, count in session.execute(
                select(ElectionResultObservation.state_code, CanonicalMaterializationIssue.code, func.count())
                .join(ElectionResultObservation, ElectionResultObservation.id == CanonicalMaterializationIssue.observation_id)
                .where(CanonicalMaterializationIssue.batch_id == batch.id)
                .group_by(ElectionResultObservation.state_code, CanonicalMaterializationIssue.code)
                .order_by(ElectionResultObservation.state_code, CanonicalMaterializationIssue.code))]
        state_pointer = session.get(StateResultPublication, scope(year))
        official = state_totals(session, year=year) if state_pointer else None
        official_states = Counter()
        if official:
            for row in official['results']:
                official_states[row['state_code']] += row['votes']
        years.append(dict(year=year, election_date=f'{year}-{DATES[year][0]:02d}-{DATES[year][1]:02d}',
            source_release_id=str(release.id) if release else None, source_sha256=release.sha256 if release else None,
            observed_rows=sum(m['rows'] for m in modes), source_modes=modes,
            county=dict(availability='published' if batch else 'missing_publication',
                batch_id=str(batch.id) if batch else None, status=batch.status if batch else None,
                source_release_id=str(batch.source_release_id) if batch else None,
                matches_active_source=batch.source_release_id == release.id if batch and release else False,
                reference_release_id=str(batch.reference_release_id) if batch else None,
                accepted_rows=batch.accepted_rows if batch else 0, excluded_rows=batch.excluded_rows if batch else None,
                votes=batch.canonical_votes if batch else None, exclusions=exclusions,
                missing_states=sorted(set(STATE_NAMES)-set(counties))),
            state=dict(availability='published' if official else 'missing_publication',
                batch_id=official['batch_id'] if official else None,
                source_release_id=official['source_release_id'] if official else None,
                votes=sum(official_states.values()) if official else None),
            states=[dict(state_code=st, county=counties.get(st), official_votes=official_states.get(st),
                state_minus_published_county_votes=official_states[st]-counties.get(st,{}).get('votes',0)
                    if official and batch else None) for st in sorted(STATE_NAMES)],
            county_coverage_verified=False, additive_across_reporting_levels=False,
            limitations=['County publications are source-backed partial subsets; excluded modes are not allocated.',
                         'State-minus-county differences combine coverage gaps and source disagreements; they are not county estimates.']))
    return dict(elections=years, additive_across_years=False)
