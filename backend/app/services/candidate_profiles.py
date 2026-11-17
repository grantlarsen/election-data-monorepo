"""Shareable candidacy profiles with explicit identity and finance availability."""
from uuid import UUID
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.election_schemas import ResultFilters
from app.models.candidate_identity import CandidateFinanceSummary, CandidateIdentityReview, FecCandidateRecord
from app.models.core import Candidacy, Contest, Election, Jurisdiction, Person
from app.models.identity import CommitteeRelationship, ExternalIdentifier, Organization
from app.models.ingestion import SourceRelease
from app.services.election_queries import _geography, _source, list_results


def finance_values(summary: CandidateFinanceSummary) -> dict:
    """FEC's published transfer correction; never treat missing amounts as zero."""
    incoming, outgoing = summary.transfers_from_authorized, summary.transfers_to_authorized
    known = all(value is not None for value in (summary.receipts, summary.disbursements, incoming, outgoing))
    adjust = known and incoming > 0 and outgoing > 0
    raised = summary.receipts - incoming if adjust else summary.receipts if known else None
    spent = summary.disbursements - outgoing if adjust else summary.disbursements if known else None
    return dict(status="available" if known else "partial", currency="USD",
        total_raised=raised, total_spent=spent, reported_receipts=summary.receipts,
        reported_disbursements=summary.disbursements, transfers_from_authorized=incoming,
        transfers_to_authorized=outgoing, cash_on_hand=summary.cash_on_hand, debts=summary.debts,
        coverage_end=summary.coverage_end,
        definition="reported_totals_less_authorized_transfers" if adjust else "reported_totals" if known else "transfer_information_incomplete")


def candidate_profile(session: Session, candidacy_id: UUID, *, reporting_level: str | None = None,
                      limit: int = 50, offset: int = 0) -> dict | None:
    candidate = session.get(Candidacy, candidacy_id)
    if candidate is None:
        return None
    contest = session.get(Contest, candidate.contest_id)
    election = session.get(Election, contest.election_id)
    geography = session.get(Jurisdiction, contest.jurisdiction_id)
    person = session.get(Person, candidate.person_id) if candidate.person_id else None
    latest_query = (select(Candidacy, Contest, Election, Jurisdiction)
        .join(Contest, Candidacy.contest_id == Contest.id)
        .join(Election, Contest.election_id == Election.id)
        .join(Jurisdiction, Contest.jurisdiction_id == Jurisdiction.id)
        .where(Election.election_date <= date.today(), Candidacy.candidate_kind == "candidate"))
    latest_query = latest_query.where(Candidacy.person_id == person.id if person else Candidacy.id == candidate.id)
    latest = session.execute(latest_query.order_by(Election.election_date.desc(), Contest.id, Candidacy.id).limit(1)).first()
    latest_election = None
    if latest:
        latest_candidate, latest_contest, latest_event, latest_geo = latest
        latest_election = dict(candidacy_id=latest_candidate.id, id=latest_contest.id,
            election_id=latest_event.id, election_date=latest_event.election_date,
            stage=latest_event.election_type, election_cycle=latest_event.election_cycle or latest_event.election_date.year,
            office_name=latest_contest.office_name, jurisdiction=_geography(latest_geo))
    cycle = election.election_cycle or election.election_date.year
    reviews = session.scalars(select(CandidateIdentityReview).where(
        CandidateIdentityReview.candidacy_id == candidate.id).order_by(
            CandidateIdentityReview.created_at, CandidateIdentityReview.id)).all()
    accepted = [r for r in reviews if r.status == "accepted"]
    pending = [r for r in reviews if r.status == "pending"]
    identifiers = session.scalars(select(ExternalIdentifier).where(or_(
        ExternalIdentifier.candidacy_id == candidate.id,
        ExternalIdentifier.person_id == person.id if person else False)).order_by(
            ExternalIdentifier.namespace, ExternalIdentifier.identifier_type, ExternalIdentifier.value)).all()
    # Person IDs can span offices. Only the accepted match's ID or a direct
    # candidacy identifier is eligible for finance; never sum all a person's IDs.
    eligible_ids = {item.id for item in identifiers if item.namespace == "fec"
                    and item.identifier_type == "candidate" and item.candidacy_id == candidate.id}
    if accepted:
        eligible_ids.add(session.get(FecCandidateRecord, accepted[0].record_id).identifier_id)
    finance = dict(status="identity_unresolved" if not person else "missing", cycle=cycle)
    if len(eligible_ids) > 1:
        finance["status"] = "ambiguous"
    elif len(eligible_ids) == 1:
        summaries = session.scalars(select(CandidateFinanceSummary).join(SourceRelease).where(
            CandidateFinanceSummary.identifier_id.in_(eligible_ids), CandidateFinanceSummary.cycle == cycle)
            .order_by(SourceRelease.retrieved_at.desc(), SourceRelease.id)).all()
        if summaries:
            latest = session.get(SourceRelease, summaries[0].release_id)
            tied = [item for item in summaries if session.get(SourceRelease, item.release_id).retrieved_at == latest.retrieved_at]
            if len(tied) > 1:
                finance["status"] = "ambiguous"
            else:
                summary = summaries[0]
                finance.update(finance_values(summary), source=_source(session, summary.release_id),
                    fec_candidate_id=session.get(ExternalIdentifier, summary.identifier_id).value)
    committees = []
    # Explicit cycle and candidacy scope prevents historical or unrelated
    # person committees from appearing as this candidacy's authorized campaign.
    links = session.scalars(select(CommitteeRelationship).where(
        CommitteeRelationship.candidacy_id == candidate.id, CommitteeRelationship.cycle == cycle)
        .order_by(CommitteeRelationship.organization_id, CommitteeRelationship.id)).all()
    for link in links:
        organization = session.get(Organization, link.organization_id)
        ids = session.scalars(select(ExternalIdentifier.value).where(
            ExternalIdentifier.organization_id == organization.id, ExternalIdentifier.namespace == "fec",
            ExternalIdentifier.identifier_type == "committee").order_by(ExternalIdentifier.value)).all()
        committees.append(dict(id=organization.id, name=organization.name, role=link.role, cycle=link.cycle,
            fec_ids=list(ids), evidence=link.evidence, source_record_key=link.source_record_key,
            source=_source(session, link.release_id) if link.release_id else None,
            source_id=link.source_id))
    level = reporting_level or ("state" if contest.office_name == "U.S. Senate" else
        "congressional_district" if geography.level == "congressional_district" else "county")
    results = list_results(session, ResultFilters(contest_id=contest.id, reporting_level=level, limit=limit, offset=offset),
                           candidacy_id=candidate.id)
    return dict(id=candidate.id, label=person.full_name if person else candidate.source_label,
        source_label=candidate.source_label, candidate_kind=candidate.candidate_kind,
        person=dict(id=person.id, full_name=person.full_name) if person else None,
        identity_status="resolved" if person else "pending_review" if pending else "unresolved",
        identity_evidence=[dict(status=r.status, confidence=r.confidence, evidence=r.evidence_json,
            decision_evidence=r.decision_evidence, decided_at=r.decided_at, record_id=r.record_id,
            source=_source(session, r.release_id),
            fec_candidate_id=session.get(ExternalIdentifier, session.get(FecCandidateRecord, r.record_id).identifier_id).value
                if r.record_id else None) for r in reviews],
        identifiers=[dict(namespace=i.namespace, identifier_type=i.identifier_type, value=i.value,
            evidence=i.evidence, source=_source(session, i.release_id) if i.release_id else None,
            source_id=i.source_id) for i in identifiers],
        contest=dict(id=contest.id, election_id=election.id, election_date=election.election_date,
            stage=election.election_type, election_cycle=cycle, office_name=contest.office_name,
            jurisdiction=_geography(geography)), latest_election=latest_election,
        committees=committees, finance=finance, results=results)
