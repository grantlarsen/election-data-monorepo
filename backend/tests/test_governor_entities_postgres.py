from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import governor
from app.models.core import Candidacy, Jurisdiction
from app.models.election import CanonicalVoteReturn
from app.models.ingestion import IngestionRun
from app.services import governor_entities as entities
from test_election_api import api_engine, client
from test_candidate_results import candidate_tables
from test_data004_postgres import pg, migration
from test_current_governor import rows, payload
from ingestion.current_governor import parse_results


def test_profiles_context_replay_and_api_without_person_matching(api_engine, client, rows, tmp_path, monkeypatch):
    for row in rows:
        row.update(race_id="GOV-NV", state="NV", status="called", outcome="won" if row["party"] == "D" else "")
    rows[0].update(candidate="Joe Lombardo", votes="35")
    rows[1].update(candidate="Aaron Ford", votes="60")
    snapshot = {**parse_results(payload(rows), 3), "year": 2026, "election_date": "2026-11-03", "expected_contests": 36,
        "sha256": "a"*64, "published_at": "2026-11-16T15:00:00Z", "retrieved_at": "2026-11-17T12:00:00Z",
        "checked_at": "2026-11-17T12:00:00Z", "next_refresh_at": "2026-11-18T12:00:00Z",
        "stale": False, "refresh_failed": False, "ruleset": "call-the-map-governor-v1",
        "source_url": "https://www.callthemap.com/results/data/2026/races.csv",
        "manifest_url": "https://www.callthemap.com/results/data/2026/manifest.json"}
    with Session(api_engine) as session, session.begin():
        session.add(Jurisdiction(name="Nevada", level="state", state_code="NV"))
        first = entities.sync_entities(session, snapshot, tmp_path)
        assert first["inserted"] == 2 and first["excluded"] == 1
    with Session(api_engine) as session, session.begin():
        second = entities.sync_entities(session, snapshot, tmp_path)
        assert second["status"] == "unchanged" and second["run_id"] == first["run_id"]
        before = entities.enrich_snapshot(session, snapshot)
        race = before["races"][0]
        incumbent = next(c for c in race["candidates"] if c["name"] == "Joe Lombardo")
        assert incumbent["incumbent"] is True and incumbent["incumbent_evidence"]["as_of"] == "2026-11-03"
        assert race["flipped"] is True and race["previous_election"]["year"] == 2022
        assert race["candidates"][2]["candidacy_id"] is None
        changed = deepcopy(snapshot); changed["sha256"] = "b"*64
        entities.sync_entities(session, changed, tmp_path)
        after = entities.enrich_snapshot(session, changed)
        assert after["races"][0]["candidates"][1]["candidacy_id"] == incumbent["candidacy_id"]
        assert session.scalar(select(func.count()).select_from(Candidacy)) == 2
        assert session.scalar(select(func.count()).select_from(CanonicalVoteReturn)) == 0
        assert all(c.person_id is None for c in session.scalars(select(Candidacy)))
        run = session.get(IngestionRun, first["run_id"])
        assert run.options_json["context_catalog_sha256"] and run.options_json["contest_scopes"][0]["flipped"]
    monkeypatch.setattr(governor, "read_snapshot", lambda: snapshot)
    monkeypatch.setattr(entities, "read_snapshot", lambda: snapshot)
    response = client.get("/api/v1/governor/2026/results")
    assert response.status_code == 200, response.text
    candidate = next(c for c in response.json()["races"][0]["candidates"] if c["name"] == "Joe Lombardo")
    assert candidate["portrait"]["url"].startswith("/media/candidates/")
    assert candidate["portrait"]["license"] and candidate["portrait"]["credit"]
    assert response.json()["races"][0]["candidates"][2]["portrait"] is None
    profile = client.get("/api/v1/candidates/" + candidate["candidacy_id"])
    assert profile.status_code == 200, profile.text
    profile = profile.json()
    assert profile["person"] is None and profile["finance"]["total_raised"] is None
    assert profile["provisional_governor_election"]["race"]["flipped"] is True
    assert profile["provisional_governor_election"]["race"]["candidates"][1]["incumbent"] is True
    assert profile["provisional_governor_election"]["race"]["candidates"][1]["portrait"] == candidate["portrait"]
