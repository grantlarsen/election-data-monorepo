"""Operator import, matching and review commands. No public write API."""
import argparse
from collections import Counter
from datetime import datetime
import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import engine
from app.models.candidate_identity import CandidateIdentityReview, FecCandidateRecord
from app.models.core import Candidacy, Contest, Election
from app.models.identity import ExternalIdentifier
from app.services.candidate_matching import decide_match, match_candidate, propose_match
from ingestion.fec_candidates import load, parse

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("import-fec")
    ingest.add_argument("--kind", choices=["master", "summary"], required=True)
    ingest.add_argument("--path", type=Path, required=True)
    ingest.add_argument("--cycle", type=int, required=True)
    ingest.add_argument("--sha256", required=True)
    ingest.add_argument("--retrieved-at", type=datetime.fromisoformat, required=True)
    ingest.add_argument("--data-dir", type=Path, default=Path("data/ingestion"))
    ingest.add_argument("--validate-only", action="store_true")
    match = commands.add_parser("match")
    match.add_argument("--release-id", type=UUID, required=True)
    match.add_argument("--year", type=int, required=True)
    match.add_argument("--candidacy-id", type=UUID)
    queue = commands.add_parser("queue")
    queue.add_argument("--status", choices=["pending", "unmatched", "accepted", "rejected"], default="pending")
    queue.add_argument("--limit", type=int, default=100)
    queue.add_argument("--offset", type=int, default=0)
    records = commands.add_parser("records")
    records.add_argument("--release-id", type=UUID, required=True)
    records.add_argument("--fec-id", required=True)
    proposal = commands.add_parser("propose")
    proposal.add_argument("--candidacy-id", type=UUID, required=True)
    proposal.add_argument("--record-id", type=UUID, required=True)
    proposal.add_argument("--actor", required=True)
    proposal.add_argument("--evidence", required=True)
    review = commands.add_parser("decide")
    review.add_argument("--review-id", type=UUID, required=True)
    review.add_argument("--decision", choices=["accept", "reject"], required=True)
    review.add_argument("--actor", required=True)
    review.add_argument("--evidence", required=True)
    args = parser.parse_args()
    try:
        if args.command == "import-fec":
            if args.validate_only:
                from ingestion.source import sha256_file
                if sha256_file(args.path) != args.sha256:
                    raise ValueError("Pinned SHA-256 does not match input")
                result = {"validated": len(parse(args.path, args.kind, cycle=args.cycle)), "database_writes": False}
            else:
                result = load(engine, path=args.path, kind=args.kind, cycle=args.cycle, sha256=args.sha256,
                    retrieved_at=args.retrieved_at, data_dir=args.data_dir)
        else:
            with Session(engine) as session, session.begin():
                if args.command == "match":
                    if args.year < 1788 or args.year > 9998:
                        raise ValueError("Invalid election year")
                    records = list(session.scalars(select(FecCandidateRecord).where(
                        FecCandidateRecord.release_id == args.release_id)).all())
                    if not records or any(r.cycle != args.year for r in records):
                        raise ValueError("Select a candidate master release for the requested election cycle")
                    query = select(Candidacy.id).join(Contest).join(Election).where(
                        Election.election_date >= datetime(args.year, 1, 1).date(),
                        Election.election_date < datetime(args.year + 1, 1, 1).date())
                    if args.candidacy_id:
                        query = query.where(Candidacy.id == args.candidacy_id)
                    counts = Counter()
                    ids = session.scalars(query.order_by(Candidacy.id)).all()
                    for candidate_id in ids:
                        counts.update(match_candidate(session, candidacy_id=candidate_id,
                            release_id=args.release_id, records=records))
                    result = dict(candidacies=len(ids), decisions=dict(counts))
                elif args.command == "queue":
                    if not 1 <= args.limit <= 1000 or args.offset < 0:
                        raise ValueError("Queue limit must be 1..1000 and offset nonnegative")
                    query = select(CandidateIdentityReview).where(CandidateIdentityReview.status == args.status)
                    if args.status in {"pending", "unmatched"}:
                        query = query.where(CandidateIdentityReview.candidacy_id.not_in(select(
                            CandidateIdentityReview.candidacy_id).where(CandidateIdentityReview.status == "accepted")))
                    rows = session.scalars(query.order_by(
                            CandidateIdentityReview.created_at, CandidateIdentityReview.id)
                        .limit(args.limit).offset(args.offset)).all()
                    result = []
                    for row in rows:
                        record = session.get(FecCandidateRecord, row.record_id) if row.record_id else None
                        identifier = session.get(ExternalIdentifier, record.identifier_id) if record else None
                        result.append(dict(id=row.id, candidacy_id=row.candidacy_id, record_id=row.record_id,
                            fec_candidate_id=identifier.value if identifier else None,
                            release_id=row.release_id, status=row.status, confidence=row.confidence,
                            evidence=row.evidence_json, decision_evidence=row.decision_evidence))
                elif args.command == "records":
                    rows = session.scalars(select(FecCandidateRecord).join(ExternalIdentifier).where(
                        FecCandidateRecord.release_id == args.release_id, ExternalIdentifier.value == args.fec_id)).all()
                    result = [dict(record_id=r.id, raw=r.raw_json) for r in rows]
                elif args.command == "propose":
                    row = propose_match(session, candidacy_id=args.candidacy_id, record_id=args.record_id,
                        actor=args.actor, evidence=args.evidence)
                    result = dict(review_id=row.id, status=row.status)
                else:
                    row = decide_match(session, review_id=args.review_id, accept=args.decision == "accept",
                        actor=args.actor, evidence=args.evidence)
                    result = dict(review_id=row.id, status=row.status)
        print(json.dumps(result, default=str, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        logger.error("Candidate identity operation failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
