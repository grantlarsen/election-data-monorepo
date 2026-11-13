import json
from pathlib import Path

import pytest

from ingestion import source

FIXTURE = Path(__file__).parent / "fixtures" / "medsl_small.csv"


def test_metadata_cache_refresh_and_integrity(tmp_path, monkeypatch):
    metadata = {"status":"OK", "data": {
        "id": 3239428, "publicationDate":"2018-10-11",
        "latestVersion": {"versionState":"RELEASED", "versionNumber":20, "versionMinorNumber":0,
            "releaseTime":"2026-02-25T19:00:32Z", "UNF":"UNF:example", "license":{"name":"CC0"},
            "files":[{"dataFile":{"id":13573089, "originalFileName":"countypres_2000-2024.csv",
                                  "originalFileSize":FIXTURE.stat().st_size}}]}}}
    calls = {"download": 0}

    def fake_request(url: str, *, destination=None):
        if destination is None:
            return json.dumps(metadata).encode()
        calls["download"] += 1
        destination.write_bytes(FIXTURE.read_bytes())
        return None

    monkeypatch.setattr(source, "_request", fake_request)
    first = source.acquire(source.DataverseMEDSL(), tmp_path)
    second = source.acquire(source.DataverseMEDSL(), tmp_path)
    assert first.sha256 == second.sha256
    assert calls["download"] == 1
    assert first.info.version == "20.0"
    assert first.info.file_id == 13573089
    first.path.write_bytes(b"corrupt")
    with pytest.raises(source.AcquisitionError, match="SHA-256"):
        source.acquire(source.DataverseMEDSL(), tmp_path)
    recovered = source.acquire(source.DataverseMEDSL(), tmp_path, refresh=True)
    assert recovered.sha256 == first.sha256
    assert calls["download"] == 2
