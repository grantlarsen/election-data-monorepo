"""Map metrics and joins without network access or publication writes."""
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.elections import get_read_session
from app.main import app
from app.api.map_schemas import MapFilters
from app.services import election_map as maps
from app.services.canonical_results import MaterializationError


def candidate(label, votes, kind="candidate"):
    return dict(label=label, votes=votes, kind=kind)


def test_shares_and_margin_include_other_votes_in_denominator():
    result = maps.summarize([candidate("Alice", 60), candidate("Bob", 30), candidate("OTHER", 10, "aggregate")])
    assert result["total_votes"] == 100
    assert result["leader"] == "Alice"
    assert result["margin_votes"] == 30 and result["margin_pp"] == 30
    assert [c["share"] for c in result["candidates"]] == [60, 30, 10]
    # Multiple anonymous buckets might conceal the same unknown runner-up.
    assert maps.summarize([candidate("A",50),candidate("B",20),
        candidate("OTHER",12,"aggregate"),candidate("WRITEIN",12,"write_in")])["status"] == "indeterminate"
    assert maps.summarize([candidate("A",10),candidate("B",0),candidate("OTHER",0,"aggregate")])["margin_pp"] == 100


@pytest.mark.parametrize("rows,status", [([], "no_results"),
    ([candidate("A", 0), candidate("B", 0)], "zero_total"),
    ([candidate("A", 5), candidate("B", 5)], "tie"),
    ([candidate("A", 5)], "indeterminate"),
    ([candidate("A", 50), candidate("B", 20), candidate("OTHER", 30, "aggregate")], "indeterminate")])
def test_missing_zero_tie_and_ambiguous_aggregate_are_distinct(rows, status):
    result = maps.summarize(rows)
    assert result["status"] == status
    if status in {"no_results", "zero_total", "indeterminate"}:
        assert result["margin_pp"] is None and result["leader"] is None


def test_negative_votes_fail_closed():
    with pytest.raises(MaterializationError):
        maps.summarize([candidate("A", -1)])


def feature(geoid="01001", name="Autauga"):
    return dict(type="Feature", id=geoid,
        properties=dict(geoid=geoid, name=name, state_code="AL"),
        geometry=dict(type="Polygon", coordinates=[[[-87,32],[-86,32],[-86,33],[-87,32]]]))


def test_boundary_integrity_and_missing_package(tmp_path, monkeypatch):
    monkeypatch.setenv("BOUNDARY_DATA_DIR", str(tmp_path))
    assert maps.load_boundaries(None) == (None, [])
    raw = json.dumps(dict(type="FeatureCollection", features=[feature("01")])).encode()
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / "objects").mkdir()
    path = tmp_path / "objects" / (digest + ".json")
    path.write_bytes(raw)
    manifest = dict(version="tiger2008-display-v1", year=2008,
                    outputs={"state": dict(object=digest, sha256=digest, count=1, repaired=0)})
    (tmp_path / "2008.json").write_text(json.dumps(manifest))
    assert maps.load_boundaries(None)[1] == [feature("01")]
    path.write_text("corrupt")
    with pytest.raises(MaterializationError):
        maps.load_boundaries(None)


def county_rows():
    jurisdiction = dict(id=uuid4(), name="Source county label", level="county", state_code="AL")
    publication = dict(batch_id=uuid4())
    contest_id, reference_id = uuid4(), uuid4()
    return [dict(jurisdiction=jurisdiction, publication=publication, contest_id=contest_id,
        geographic_reference_id=reference_id, label=label, votes=votes, candidate_kind=kind,
        candidacy_id=uuid4() if kind == "candidate" else None,
        observation_ids=[uuid4()], correction_ids=[uuid4()])
        for label, votes, kind in [("Alice",60,"candidate"),("Bob",30,"candidate"),("OTHER",10,"aggregate")]]


def test_exact_reference_join_preserves_unmatched_results_and_empty_boundaries(monkeypatch):
    rows = county_rows()
    monkeypatch.setattr(maps, "_all_rows", lambda *args: rows)
    monkeypatch.setattr(maps, "load_boundaries", lambda *args: ({"year":2008}, [feature(), feature("01003", "Baldwin")]))
    reference = SimpleNamespace(kind="county", jurisdiction_id=rows[0]["jurisdiction"]["id"],
                                state_fips="01", geoid="01099", vintage_start=2002, vintage_end=2011)
    session = SimpleNamespace(get=lambda *args: reference)
    response = maps.build_map(session, MapFilters(state_code="AL"))
    assert response["coverage"] == dict(boundary_units=2, units_with_results=1, missing_results=2, results_without_geometry=1)
    unmatched = next(u for u in response["units"] if u["id"] == "01099")
    assert not unmatched["has_geometry"] and unmatched["summary"]["total_votes"] == 100
    assert unmatched["summary"]["candidates"][0]["correction_ids"] == rows[0]["correction_ids"]
    reference.geoid = "01001"
    response = maps.build_map(session, MapFilters(state_code="AL"))
    assert response["coverage"]["results_without_geometry"] == 0
    assert next(u for u in response["units"] if u["id"] == "01001")["name"] == "Source county label"
    reference.vintage_end = 2007
    with pytest.raises(MaterializationError):
        maps.build_map(session, MapFilters(state_code="AL"))


def test_overlapping_scopes_fail_instead_of_double_counting(monkeypatch):
    rows = county_rows()
    rows[-1]["contest_id"] = uuid4()
    monkeypatch.setattr(maps, "_all_rows", lambda *args: rows)
    monkeypatch.setattr(maps, "load_boundaries", lambda *args: (None, []))
    reference = SimpleNamespace(kind="county", jurisdiction_id=rows[0]["jurisdiction"]["id"],
                                state_fips="01", geoid="01001", vintage_start=2002, vintage_end=2011)
    with pytest.raises(MaterializationError):
        maps.build_map(SimpleNamespace(get=lambda *args: reference), MapFilters(state_code="AL"))


def test_all_pages_use_the_same_session(monkeypatch):
    calls = []
    session = object()
    def query(s, filters):
        assert s is session
        calls.append(filters.offset)
        return dict(items=[filters.offset], has_more=filters.offset == 0)
    monkeypatch.setattr(maps.election_queries, "list_results", query)
    assert maps._all_rows(session, MapFilters(state_code='AL'), 'county') == [0, 200]
    assert calls == [0, 200]


def test_map_http_validation_empty_unsupported_and_sanitized_errors(monkeypatch):
    app.dependency_overrides[get_read_session] = lambda: None
    monkeypatch.setattr(maps, "_all_rows", lambda *args: [])
    monkeypatch.setattr(maps, "load_boundaries", lambda *args: (None, []))
    try:
        with TestClient(app) as client:
            for params in [{"year":0}, {"state_code":"ZZ"}, {"jurisdiction_id":"bad"}, {"unknown":1}]:
                assert client.get('/api/v1/election-map', params=params).status_code == 422
            assert client.get('/api/v1/election-map?year=2024').json()["availability"] == "boundaries_unavailable"
            assert client.get('/api/v1/election-map?office=Governor').json()['availability'] == 'unsupported_selection'
            assert client.get('/api/v1/election-map').json()["availability"] == "boundaries_unavailable"
            monkeypatch.setattr(maps, "load_boundaries", lambda *args: ({}, []))
            assert client.get('/api/v1/election-map').json()["availability"] == "no_matching_published_results"
            def fail(*args):
                raise MaterializationError("password=private")
            monkeypatch.setattr(maps, "_all_rows", fail)
            response = client.get('/api/v1/election-map')
            assert response.status_code == 503 and 'private' not in response.text
    finally:
        app.dependency_overrides.clear()


def test_state_paint_requires_the_published_canonical_jurisdiction_reference(monkeypatch):
    jurisdiction = dict(id=uuid4(), name='Alabama', level='state', state_code='AL')
    publication, contest = dict(batch_id=uuid4()), uuid4()
    rows = [dict(jurisdiction=jurisdiction, publication=publication, contest_id=contest,
                 candidate_bucket=label, votes=votes, bucket_kind='source_candidate')
            for label, votes in [('Alice',60),('Bob',40)]]
    monkeypatch.setattr(maps, '_all_rows', lambda *args: rows)
    monkeypatch.setattr(maps, 'load_boundaries', lambda *args: ({'year':2008}, [feature('01', 'Alabama')]))
    session = SimpleNamespace(scalars=lambda *args: [])
    missing = maps.build_map(session, MapFilters())
    assert missing['coverage']['results_without_geometry'] == 1
    assert missing['features']['features'][0]['properties']['jurisdiction_id'] is None
    unmatched = next(u for u in missing['units'] if u['geometry_match'] == 'missing_reference')
    assert unmatched['jurisdiction_id'] == jurisdiction['id'] and unmatched['geoid'] is None
    assert unmatched['summary']['total_votes'] == 100
    session.scalars = lambda *args: ['01']
    matched = maps.build_map(session, MapFilters())
    assert matched['features']['features'][0]['properties']['jurisdiction_id'] == jurisdiction['id']
    assert matched['units'][0]['geometry_match'] == 'matched'
    assert matched['drill_down_level'] == 'county'
    alias = maps.build_map(session, MapFilters(office='President of the United States'))
    assert alias['availability'] == 'available' and alias['drill_down_level'] == 'county'
    session.scalars = lambda *args: ['02']
    with pytest.raises(MaterializationError):
        maps.build_map(session, MapFilters())


def test_federal_district_mapping_uses_selected_year_grain_and_exact_reference(monkeypatch):
    rows = county_rows()
    rows[0]['jurisdiction']['level'] = 'congressional_district'
    reference = SimpleNamespace(kind='congressional_district', jurisdiction_id=rows[0]['jurisdiction']['id'],
                                state_fips='01', geoid='0101', vintage_start=2022, vintage_end=2024)
    calls = []
    def boundaries(*args):
        calls.append(args)
        return {'year':2024}, [feature('0101', 'District 1')]
    monkeypatch.setattr(maps, '_all_rows', lambda *args: rows)
    monkeypatch.setattr(maps, 'load_boundaries', boundaries)
    response = maps.build_map(SimpleNamespace(get=lambda *args: reference), MapFilters(year=2024, office='U.S. House'))
    assert calls == [(None, 2024, 'congressional_district')]
    assert response['reporting_level'] == 'congressional_district' and response['year'] == 2024
    assert response['units'][0]['jurisdiction_id'] == rows[0]['jurisdiction']['id']
    assert response['units'][0]['summary']['total_votes'] == 100
    reference.geoid = '0201'
    with pytest.raises(MaterializationError):
        maps.build_map(SimpleNamespace(get=lambda *args: reference), MapFilters(year=2024, office='U.S. House'))


def test_row_selection_does_not_reset_federal_office_year_or_stage(monkeypatch):
    observed = []
    def query(session, filters):
        observed.append(filters)
        return dict(items=[], has_more=False)
    monkeypatch.setattr(maps.election_queries, 'list_results', query)
    maps._all_rows(None, MapFilters(year=2024, office='U.S. House', stage='primary', state_code='NY'), 'congressional_district')
    assert observed[0].year == 2024 and observed[0].office == 'U.S. House'
    assert observed[0].stage == 'primary' and observed[0].reporting_level == 'congressional_district'


def test_other_vintages_and_grains_do_not_reuse_2008_counties(tmp_path, monkeypatch):
    monkeypatch.setenv('BOUNDARY_DATA_DIR', str(tmp_path))
    (tmp_path / '2008.json').write_text(json.dumps(dict(version='tiger2008-display-v1', year=2008, outputs={})))
    assert maps.load_boundaries(None, 2024, 'congressional_district') == (None, [])
    assert maps.load_boundaries(None, 2008, 'congressional_district') == (None, [])
