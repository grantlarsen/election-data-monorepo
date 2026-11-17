"""2026 election geography pins, preparation, replay and read-only API contracts."""
from copy import deepcopy
from hashlib import sha256
import io
import json
import os
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest
import shapefile

from app.main import app
from app.services.election_map import load_boundaries
from ingestion import boundaries
from ingestion.current_house import BOUNDARY_RACES
from ingestion.medsl import STATE_FIPS


def test_2026_scope_and_corrected_source_pins():
    config = boundaries.configuration(2026, "house")
    assert config["reviewed_at"] == "2026-11-17"
    assert len(config["sources"]) == 51
    assert {s["include_states"][0] for s in config["sources"]} == set(STATE_FIPS)
    assert len({s["file_id"] for s in config["sources"]}) == 51
    assert all(s["source_year"] == 2026 and len(s["sha256"]) == 64 for s in config["sources"])
    mo = next(s for s in config["sources"] if s["include_states"] == ["MO"])
    assert mo["sha256"] == "ad6d2f736622e0f3a7bc578737c424a9ec696419a49bde21877acc065fa11d1d"
    assert any("120cd" in url for url in config["source_notes"])
    with pytest.raises(ValueError, match="Unsupported"):
        boundaries.configuration(2026, "president")


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    archive_path = tmp_path / "districts.zip"
    streams = [io.BytesIO() for _ in range(3)]
    writer = shapefile.Writer(shp=streams[0], shx=streams[1], dbf=streams[2])
    for field, length in [("STATEFP", 2), ("GEOID", 4), ("NAMELSAD", 50)]:
        writer.field(field, "C", length)
    for geoid in [*BOUNDARY_RACES, "1198"]:
        writer.poly([[[-101, 32], [-101, 33], [-100, 33], [-101, 32]]])
        writer.record(geoid[:2], geoid, "Congressional District " + geoid[2:])
    writer.close()
    with ZipFile(archive_path, "w") as archive:
        for stream, suffix in zip(streams, [".shp", ".shx", ".dbf"]):
            archive.writestr("districts" + suffix, stream.getvalue())
        archive.writestr("districts.prj", 'GEOGCS["North_American_1983",UNIT["Degree",1]]')
    config = deepcopy(boundaries.configuration(2026, "house"))
    config["sources"] = [{**config["sources"][0], "filename": "districts.zip",
                          "sha256": sha256(archive_path.read_bytes()).hexdigest()}]
    config["sources"][0].pop("include_states")
    monkeypatch.setattr(boundaries, "configuration", lambda year, office: config)
    monkeypatch.setattr(boundaries, "acquire", lambda adapter, root: SimpleNamespace(path=archive_path,
        sha256=sha256(archive_path.read_bytes()).hexdigest(),
        retrieved_at=SimpleNamespace(isoformat=lambda: "2026-11-17T12:00:00Z")))
    def execute(query, params):
        row = dict(original_valid=True, valid=True, empty=False, geometry=json.loads(params["raw"]))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: row))
    connection = SimpleNamespace(execute=execute)
    output = tmp_path / "display"
    result = boundaries.prepare(connection, data_dir=tmp_path, output=output, year=2026)
    monkeypatch.setenv("BOUNDARY_DATA_DIR", str(output))
    return connection, output, result


def test_preparation_exact_districts_provenance_and_idempotency(prepared, tmp_path):
    connection, output, result = prepared
    assert result["districts"] == 436 and result["repaired"] == 0
    metadata, features = load_boundaries(None, 2026, "congressional_district")
    assert {f["id"] for f in features} == set(BOUNDARY_RACES) | {"1198"}
    assert metadata["reviewed_at"] == "2026-11-17" and metadata["source_notes"]
    path = output / "2026.json"
    before = path.read_bytes()
    assert boundaries.prepare(connection, data_dir=tmp_path, output=output, year=2026)["status"] == "unchanged"
    assert path.read_bytes() == before


def test_house_boundaries_api_joins_exact_source_ids_and_fails_closed(prepared):
    _, output, _ = prepared
    with TestClient(app) as client:
        response = client.get("/api/v1/house/2026/boundaries")
        assert response.status_code == 200
        data = response.json()
        assert len(data["features"]) == 436 and data["source"]["year"] == 2026
        ids = {f["id"]: f["properties"]["race_id"] for f in data["features"]}
        assert ids["0601"] == "CA-01" and ids["0200"] == "AK-AL" and ids["1198"] is None
        manifest = json.loads((output / "2026.json").read_text())
        target = output / "objects" / (manifest["outputs"]["congressional_district"]["object"] + ".json")
        target.write_bytes(b"corrupt")
        response = client.get("/api/v1/house/2026/boundaries")
        assert response.status_code == 503 and str(output) not in response.text


def test_missing_house_boundaries_explicit_503(tmp_path, monkeypatch):
    monkeypatch.setenv("BOUNDARY_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/v1/house/2026/boundaries").status_code == 503


@pytest.mark.skipif(not os.getenv("CURRENT_HOUSE_BOUNDARY_DIR"), reason="Requires explicitly retained Census package")
def test_retained_census_120th_district_package(monkeypatch):
    monkeypatch.setenv("BOUNDARY_DATA_DIR", os.environ["CURRENT_HOUSE_BOUNDARY_DIR"])
    metadata, features = load_boundaries(None, 2026, "congressional_district")
    assert len(features) == 436 and {f["id"] for f in features} == set(BOUNDARY_RACES) | {"1198"}
    assert len(metadata["sources"]) == 51 and metadata["repaired_features"] == 0
    pins = {s["url"]: s["sha256"] for s in boundaries.configuration(2026, "house")["sources"]}
    assert all(pins[s["url"]] == s["sha256"] for s in metadata["sources"])
