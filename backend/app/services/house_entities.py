"""Source-scoped House profiles and reviewed incumbency; no vote publication/person matching."""
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.core import Candidacy, Contest, DataSource, Jurisdiction, PoliticalParty
from app.models.ingestion import IngestionRun, SourceRelease
from app.services import elections
from app.services.house_results import cache_directory, read_snapshot, house_control
from app.services.senate_entities import BUCKETS, PARTIES
from app.services.canonical_results import MaterializationError
from app.services.candidate_media import candidate_portrait
from ingestion.current_house import YEAR, ELECTION_DATE, EXPECTED_CONTESTS, utc_timestamp

SOURCE = 'call_the_map_house'
PREFIX = f'{SOURCE}:{YEAR}:'
CATALOG = Path(__file__).resolve().parents[2] / 'ingestion/catalog/house_incumbents.json'
RULESET = 'current-house-entities-v1'


def candidate_key(race_id: str, candidate: dict) -> str | None:
    if candidate['name'].strip().casefold() in BUCKETS:
        return None
    return PREFIX + sha256(json.dumps([race_id, candidate['name'], candidate['party']], ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=1)
def incumbent_catalog() -> dict:
    data = json.loads(CATALOG.read_text(encoding='utf-8'))
    if data['year'] != YEAR or data['as_of'] != ELECTION_DATE:
        raise ValueError('House incumbency evidence does not cover this election')
    data['_index'] = {(r['race_id'], r['state'], r['name'], r['party']): r for r in data['candidates']}
    if len(data['_index']) != len(data['candidates']):
        raise ValueError('Duplicate House incumbent annotations')
    return data


def incumbent_evidence(race: dict, candidate: dict, catalog: dict) -> dict | None:
    row = catalog['_index'].get((race['id'], race['state_code'], candidate['name'], candidate['party']))
    return {**row, 'as_of': catalog['as_of'], 'url': catalog['source_url'],
            'source_sha256': catalog['source_sha256'], 'method': catalog['method']} if row else None


def enrich_snapshot(session: Session, snapshot: dict) -> dict:
    result = deepcopy(snapshot)
    catalog = incumbent_catalog()
    candidates = {row.creation_key: row for row in session.scalars(select(Candidacy).where(Candidacy.creation_key.startswith(PREFIX, autoescape=True)))}
    contests = {row.creation_key: row for row in session.scalars(select(Contest).where(Contest.creation_key.startswith(PREFIX, autoescape=True)))}
    for race in result['races']:
        contest = contests.get(PREFIX + race['id'])
        race['contest_id'] = str(contest.id) if contest else None
        for candidate in race['candidates']:
            key = candidate_key(race['id'], candidate)
            identity = candidates.get(key)
            evidence = incumbent_evidence(race, candidate, catalog) if key else None
            candidate.update(candidacy_id=str(identity.id) if identity else None, kind='candidate' if key else 'aggregate',
                             incumbent=True if evidence else None, incumbent_evidence=evidence,
                             portrait=candidate_portrait(SOURCE, YEAR, race['id'], candidate['name'], candidate['party']) if key else None)
    result['control'] = house_control(result)
    return result


def sync_entities(session: Session, snapshot: dict, directory: Path | None = None) -> dict:
    session.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'), {'scope': PREFIX})
    catalog = incumbent_catalog()
    catalog_hash = sha256(CATALOG.read_bytes()).hexdigest()
    source = session.scalar(select(DataSource).where(DataSource.name == SOURCE))
    if source is None:
        source = DataSource(name=SOURCE, url='https://www.callthemap.com/results/data')
        session.add(source)
        session.flush()
    release = session.scalar(select(SourceRelease).where(SourceRelease.source_id == source.id,
        SourceRelease.version == snapshot['published_at'], SourceRelease.sha256 == snapshot['sha256']))
    if release is None:
        release = SourceRelease(source_id=source.id, version=snapshot['published_at'], sha256=snapshot['sha256'],
            filename='races.csv', file_id=1, download_url=snapshot['source_url'],
            raw_path=str((directory or cache_directory()) / 'raw' / f"{snapshot['sha256']}.csv"),
            retrieved_at=utc_timestamp(snapshot['retrieved_at']), published_at=utc_timestamp(snapshot['published_at']),
            metadata_json={'license': 'CC BY 4.0', 'manifest_url': snapshot['manifest_url'], 'ruleset': RULESET,
                           'file_id_semantics': 'Adapter-local file ordinal, not an upstream identifier'})
        session.add(release)
        session.flush()
    previous = session.scalar(select(IngestionRun).where(IngestionRun.release_id == release.id,
        IngestionRun.status == 'COMPLETED', IngestionRun.options_json['ruleset'].astext == RULESET,
        IngestionRun.options_json['incumbency_catalog_sha256'].astext == catalog_hash).limit(1))
    if previous:
        return {'status': 'unchanged', 'inserted': 0, 'unchanged': len(previous.options_json['source_rows']), 'run_id': str(previous.id)}
    started = datetime.now(timezone.utc)
    contests = {row.creation_key: row for row in session.scalars(select(Contest).where(Contest.creation_key.startswith(PREFIX, autoescape=True)))}
    known = set(session.scalars(select(Candidacy.creation_key).where(Candidacy.creation_key.startswith(PREFIX, autoescape=True))))
    parties = {row.name: row.id for row in session.scalars(select(PoliticalParty))}
    audit, inserted, excluded, scopes = [], 0, 0, []
    for race in snapshot['races']:
        if (race['id'] not in EXPECTED_CONTESTS or EXPECTED_CONTESTS[race['id']]['state_code'] != race['state_code']
                or EXPECTED_CONTESTS[race['id']]['district_code'] != race['district_code']):
            raise ValueError('Invalid House source contest scope')
        key = PREFIX + race['id']
        contest = contests.get(key)
        if contest is None:
            # An election-scoped logical district, never a guessed match to historical boundaries.
            geography = Jurisdiction(name=f"{race['state_name']} District {race['district_code']} (2026 election)",
                                     level='congressional_district', state_code=race['state_code'])
            session.add(geography)
            session.flush()
            event = elections.election(session, creation_key=key + ':event', election_date=date.fromisoformat(ELECTION_DATE),
                election_type='general', election_cycle=YEAR, jurisdiction_id=geography.id)
            contest = elections.contest(session, creation_key=key, office_name='U.S. House', election_id=event.id, jurisdiction_id=geography.id)
        scopes.append({'race_id': race['id'], 'contest_id': str(contest.id), 'jurisdiction_id': str(contest.jurisdiction_id),
                       'note': '2026 source district identity; no historical-boundary equivalence asserted'})
        for candidate in race['candidates']:
            creation_key = candidate_key(race['id'], candidate)
            if creation_key is None:
                excluded += 1
                continue
            entity = elections.candidacy(session, creation_key=creation_key, contest_id=contest.id,
                source_label=candidate['name'], party_id=parties.get(PARTIES.get(candidate['party'], '')))
            inserted += creation_key not in known
            audit.append({'candidacy_id': str(entity.id), 'race_id': race['id'], 'name': candidate['name'], 'party': candidate['party'],
                          'source_row_number': candidate['source_row_number'], 'incumbent_evidence': incumbent_evidence(race, candidate, catalog)})
    finished = datetime.now(timezone.utc)
    run = IngestionRun(source_id=source.id, release_id=release.id, status='COMPLETED', started_at=started, completed_at=finished,
        duration_ms=int((finished-started).total_seconds()*1000), records_read=snapshot['accepted_rows'], records_inserted=inserted,
        records_updated=0, records_rejected=0, raw_sha256=snapshot['sha256'], options_json={'ruleset': RULESET,
        'records_unchanged': len(audit)-inserted, 'excluded_anonymous_buckets': excluded, 'source_rows': audit,
        'district_scopes': scopes, 'incumbency_catalog_sha256': catalog_hash, 'note': 'No person matching or vote publication'})
    session.add(run)
    session.flush()
    return {'status': 'registered', 'inserted': inserted, 'unchanged': len(audit)-inserted, 'excluded': excluded, 'run_id': str(run.id)}


def sync_cached_entities(directory: Path | None = None) -> dict:
    from app.database import SessionLocal
    with SessionLocal() as session, session.begin():
        return sync_entities(session, read_snapshot(directory), directory)


def provisional_profile(session: Session, candidate: Candidacy) -> dict | None:
    if not (candidate.creation_key or '').startswith(PREFIX):
        return None
    try:
        snapshot = enrich_snapshot(session, read_snapshot())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MaterializationError('Current House source snapshot is unavailable') from exc
    for race in snapshot['races']:
        if any(row['candidacy_id'] == str(candidate.id) for row in race['candidates']):
            return {'race': race, **{key: snapshot[key] for key in ('checked_at', 'retrieved_at', 'stale', 'sha256')}}
    return None
