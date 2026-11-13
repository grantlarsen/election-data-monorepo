"""Offline tests of Dataverse 6.10+ guestbook/signed-URL acquisition."""
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from ingestion import source

FIXTURE = Path(__file__).parent / "fixtures" / "medsl_small.csv"


def _metadata():
    return {"status": "OK", "data": {
        "id": 3239428, "guestbookId": 458,
        "publicationDate": "2018-10-11",
        "latestVersion": {
            "versionState": "RELEASED", "versionNumber": 20, "versionMinorNumber": 0,
            "releaseTime": "2026-02-25T19:00:32Z", "files": [{"dataFile": {
                "id": 13573089, "originalFileName": "countypres_2000-2024.csv",
                "originalFileSize": FIXTURE.stat().st_size,
            }}],
        },
    }}


def _guestbook():
    return {"status": "OK", "data": {
        "nameRequired": True,
        "emailRequired": True,
        "institutionRequired": False,
        "positionRequired": False,
        "customQuestions": [{"id": 1234, "question": "Purpose of research?", "required": True}],
    }}


def _config(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "guestbook_response.json"
    path.write_text(json.dumps({"guestbookResponse": {
        "name": "Example Researcher", "email": "user@example.invalid",
        "answers": [{"id": 1234, "value": "Academic analysis"}],
    }}))
    return path


def test_guestbook_download_and_subsequent_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAVERSE_GUESTBOOK_RESPONSE_FILE", raising=False)
    _config(tmp_path)
    calls = []
    signed = "https://dataverse.harvard.edu/api/access/datafile/13573089?token=SECRET"

    def fake_request(url, *, destination=None, method="GET", json_body=None):
        calls.append((url, method, json_body))
        if url.endswith("/api/guestbooks/458"):
            return json.dumps(_guestbook()).encode()
        if "/api/datasets/:persistentId/" in url:
            return json.dumps(_metadata()).encode()
        if method == "POST":
            assert url.endswith("13573089?format=original")
            assert json_body["guestbookResponse"]["name"] == "Example Researcher"
            return json.dumps({"status": "OK", "data": {"signedUrl": signed}}).encode()
        assert url == signed
        assert destination is not None
        destination.write_bytes(FIXTURE.read_bytes())
        return None

    monkeypatch.setattr(source, "_request", fake_request)
    first = source.acquire(source.DataverseMEDSL(), tmp_path)
    second = source.acquire(source.DataverseMEDSL(), tmp_path)
    assert first.path == second.path
    assert first.sha256 == second.sha256
    assert len([c for c in calls if c[1] == "POST"]) == 1
    assert len([c for c in calls if c[0].endswith("/api/guestbooks/458")]) == 1
    manifest = (first.path.parent / "file_13573089.json").read_text()
    assert "SECRET" not in manifest
    assert "user@example.invalid" not in manifest
    assert "guestbook_id" in manifest


def test_missing_response_file_errors_with_instructions(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAVERSE_GUESTBOOK_RESPONSE_FILE", raising=False)

    def fake_request(url, *, destination=None, method="GET", json_body=None):
        if "/api/datasets/:persistentId/" in url:
            return json.dumps(_metadata()).encode()
        if url.endswith("/api/guestbooks/458"):
            return json.dumps(_guestbook()).encode()
        raise AssertionError("Should not attempt download without a guestbook response")

    monkeypatch.setattr(source, "_request", fake_request)
    with pytest.raises(source.AcquisitionError, match="guestbook 458") as exc:
        source.acquire(source.DataverseMEDSL(), tmp_path)
    assert "Purpose of research" in str(exc.value)
    assert "guestbook_response.json" in str(exc.value)


def test_missing_required_question_is_rejected_locally(tmp_path, monkeypatch):
    monkeypatch.delenv("DATAVERSE_GUESTBOOK_RESPONSE_FILE", raising=False)
    path = _config(tmp_path)
    path.write_text(json.dumps({"guestbookResponse": {
        "name": "Example Researcher", "email": "user@example.invalid", "answers": []
    }}))

    def fake_request(url, *, destination=None, method="GET", json_body=None):
        if "/api/datasets/:persistentId/" in url:
            return json.dumps(_metadata()).encode()
        if url.endswith("/api/guestbooks/458"):
            return json.dumps(_guestbook()).encode()
        raise AssertionError("Should not post invalid response")

    monkeypatch.setattr(source, "_request", fake_request)
    with pytest.raises(source.AcquisitionError, match="question ID 1234"):
        source.acquire(source.DataverseMEDSL(), tmp_path)


def test_upstream_http_error_body_is_exposed_without_query_token(monkeypatch):
    def fake_urlopen(req, timeout):
        raise HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(json.dumps({
            "status": "ERROR", "message": "A guestbook response is required for guestbookID 458."
        }).encode()))
    monkeypatch.setattr(source, "urlopen", fake_urlopen)
    with pytest.raises(source.AcquisitionError) as exc:
        source._request("https://dataverse.harvard.edu/api/access/datafile/13573089?token=SENSITIVE")
    message = str(exc.value)
    assert "guestbookID 458" in message
    assert "SENSITIVE" not in message
