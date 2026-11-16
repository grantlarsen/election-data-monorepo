"""Append-only publication of checksum-pinned FEC presidential state summaries."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.core import DataSource, Jurisdiction
from app.models.ingestion import IngestionRun, SourceRelease
from app.models.state_results import StateResultBatch, StateResultPublication, StateVoteReturn
from app.services.fec_state_results import state_contest
from ingestion.medsl import STATE_NAMES
from ingestion.presidential_state_returns import RULESET, digest, scope, verify_package
from ingestion.source import sha256_file

logger = logging.getLogger(__name__)


def projection(session: Session, package: dict, directory: Path) -> dict:
    verify_package(package)
    source = package['source']
    url = urlsplit(source['url'])
    if url.scheme != 'https' or url.hostname != 'www.fec.gov':
        raise ValueError('Expected an official FEC HTTPS source')
    archive = (directory / source['filename']).resolve()
    if archive.parent != directory.resolve() or sha256_file(archive) != source['sha256']:
        raise ValueError('Original FEC workbook checksum mismatch')
    groups = {}
    for item in session.scalars(select(Jurisdiction).where(Jurisdiction.level == 'state')):
        if item.state_code in groups:
            raise ValueError('Ambiguous state jurisdiction')
        groups[item.state_code] = str(item.id)
    if not set(STATE_NAMES).issubset(groups):
        raise ValueError('Missing state jurisdictions')
    manifest = dict(format=RULESET, scope=scope(package['year']), package=package,
                    jurisdictions={st: groups[st] for st in sorted(STATE_NAMES)})
    return dict(manifest=manifest, fingerprint=digest(manifest), archive=archive)


def publish(session: Session, package: dict, directory: Path, *, expected_fingerprint: str,
            actor: str, authorization_note: str) -> dict:
    if not actor.strip() or len(actor) > 100 or not authorization_note.strip():
        raise ValueError('Publishing actor and authorization note are required')
    if session.scalar(text('SHOW transaction_isolation')) != 'repeatable read':
        raise ValueError('Publication requires REPEATABLE READ')
    year = package['year']
    key = scope(year)
    session.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'), {'scope': key})
    plan = projection(session, package, directory)
    if plan['fingerprint'] != expected_fingerprint:
        raise ValueError('Stale FEC publication fingerprint')
    pointer = session.get(StateResultPublication, key)
    if pointer and session.get(StateResultBatch, pointer.batch_id).fingerprint == expected_fingerprint:
        read_totals(session, year=year)
        logger.info('Presidential state publication unchanged', extra={'year':year, 'batch_id':str(pointer.batch_id)})
        return dict(action='UNCHANGED', year=year, batch_id=str(pointer.batch_id), fingerprint=expected_fingerprint)
    if session.scalar(select(StateResultBatch.id).where(StateResultBatch.scope_key == key,
                                                       StateResultBatch.fingerprint == expected_fingerprint)):
        raise ValueError('Historical batch reactivation requires explicit review')
    source = session.scalar(select(DataSource).where(DataSource.name == 'fec_presidential_official'))
    if source is None:
        source = DataSource(name='fec_presidential_official', url=package['source']['url'])
        session.add(source)
        session.flush()
    spec = package['source']
    version = f'{year}-summary'
    release = session.scalar(select(SourceRelease).where(SourceRelease.source_id == source.id,
        SourceRelease.version == version, SourceRelease.sha256 == spec['sha256']))
    if release is None:
        release = SourceRelease(source_id=source.id, version=version, sha256=spec['sha256'],
            filename=spec['filename'], file_id=0, download_url=spec['url'], raw_path=str(plan['archive']),
            retrieved_at=datetime.fromisoformat(spec['retrieved_at']),
            metadata_json=dict(authority='FEC', reporting_level='state', extraction=spec,
                               package_sha256=digest(package), resource_id_namespace='FEC URL; file_id unused'))
        session.add(release)
        session.flush()
    batch = StateResultBatch(scope_key=key, fingerprint=expected_fingerprint, ruleset_version=RULESET,
        election_year=year, source_release_id=release.id, published_by=actor,
        authorization_note=authorization_note, manifest_json=plan['manifest'],
        supersedes_id=pointer.batch_id if pointer else None)
    session.add(batch)
    session.flush()
    for state in package['states']:
        st = state['state_code']
        jurisdiction_id = UUID(plan['manifest']['jurisdictions'][st])
        contest = state_contest(session, st, jurisdiction_id, year=year)
        for bucket, votes in state['votes'].items():
            session.add(StateVoteReturn(batch_id=batch.id, state_code=st, candidate_bucket=bucket,
                jurisdiction_id=jurisdiction_id, contest_id=contest.id, votes=votes,
                medsl_source_votes=None, medsl_county_votes=None, source_adjustment=None,
                source_locator=state['source_locator'],
                components_json=[dict(bucket=bucket, votes=votes, source_locator=state['source_locator'])]))
    session.flush()
    session.execute(pg_insert(StateResultPublication).values(scope_key=key, batch_id=batch.id)
        .on_conflict_do_update(index_elements=['scope_key'], set_={'batch_id':batch.id, 'published_at':datetime.now(timezone.utc)}))
    session.expire_all()
    read_totals(session, year=year)
    now = datetime.now(timezone.utc)
    session.add(IngestionRun(source_id=source.id, release_id=release.id, status='SUCCEEDED',
        started_at=now, completed_at=now, records_read=153, records_inserted=153,
        records_updated=0, records_rejected=0, warnings_json=[], errors_json=[],
        options_json=dict(year=year, ruleset=RULESET, batch_id=str(batch.id),
                          package_sha256=digest(package), fingerprint=expected_fingerprint), raw_sha256=release.sha256))
    session.flush()
    logger.info('Presidential state publication created', extra={'year':year, 'batch_id':str(batch.id), 'rows':153})
    return dict(action='CREATED', year=year, batch_id=str(batch.id), fingerprint=expected_fingerprint,
                states=51, rows=153, votes=sum(s['total_votes'] for s in package['states']))


def read_totals(session: Session, *, year: int, state_code: str | None = None) -> dict:
    key = scope(year)
    if state_code is not None and state_code not in STATE_NAMES:
        raise ValueError('Unknown state code')
    pointer = session.get(StateResultPublication, key)
    if pointer is None:
        raise ValueError('No published authoritative state totals')
    batch = session.get(StateResultBatch, pointer.batch_id)
    manifest = batch.manifest_json
    if (batch.election_year != year or batch.scope_key != key or batch.ruleset_version != RULESET
            or digest(manifest) != batch.fingerprint or manifest['scope'] != key):
        raise ValueError('Invalid presidential state manifest')
    package = manifest['package']
    verify_package(package)
    release = session.get(SourceRelease, batch.source_release_id)
    if package['year'] != year or release.sha256 != package['source']['sha256']:
        raise ValueError('State release differs from its manifest')
    rows = list(session.scalars(select(StateVoteReturn).where(StateVoteReturn.batch_id == batch.id)
                               .order_by(StateVoteReturn.state_code, StateVoteReturn.candidate_bucket)))
    expected = {(s['state_code'], b): (v, s['source_locator']) for s in package['states'] for b, v in s['votes'].items()}
    if len(rows) != 153:
        raise ValueError('Incomplete state publication')
    for row in rows:
        target = expected.get((row.state_code, row.candidate_bucket))
        if (target != (row.votes, row.source_locator) or
                str(row.jurisdiction_id) != manifest['jurisdictions'][row.state_code] or
                any(v is not None for v in (row.medsl_source_votes, row.medsl_county_votes, row.source_adjustment)) or
                row.components_json != [dict(bucket=row.candidate_bucket, votes=row.votes, source_locator=row.source_locator)]):
            raise ValueError('State returns differ from their immutable manifest')
    return dict(year=year, scope=key, batch_id=str(batch.id), source='FEC', source_release_id=str(release.id),
        reporting_level='state', reporting_mode='TOTAL', additive_with_county_returns=False,
        county_coverage_verified=False, results=[dict(state_code=r.state_code, candidate_bucket=r.candidate_bucket,
            votes=r.votes, source_locator=r.source_locator, source_adjustment=None,
            medsl_source_votes=None, medsl_county_votes=None) for r in rows if state_code is None or r.state_code == state_code])
