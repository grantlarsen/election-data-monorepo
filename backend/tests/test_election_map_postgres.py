"""Validate the map adapter against migrated canonical result fixtures."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.models.core import Candidacy
from app.services.canonical_results import materialize_medsl_year
from app.api.map_schemas import MapFilters
from test_data003_postgres import _seed, _observe

from app.services import election_map
from test_election_api import api_engine, client, populated
from test_data004_postgres import pg

pytestmark = pytest.mark.integration


def test_county_map_matches_existing_api_and_does_not_add_state_totals(client, populated, monkeypatch):
    monkeypatch.setattr(election_map, "load_boundaries", lambda *args: ({"year":2008}, []))
    reference = client.get('/api/v1/results?year=2008&limit=200').json()
    code = reference["items"][0]["jurisdiction"]["state_code"]
    response = client.get('/api/v1/election-map', params=dict(state_code=code)).json()
    assert response["availability"] == "available"
    assert sum(u["summary"]["total_votes"] or 0 for u in response["units"]) == sum(r["votes"] for r in reference["items"])
    assert response["coverage"]["results_without_geometry"] == 1
    candidates = response["units"][0]["summary"]["candidates"]
    assert {str(c["candidacy_id"]) for c in candidates} == {str(r["candidacy_id"]) for r in reference["items"]}
    assert response["publications"][0]["status"] == "PARTIAL"
    assert not client.get('/api/v1/election-map').json()["units"]  # No FEC authority in this fixture.
    selected = client.get('/api/v1/election-map', params=dict(state_code=code, jurisdiction_id=str(populated['county']))).json()
    assert selected["selected_jurisdiction_id"] == str(populated['county'])
    missing = client.get('/api/v1/election-map', params=dict(state_code=code, jurisdiction_id='00000000-0000-0000-0000-000000000000')).json()
    assert missing["availability"] == "no_matching_published_results" and not missing["units"]


def test_map_parties_use_only_published_observations_without_creating_affiliations(api_engine, monkeypatch):
    with Session(api_engine) as session, session.begin():
        seed = _seed(session)
        for n, (name, votes, kind, party) in enumerate([
            ('ALICE',100,'candidate','DEMOCRATIC'), ('BOB',80,'candidate','REPUBLICAN'),
            ('OTHER',5,'aggregate','GREEN')], 2):
            _observe(session, seed, n, name=name, votes=votes, total=185, kind=kind, party=party)
        # An excluded observation must not change the displayed party of a published candidate.
        _observe(session, seed, 5, name='ALICE', votes=9, total=185, party='REPUBLICAN', mode='PROVISIONAL')
    with Session(api_engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        materialize_medsl_year(session, year=2008, dry_run=False, allow_partial=True)
    monkeypatch.setattr(election_map, 'load_boundaries', lambda *args: (None, []))
    with Session(api_engine) as session, session.begin():
        response = election_map.build_map(session, MapFilters(state_code='NY'))
        candidates = response['units'][0]['summary']['candidates']
        assert {c['label']:c['party_labels'] for c in candidates} == {
            'ALICE':['DEMOCRATIC'], 'BOB':['REPUBLICAN'], 'OTHER':['GREEN']}
        assert response['units'][0]['summary']['total_votes'] == 185
        assert all(candidate.party_id is None for candidate in session.scalars(select(Candidacy)))
