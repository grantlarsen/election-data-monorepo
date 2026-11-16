from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.main import app
from app.api.elections import get_read_session
from app.services import election_map
from test_house_returns_postgres import house_engine, load_census, load_fixture, materialize
from test_data004_postgres import pg

pytestmark = pytest.mark.integration


def test_district_map_fusion_parties_missing_contest_links_and_selection(house_engine, monkeypatch):
    load_census(house_engine)
    load_fixture(house_engine)
    materialize(house_engine, dry_run=False, allow_partial=True)
    def boundaries(state, year, level):
        assert year == 2024 and level == 'congressional_district'
        return ({'year':2024}, [dict(type='Feature',id=geoid,geometry=dict(type='Polygon',coordinates=[]),
            properties=dict(geoid=geoid,state_code=st,name=geoid))
            for geoid,st in [('3601','NY'),('1220','FL'),('1198','DC'),('2302','ME')]
            if not state or state==st])
    monkeypatch.setattr(election_map,'load_boundaries',boundaries)
    def read():
        with Session(house_engine) as session, session.begin():yield session
    app.dependency_overrides[get_read_session]=read
    try:
        with TestClient(app) as client:
            params=dict(year=2024,office='U.S. House')
            response=client.get('/api/v1/election-map',params=params)
            assert response.status_code==200,response.text
            data=response.json()
            assert data['coverage']==dict(boundary_units=4,units_with_results=3,missing_results=1,results_without_geometry=0)
            assert sum(u['summary']['total_votes'] or 0 for u in data['units'])==340
            ny=next(u for u in data['units'] if u['id']=='3601')
            alice=next(c for c in ny['summary']['candidates'] if c['label']=='ALICE')
            assert alice['party_labels']==['DEMOCRATIC','WORKING FAMILIES'] and alice['votes']==100
            missing=next(u for u in data['units'] if u['id']=='1220')
            assert missing['contest_id'] and missing['jurisdiction_id']
            assert missing['summary']['total_votes'] is None
            assert missing['summary']['leader'] is None
            selected=client.get('/api/v1/election-map',params=dict(params,state_code='FL',jurisdiction_id=missing['jurisdiction_id']))
            assert selected.json()['availability']=='no_matching_published_results'
            assert selected.json()['units'][0]['contest_id']==missing['contest_id']
    finally:app.dependency_overrides.clear()
