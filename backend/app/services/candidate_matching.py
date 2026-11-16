"""Conservative MEDSL/FEC matching; name equality only creates review proposals."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import re
import unicodedata
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate_identity import CandidateIdentityReview, FecCandidateRecord
from app.models.core import Candidacy, Contest, Election, Jurisdiction
from app.models.geography import GeographicReference
from app.models.identity import ExternalIdentifier
from app.services.identity import (
    IdentityConflictError, _key, attach_external_identifier, create_person,
    link_committee, lookup_identifier, register_organization, resolve_external_identifier,
)

RULESET = "candidate-identity-v1"
OFFICES = {"u.s. house": "H", "u.s. senate": "S", "u.s. president": "P",
           "president of the united states": "P", "us president": "P"}


def comparable_name(value: str) -> str:
    """Reorder LAST, FIRST while preserving initials and suffixes; no nickname guesses."""
    if "," in value:
        last, first = value.split(",", 1)
        value = f"{first} {last}"
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", value).split())


def candidate_context(session: Session, candidacy: Candidacy) -> dict:
    contest = session.get(Contest, candidacy.contest_id)
    election = session.get(Election, contest.election_id)
    geography = session.get(Jurisdiction, contest.jurisdiction_id)
    year = election.election_date.year
    office = OFFICES.get(contest.office_name.lower())
    district = "00"
    if office == "H":
        codes = set(session.scalars(select(GeographicReference.geoid).where(
            GeographicReference.jurisdiction_id == geography.id,
            GeographicReference.kind == "congressional_district",
            GeographicReference.vintage_start <= year, GeographicReference.vintage_end >= year)).all())
        district = next(iter(codes))[-2:] if len(codes) == 1 else None
        if geography.state_code == "DC" and district == "98":
            district = "00"  # FEC at-large/delegate identifier vs Census delegate geography.
    return dict(year=year, office=office, state_code="US" if office == "P" else geography.state_code,
                district=district, source_label=candidacy.source_label, contest_id=str(contest.id))


def same_scope(record: FecCandidateRecord, context: dict) -> bool:
    return (record.district is not None and context["district"] is not None
            and record.raw_json.get("CAND_ID", record.office).startswith(record.office)
            and record.election_year == context["year"] and record.cycle == context["year"]
            and record.office == context["office"] and record.state_code == context["state_code"]
            and record.district == context["district"])


def match_candidate(session: Session, *, candidacy_id: UUID, release_id: UUID,
                    records: list[FecCandidateRecord] | None = None) -> dict:
    session.flush()
    candidate = session.scalar(select(Candidacy).where(Candidacy.id == candidacy_id).with_for_update()
        .execution_options(populate_existing=True))
    if candidate is None:
        raise ValueError("Candidacy not found")
    if candidate.candidate_kind != "candidate":
        return {"excluded": 1}
    previous = session.scalars(select(CandidateIdentityReview).where(
        CandidateIdentityReview.candidacy_id == candidate.id)).all()
    if any(item.status == "accepted" for item in previous):
        return {"unchanged": 1}
    context = candidate_context(session, candidate)
    if records is None:
        records = list(session.scalars(select(FecCandidateRecord).where(FecCandidateRecord.release_id == release_id)
            .order_by(FecCandidateRecord.identifier_id)).all())
    if not records:
        raise ValueError("Selected release contains no FEC candidate master records")
    direct = session.scalars(select(ExternalIdentifier.id).where(
        ExternalIdentifier.namespace == "fec", ExternalIdentifier.identifier_type == "candidate",
        ExternalIdentifier.candidacy_id == candidate.id)).all()
    # Official IDs take precedence, including contradictory evidence: never fall back
    # to a matching name when an explicit authoritative ID exists.
    if direct:
        proposals = [record for record in records if record.identifier_id in direct]
        reason = "official_identifier"
    else:
        proposals = [record for record in records if same_scope(record, context)
                     and comparable_name(record.name) == comparable_name(candidate.source_label or "")]
        reason = "exact_name_and_scope_requires_review"
    counts = Counter()
    for record in proposals:
        # Rejections are stable non-merge assertions; new source releases retain
        # separate pending evidence so corrected records can be reviewed.
        if any(item.status == "rejected" and item.evidence_json.get("identifier_id") == str(record.identifier_id) for item in previous):
            counts["unchanged"] += 1
            continue
        dedupe = _key(dict(candidacy=candidate.id, identifier=record.identifier_id, release=release_id))
        existing = next((item for item in previous if item.dedupe_key == dedupe), None)
        if existing:
            counts["unchanged"] += 1
            continue
        row = CandidateIdentityReview(candidacy_id=candidate.id, release_id=release_id,
            record_id=record.id, dedupe_key=dedupe, status="pending",
            confidence=Decimal("1") if direct and same_scope(record, context) else Decimal("0.8") if not direct else Decimal("0"),
            evidence_json=dict(ruleset=RULESET, reason=reason, context=context,
                fec_name=record.name, scope_agrees=same_scope(record, context),
                alternatives=len(proposals), identifier_id=str(record.identifier_id)))
        session.add(row)
        session.flush()
        if direct and len(proposals) == 1 and len(direct) == 1 and same_scope(record, context):
            decide_match(session, review_id=row.id, accept=True, actor=RULESET,
                         evidence="Existing FEC identifier on candidacy and exact election/office/geography scope")
            counts["accepted"] += 1
        else:
            counts["pending"] += 1
    if not proposals:
        dedupe = _key(dict(candidacy=candidate.id, unmatched_release=release_id))
        if any(item.dedupe_key == dedupe for item in previous):
            counts["unchanged"] += 1
        else:
            session.add(CandidateIdentityReview(candidacy_id=candidate.id, release_id=release_id,
                record_id=None, dedupe_key=dedupe, status="unmatched", confidence=Decimal("0"),
                evidence_json=dict(ruleset=RULESET, context=context, reason="official_id_missing_from_release" if direct else "no_exact_name_and_scope")))
            counts["unmatched"] += 1
    session.flush()
    return dict(counts)


def propose_match(session: Session, *, candidacy_id: UUID, record_id: UUID,
                  actor: str, evidence: str) -> CandidateIdentityReview:
    """Let operators propose an alias match without weakening automatic matching."""
    if not actor.strip() or not evidence.strip() or len(actor) > 150:
        raise ValueError("Manual proposal requires actor and supporting evidence")
    session.flush()
    candidate = session.scalar(select(Candidacy).where(Candidacy.id == candidacy_id).with_for_update()
        .execution_options(populate_existing=True))
    record = session.get(FecCandidateRecord, record_id)
    if candidate is None or record is None or candidate.candidate_kind != "candidate":
        raise ValueError("Named candidacy and FEC record required")
    context = candidate_context(session, candidate)
    if not same_scope(record, context):
        raise IdentityConflictError("Candidate and FEC scopes disagree")
    rejected = session.scalars(select(CandidateIdentityReview).where(
        CandidateIdentityReview.candidacy_id == candidate.id, CandidateIdentityReview.status == "rejected")).all()
    if any(item.evidence_json.get("identifier_id") == str(record.identifier_id) for item in rejected):
        raise IdentityConflictError("Explicit non-merge assertion forbids this candidate/identifier pair")
    dedupe = _key(dict(candidacy=candidate.id, identifier=record.identifier_id, release=record.release_id))
    existing = session.scalar(select(CandidateIdentityReview).where(CandidateIdentityReview.dedupe_key == dedupe))
    if existing:
        return existing
    row = CandidateIdentityReview(candidacy_id=candidate.id, release_id=record.release_id,
        record_id=record.id, dedupe_key=dedupe, status="pending", confidence=Decimal("0"),
        evidence_json=dict(ruleset=RULESET, reason="manual_proposal", context=context,
            actor=actor, evidence=evidence, identifier_id=str(record.identifier_id)))
    session.add(row)
    session.flush()
    return row


def decide_match(session: Session, *, review_id: UUID, accept: bool, actor: str,
                 evidence: str) -> CandidateIdentityReview:
    if not actor.strip() or not evidence.strip() or len(actor) > 150:
        raise ValueError("Decision requires actor (up to 150 characters) and supporting evidence")
    session.flush()
    initial = session.get(CandidateIdentityReview, review_id)
    if initial is None:
        raise ValueError("Review not found")
    candidate = session.scalar(select(Candidacy).where(Candidacy.id == initial.candidacy_id).with_for_update()
        .execution_options(populate_existing=True))
    row = session.scalar(select(CandidateIdentityReview).where(CandidateIdentityReview.id == review_id)
                         .with_for_update().execution_options(populate_existing=True))
    status = "accepted" if accept else "rejected"
    if row.status == status:
        return row
    if row.status != "pending" or row.record_id is None:
        raise IdentityConflictError("A completed decision cannot be overwritten")
    if not accept:
        record = session.get(FecCandidateRecord, row.record_id)
        accepted_records = session.scalars(select(FecCandidateRecord.identifier_id).join(
            CandidateIdentityReview, CandidateIdentityReview.record_id == FecCandidateRecord.id).where(
                CandidateIdentityReview.candidacy_id == candidate.id, CandidateIdentityReview.status == "accepted")).all()
        if record.identifier_id in accepted_records:
            raise IdentityConflictError("An accepted identifier cannot also receive a non-merge assertion")
    if accept:
        accepted = session.scalar(select(CandidateIdentityReview.id).where(
            CandidateIdentityReview.candidacy_id == candidate.id, CandidateIdentityReview.status == "accepted"))
        if accepted:
            raise IdentityConflictError("Candidacy already has an accepted identity")
        record = session.get(FecCandidateRecord, row.record_id)
        rejected = session.scalars(select(CandidateIdentityReview).where(
            CandidateIdentityReview.candidacy_id == candidate.id, CandidateIdentityReview.status == "rejected")).all()
        if any(item.evidence_json.get("identifier_id") == str(record.identifier_id) for item in rejected):
            raise IdentityConflictError("Explicit non-merge assertion forbids this candidate/identifier pair")
        if record.release_id != row.release_id or not same_scope(record, candidate_context(session, candidate)):
            raise IdentityConflictError("Candidate and FEC election/office/geography scopes disagree")
        identifier = session.scalar(select(ExternalIdentifier).where(
            ExternalIdentifier.id == record.identifier_id).with_for_update().execution_options(populate_existing=True))
        person_id = identifier.person_id
        if identifier.candidacy_id:
            person_id = session.get(Candidacy, identifier.candidacy_id).person_id
        if person_id and candidate.person_id and person_id != candidate.person_id:
            raise IdentityConflictError("Existing person assignment disagrees; no automatic person merge")
        if not person_id:
            person_id = candidate.person_id or create_person(session, full_name=record.name,
                creation_key=f"fec:candidate:{identifier.value}").id
        if identifier.person_id is None and identifier.candidacy_id is None:
            resolve_external_identifier(session, identifier_id=identifier.id, target_type="person",
                target_id=person_id, actor=actor, evidence=evidence)
        elif identifier.candidacy_id and identifier.candidacy_id != candidate.id:
            old = session.get(Candidacy, identifier.candidacy_id)
            if old.person_id is None:
                raise IdentityConflictError("FEC ID points to another unresolved candidacy; review it first")
        candidate.person_id = person_id
        if record.principal_committee:
            committee = lookup_identifier(session, namespace="fec", identifier_type="committee", value=record.principal_committee)
            organization = None
            if committee and committee.organization_id:
                from app.models.identity import Organization
                organization = session.get(Organization, committee.organization_id)
            if organization is None:
                organization = register_organization(session, name=f"FEC committee {record.principal_committee}",
                    kind="committee", creation_key=f"fec:committee:{record.principal_committee}")
                if committee:
                    resolve_external_identifier(session, identifier_id=committee.id, target_type="organization",
                        target_id=organization.id, actor=actor, evidence=evidence)
                else:
                    from app.models.ingestion import SourceRelease
                    release = session.get(SourceRelease, record.release_id)
                    attach_external_identifier(session, namespace="fec", identifier_type="committee",
                        value=record.principal_committee, source_id=release.source_id, release_id=release.id,
                        target_type="organization", target_id=organization.id, actor=actor, evidence=evidence)
            from app.models.ingestion import SourceRelease
            release = session.get(SourceRelease, record.release_id)
            link_committee(session, organization_id=organization.id, person_id=person_id,
                candidacy_id=candidate.id, cycle=record.cycle, role="principal_campaign",
                source_id=release.source_id, release_id=release.id,
                source_record_key=identifier.value, evidence="FEC candidate master CAND_PCC; " + evidence)
    row.status, row.actor, row.decision_evidence = status, actor, evidence
    row.decided_at = datetime.now(timezone.utc)
    session.flush()
    return row
