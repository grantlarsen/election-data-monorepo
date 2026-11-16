"""Export DATA-005's current stored and planned scope in one read-only snapshot."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import engine
from app.models.election import CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn
from app.services.canonical_results import _plan
from app.services.geo001_audit import all_fingerprints


def snapshot(session):
    plan = _plan(session, 2008, None)
    pointer = session.get(CanonicalPublication, 'medsl_presidential_county:2008:county_total')
    if pointer is None:
        raise ValueError('Missing 2008 canonical publication')
    batch = session.get(CanonicalResultBatch, pointer.batch_id)
    stored = {str(r.observation_id): r for r in session.scalars(
        select(CanonicalVoteReturn).where(CanonicalVoteReturn.batch_id == batch.id))}
    accepted = {str(o.id) for o, *_ in plan['accepted']}
    rejected = {str(o.id): reason for o, reason in plan['rejected']}
    heads = {}
    for g in session.execute(text('''SELECT g.*, r.name_raw AS reference_label,
            r.release_id AS matched_reference_release_id FROM geographic_resolution g
            LEFT JOIN geographic_reference r ON r.id=g.reference_id
            JOIN election_result_observation o ON o.id=g.observation_id
            WHERE o.year=2008 AND o.release_id=:source AND g.reference_release_id=:ref
            AND NOT EXISTS(SELECT 1 FROM geographic_resolution c WHERE c.supersedes_id=g.id)'''),
            {'source': plan['release'].id, 'ref': plan['ref_release']}).mappings():
        key = str(g['observation_id'])
        if key in heads:
            raise ValueError(f'Multiple geographic heads for {key}')
        heads[key] = dict(g)
    rows = []
    for o in plan['observations']:
        if str(o.id) not in heads:
            raise ValueError(f'Expected exactly one geographic head for {o.id}')
        head = heads[str(o.id)]
        previous = stored.get(str(o.id))
        rows.append(dict(observation_id=str(o.id), source_row_number=o.source_row_number,
            row_sha256=o.row_sha256, release_id=str(o.release_id), state=o.state_code,
            county=o.county_raw, county_fips=o.county_fips, candidate=o.candidate_normalized,
            candidate_kind=o.candidate_kind, party=o.party_normalized, mode=o.mode_normalized,
            votes=o.candidate_votes, total_votes=o.total_votes, raw_json=o.raw_json,
            stored_accepted=previous is not None, stored_votes=previous.votes if previous else None,
            stored_resolution_id=str(previous.geographic_resolution_id) if previous else None,
            preview_accepted=str(o.id) in accepted, preview_reason=rejected.get(str(o.id)),
            geography=head))
    release = plan['release']
    source_path = Path(release.raw_path)
    if not source_path.is_absolute():
        source_path = Path('/app') / source_path
    source_sha = sha256(source_path.read_bytes()).hexdigest()
    if source_sha != release.sha256:
        raise ValueError('MEDSL archived source checksum mismatch')
    result = dict(generated_at=datetime.now(timezone.utc).isoformat(),
        isolation=session.scalar(text('SHOW transaction_isolation')),
        read_only=session.scalar(text('SHOW transaction_read_only')),
        alembic_revision=session.scalar(text('SELECT version_num FROM alembic_version')),
        source=dict(id=str(release.id), version=release.version, sha256=release.sha256,
                    download_url=release.download_url, raw_path=release.raw_path,
                    archived_sha256=source_sha),
        stored_batch=dict(id=str(batch.id), fingerprint=batch.fingerprint, status=batch.status,
            accepted_rows=batch.accepted_rows, excluded_rows=batch.excluded_rows,
            canonical_votes=batch.canonical_votes),
        preview=dict(fingerprint=plan['fingerprint'], accepted_rows=len(accepted),
            excluded_rows=len(rejected), canonical_votes=plan['target_sum'],
            reference_release_id=str(plan['ref_release'])), observations=rows,
        fingerprints=all_fingerprints(session.connection()))
    if len(stored) != batch.accepted_rows or sum(r.votes for r in stored.values()) != batch.canonical_votes:
        raise ValueError('Stored batch accounting mismatch')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Refusing to replace existing snapshot')
    with Session(engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        result = snapshot(session)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('alembic_revision', 'source', 'stored_batch', 'preview')}))


if __name__ == '__main__':
    main()
