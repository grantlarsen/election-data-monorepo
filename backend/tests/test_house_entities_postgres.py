from copy import deepcopy
from hashlib import sha256
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api import house
from app.services import house_entities as entities
from app.models.core import Candidacy, Jurisdiction
from app.models.election import CanonicalVoteReturn
from test_election_api import api_engine, client
from test_candidate_results import candidate_tables
from test_data004_postgres import pg, migration
from test_current_house import rows, parse


def test_house_profiles_replay_audit_and_api_without_person_matching(api_engine, client, rows, tmp_path, monkeypatch):
    for row in rows:
        row.update(race_id='IA-03', state='IA')
    rows[1]['candidate'] = 'Zach Nunn'
    snapshot = {**parse(rows), 'year': 2026, 'election_date': '2026-11-03', 'expected_contests': 435,
                'sha256': 'a'*64, 'published_at': '2026-11-16T15:00:00Z', 'retrieved_at': '2026-11-17T12:00:00Z',
                'checked_at': '2026-11-17T12:00:00Z', 'next_refresh_at': '2026-11-18T12:00:00Z',
                'stale': False, 'refresh_failed': False, 'ruleset': 'call-the-map-house-v1',
                'source_url': 'https://www.callthemap.com/results/data/2026/races.csv',
                'manifest_url': 'https://www.callthemap.com/results/data/2026/manifest.json'}
    with Session(api_engine) as session, session.begin():
        first = entities.sync_entities(session, snapshot, tmp_path)
        assert first['inserted'] == 2 and first['excluded'] == 1
    with Session(api_engine) as session, session.begin():
        second = entities.sync_entities(session, snapshot, tmp_path)
        assert second['status'] == 'unchanged' and second['run_id'] == first['run_id']
        before = entities.enrich_snapshot(session, snapshot)
        assert before['races'][0]['candidates'][1]['incumbent'] is True
        assert before['races'][0]['candidates'][2]['candidacy_id'] is None
        changed = deepcopy(snapshot)
        changed['sha256'] = 'b'*64
        entities.sync_entities(session, changed, tmp_path)
        assert entities.enrich_snapshot(session, changed)['races'][0]['candidates'][1]['candidacy_id'] == before['races'][0]['candidates'][1]['candidacy_id']
        assert session.scalar(select(func.count()).select_from(Candidacy)) == 2
        assert session.scalar(select(func.count()).select_from(Jurisdiction).where(Jurisdiction.level=='congressional_district')) == 1
        assert session.scalar(select(func.count()).select_from(CanonicalVoteReturn)) == 0
    monkeypatch.setattr(house, 'read_snapshot', lambda: snapshot)
    monkeypatch.setattr(entities, 'read_snapshot', lambda: snapshot)
    response = client.get('/api/v1/house/2026/results')
    assert response.status_code == 200, response.text
    candidate = response.json()['races'][0]['candidates'][1]
    assert candidate['portrait']['url'].startswith('/media/candidates/')
    assert candidate['portrait']['license'] and candidate['portrait']['credit']
    profile = client.get('/api/v1/candidates/'+candidate['candidacy_id'])
    assert profile.status_code == 200, profile.text
    profile = profile.json()
    assert profile['person'] is None and profile['finance']['total_raised'] is None
    assert profile['provisional_house_election']['race']['candidates'][1]['incumbent'] is True
    assert profile['provisional_house_election']['race']['candidates'][1]['portrait'] == candidate['portrait']
