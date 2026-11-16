"""Validate the map adapter against migrated canonical result fixtures."""
import pytest

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
