"""Entity replay, provenance, anonymous buckets, profiles and read-only API on PostgreSQL."""
from copy import deepcopy
from datetime import date
from hashlib import sha256

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import senate
from app.models.core import Candidacy, Contest, DataSource, Jurisdiction, Person
from app.models.election import CanonicalVoteReturn, Office
from app.models.ingestion import IngestionRun, SourceRelease
from app.models.senate_returns import SenateSeat
from app.services import senate_entities as entities
from ingestion.current_senate import parse_results
from test_current_senate import rows, payload
from test_election_api import api_engine, client
from test_candidate_results import candidate_tables
from test_data004_postgres import pg, migration

pytestmark = pytest.mark.integration


@pytest.fixture
def snapshot(rows):
    rows[0]["candidate"] = "Ashley Moody"
    raw = payload(rows)
    result = parse_results(raw, len(rows))
    return {**result, "year": 2026, "election_date": "2026-11-03", "expected_contests": 35,
        "sha256": sha256(raw).hexdigest(), "published_at": "2026-11-16T15:00:00Z",
        "retrieved_at": "2026-11-17T12:00:00Z", "checked_at": "2026-11-17T12:00:00Z",
        "next_refresh_at": "2026-11-18T12:00:00Z", "stale": False, "refresh_failed": False,
        "ruleset": "call-the-map-senate-v1", "source_url": "https://www.callthemap.com/results/data/2026/races.csv",
        "manifest_url": "https://www.callthemap.com/results/data/2026/manifest.json"}


def seed(session):
    state = Jurisdiction(name="Florida", level="state", state_code="FL")
    session.add(state)
    session.flush()
    office = Office(name="U.S. Senate", creation_key="us:senate:FL:class:3", office_kind="legislative", jurisdiction_id=state.id)
    session.add(office)
    session.flush()
    session.add(SenateSeat(office_id=office.id, state_code="FL", seat_class=3,
                          evidence_url="https://www.senate.gov/senators/Class_III.htm"))


def test_registration_replay_profile_and_no_person_matching(api_engine, client, snapshot, tmp_path, monkeypatch):
    with Session(api_engine) as session, session.begin():
        seed(session)
        session.add(Person(full_name="Ashley Moody", creation_key="different-source-person"))
    with Session(api_engine) as session, session.begin():
        first = entities.sync_entities(session, snapshot, tmp_path)
    assert first["inserted"] == 2 and first["excluded_buckets"] == 1
    with Session(api_engine) as session, session.begin():
        second = entities.sync_entities(session, snapshot, tmp_path)
        assert second["status"] == "unchanged" and second["run_id"] == first["run_id"]
        data = entities.enrich_snapshot(session, snapshot)
        race = data["races"][0]
        assert race["margin_votes"] == 25 and race["margin_pct"] == 25
        assert race["candidates"][0]["incumbent"] is True
        assert race["candidates"][0]["incumbent_evidence"]["as_of"] == "2026-11-03"
        assert race["candidates"][2]["candidacy_id"] is None and race["candidates"][2]["kind"] == "aggregate"
        assert session.scalar(select(func.count()).select_from(Candidacy)) == 2
        assert all(c.person_id is None for c in session.scalars(select(Candidacy)))
        assert session.scalar(select(func.count()).select_from(CanonicalVoteReturn)) == 0
        audit = session.get(IngestionRun, first["run_id"])
        assert audit.records_read == 3 and len(audit.options_json["source_rows"]) == 2
        assert audit.options_json["excluded_anonymous_buckets"] == 1
        event = session.get(Contest, race["contest_id"])
        assert event.office_id is not None
    monkeypatch.setattr(senate, "read_snapshot", lambda: snapshot)
    monkeypatch.setattr(entities, "read_snapshot", lambda: snapshot)
    response = client.get('/api/v1/senate/2026/results')
    assert response.status_code == 200, response.text
    candidate = response.json()["races"][0]["candidates"][0]
    assert candidate["portrait"]["url"].startswith('/media/candidates/')
    assert candidate["portrait"]["license"] and candidate["portrait"]["credit"]
    profile = client.get('/api/v1/candidates/' + candidate["candidacy_id"])
    assert profile.status_code == 200, profile.text
    profile = profile.json()
    assert profile["person"] is None and profile["identity_status"] == "unresolved"
    assert profile["finance"]["cycle"] == 2026 and profile["finance"]["total_raised"] is None
    assert profile["finance"]["total_spent"] is None
    assert profile["provisional_election"]["race"]["id"] == "SEN-FL"
    assert profile["provisional_election"]["race"]["candidates"][0]["portrait"] == candidate["portrait"]
    assert profile["results"]["total"] == 0


def test_new_count_release_keeps_profile_ids_and_audits_source_rows(api_engine, snapshot, tmp_path):
    with Session(api_engine) as session, session.begin():
        seed(session)
        entities.sync_entities(session, snapshot, tmp_path)
        before = entities.enrich_snapshot(session, snapshot)
    changed = deepcopy(snapshot)
    changed["sha256"] = "b" * 64
    changed["races"][0]["candidates"][0].update(votes=59, share_pct=59)
    changed["races"][0]["candidates"][1].update(votes=36, share_pct=36)
    with Session(api_engine) as session, session.begin():
        result = entities.sync_entities(session, changed, tmp_path)
        after = entities.enrich_snapshot(session, changed)
        assert result["inserted"] == 0 and result["unchanged"] == 2
        assert before["races"][0]["candidates"][0]["candidacy_id"] == after["races"][0]["candidates"][0]["candidacy_id"]
        assert after["races"][0]["margin_votes"] == 23
        assert session.scalar(select(func.count()).select_from(SourceRelease)) == 2
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 2
        assert session.scalar(select(func.count()).select_from(CanonicalVoteReturn)) == 0


def test_missing_seat_prerequisite_rolls_back_all_entities(api_engine, snapshot, tmp_path):
    with pytest.raises(ValueError, match="canonical state jurisdictions"), Session(api_engine) as session, session.begin():
        entities.sync_entities(session, snapshot, tmp_path)
    with Session(api_engine) as session:
        assert session.scalar(select(func.count()).select_from(DataSource)) == 0
        assert session.scalar(select(func.count()).select_from(Candidacy)) == 0
