"""Governor source scope, cache recovery, read-only API, replay and scheduler."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
import polars as pl
import pytest

from app.main import app
from app.services import governor_results as cache
from ingestion import current_governor as source

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline_profiles(monkeypatch):
    from app.api.elections import get_read_session
    from app.api import governor
    monkeypatch.setitem(app.dependency_overrides, get_read_session, lambda: None)
    monkeypatch.setattr(governor, "enrich_snapshot", lambda _session, snapshot: snapshot)


@pytest.fixture
def rows():
    def row(name, party, votes):
        return dict(race_id="GOV-FL", state="FL", office="Governor", title="Florida Governor",
            status="counting", outcome="leads" if party == "R" else "", candidate=name,
            party=party, votes=str(votes), share_pct="", total_votes="100", seats="1",
            called_utc="", count_updated_utc="2026-11-16T12:00:00Z",
            source="civicAPI", source_url="https://civicapi.org/race/example",
            source_read_utc="2026-11-16T13:00:00Z", page_url="https://www.callthemap.com/results/governor/fl")
    return [row("Candidate R", "R", 60), row("Candidate D", "D", 35), row("Write-in", "O", 5)]


def payload(rows):
    return pl.DataFrame(rows).write_csv().encode()


def upstream(monkeypatch, rows, *, bad_checksum=False):
    raw = payload(rows)
    manifest = json.dumps(dict(schema_version="ctm-results-open-data-v1", generated_utc=NOW.isoformat(),
        license={"name": "CC BY 4.0"}, files=[dict(path="races.csv", table="races", format="csv",
            rows=len(rows), bytes=len(raw), sha256="a" * 64 if bad_checksum else sha256(raw).hexdigest())])).encode()
    calls = []
    def download(url):
        calls.append(url)
        return manifest if url == source.MANIFEST_URL else raw
    monkeypatch.setattr(source, "download", download)
    return raw, calls


def test_scope_and_exclusions(rows):
    assert len(source.EXPECTED_CONTESTS) == 36
    assert not ({"VA", "NJ", "GU", "MP", "VI", "DC"} & source.EXPECTED_STATES)
    other = {**rows[0], "office": "Senate", "race_id": "SEN-FL"}
    data = source.parse_results(payload(rows + [other]), 4)
    assert (data["accepted_rows"], data["excluded_rows"], data["rejected_rows"]) == (3, 1, 0)
    assert len(data["missing_states"]) == 35 and "FL" not in data["missing_states"]
    race = data["races"][0]
    assert "seat_class" not in race and "special" not in race
    assert sum(c["share_pct"] for c in race["candidates"]) == 100


@pytest.mark.parametrize("change", [
    {"votes": "-1"}, {"votes": "1.5"}, {"total_votes": "101"}, {"status": "projected"},
    {"outcome": "won"}, {"candidate": ""}, {"share_pct": "99"}, {"share_pct": "NaN"},
    {"source_url": "javascript:alert(1)"}, {"source_read_utc": "2026-11-16T13:00:00"},
    {"state": "NJ"}, {"race_id": "GOV-NJ"}, {"office": "Governor General"}, {"seats": "2"},
])
def test_invalid_records_block_promotion(rows, change):
    rows[0].update(change)
    with pytest.raises(source.ResultsSourceError):
        source.parse_results(payload(rows), len(rows))


def test_duplicates_and_row_count(rows):
    with pytest.raises(source.ResultsSourceError, match="Duplicate"):
        source.parse_results(payload(rows + [rows[0]]), 4)
    with pytest.raises(source.ResultsSourceError, match="row count"):
        source.parse_results(payload(rows), 99)


def test_null_zero_counts_and_calls(rows):
    missing = [{**r, "votes": "", "total_votes": "", "outcome": "", "status": "called"} for r in rows]
    missing[0]["outcome"] = "won"
    race = source.parse_results(payload(missing), 3)["races"][0]
    assert race["total_votes"] is None and race["status"] == "called"
    assert all(c["votes"] is None and c["share_pct"] is None for c in race["candidates"])
    missing[0]["votes"] = "0"
    with pytest.raises(source.ResultsSourceError, match="Partially missing"):
        source.parse_results(payload(missing), 3)
    zero = [{**r, "votes": "0", "total_votes": "0", "outcome": ""} for r in rows]
    assert all(c["share_pct"] is None for c in source.parse_results(payload(zero), 3)["races"][0]["candidates"])


def test_daily_replay_and_corrections(tmp_path, monkeypatch, rows):
    raw, calls = upstream(monkeypatch, rows)
    first = cache.refresh_snapshot(tmp_path, now=NOW)
    assert (first["inserted"], first["updated"], first["unchanged"]) == (3, 0, 0)
    assert cache.refresh_snapshot(tmp_path, now=NOW + timedelta(hours=23))["status"] == "cached"
    assert len(calls) == 2
    report = cache.refresh_snapshot(tmp_path, now=NOW + timedelta(days=1))
    assert report["unchanged"] == 3 and len(calls) == 3
    restarted = cache.read_snapshot(tmp_path, NOW + timedelta(days=1))
    assert restarted["retrieved_at"] == NOW.isoformat() and not restarted["stale"]
    assert cache.read_snapshot(tmp_path, NOW + timedelta(days=2))["stale"]
    rows[0]["votes"], rows[1]["votes"] = "59", "36"
    upstream(monkeypatch, rows)
    report = cache.refresh_snapshot(tmp_path, now=NOW + timedelta(days=2))
    assert (report["inserted"], report["updated"], report["unchanged"]) == (0, 2, 1)
    assert len(list((tmp_path / "raw").glob("*.csv"))) == 2
    assert (tmp_path / "raw" / f"{sha256(raw).hexdigest()}.csv").read_bytes() == raw


@pytest.mark.parametrize("failure", ["checksum", "validation", "missing_race", "network", "older_manifest"])
def test_failures_retain_last_good(tmp_path, monkeypatch, rows, failure):
    upstream(monkeypatch, rows)
    cache.refresh_snapshot(tmp_path, now=NOW)
    pointer = (tmp_path / "latest.json").read_bytes()
    changed = deepcopy(rows)
    if failure == "validation": changed[0]["votes"] = "61"
    if failure == "missing_race": changed = [{**r, "race_id": "GOV-WY", "state": "WY"} for r in rows]
    upstream(monkeypatch, changed, bad_checksum=failure == "checksum")
    original = source.download
    if failure in {"network", "older_manifest"}:
        def download(url):
            if failure == "network": raise OSError("Sensitive network details")
            body = original(url)
            if url == source.MANIFEST_URL:
                doc = json.loads(body); doc["generated_utc"] = "2026-11-16T00:00:00Z"
                return json.dumps(doc).encode()
            return body
        monkeypatch.setattr(source, "download", download)
    with pytest.raises((source.ResultsSourceError, OSError)):
        cache.refresh_snapshot(tmp_path, force=True, now=NOW + timedelta(hours=1))
    assert (tmp_path / "latest.json").read_bytes() == pointer
    data = cache.read_snapshot(tmp_path, NOW + timedelta(hours=1))
    assert data["refresh_failed"] and data["stale"]
    assert "Sensitive" not in (tmp_path / "last_attempt.json").read_text()


def test_api_read_only_and_corruption(tmp_path, monkeypatch, rows):
    upstream(monkeypatch, rows)
    cache.refresh_snapshot(tmp_path, now=NOW)
    monkeypatch.setenv("GOVERNOR_RESULTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(source, "download", lambda _: pytest.fail("API contacted upstream"))
    with TestClient(app) as client:
        response = client.get("/api/v1/governor/2026/results")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["expected_contests"] == 36 and data["races"][0]["total_votes"] == 100
        (tmp_path / "raw" / f"{data['sha256']}.csv").write_bytes(b"corrupt")
        response = client.get("/api/v1/governor/2026/results")
        assert response.status_code == 503 and str(tmp_path) not in response.text


def test_missing_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNOR_RESULTS_CACHE_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/v1/governor/2026/results").status_code == 503


def test_scheduler_retry_and_lifespan(monkeypatch):
    from importlib import import_module
    main = import_module("app.main")
    events = []
    def refresh():
        events.append("attempt")
        raise OSError("offline")
    async def sleep(seconds):
        assert seconds == 3600
        if len(events) == 2: raise asyncio.CancelledError()
    monkeypatch.setattr(cache, "refresh_snapshot", refresh)
    monkeypatch.setattr(cache.asyncio, "sleep", sleep)
    async def retry():
        with pytest.raises(asyncio.CancelledError): await cache.daily_refresh()
    asyncio.run(retry())
    assert events == ["attempt", "attempt"]
    async def background():
        events.append("start")
        try: await asyncio.Future()
        finally: events.append("stop")
    monkeypatch.setenv("GOVERNOR_RESULTS_AUTO_REFRESH", "1")
    monkeypatch.setattr(main, "daily_governor_refresh", background)
    async def lifecycle():
        async with main.lifespan(app):
            future = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(future.set_result, None)
            await future
        assert events[-2:] == ["start", "stop"]
    asyncio.run(lifecycle())


@pytest.mark.skipif(not os.getenv("CURRENT_GOVERNOR_CACHE_DIR"), reason="Requires explicitly retained live inputs")
def test_retained_live_governor_snapshot():
    data = cache.read_snapshot(Path(os.environ["CURRENT_GOVERNOR_CACHE_DIR"]))
    assert len(data["races"]) == 36 and not data["missing_states"]
    assert data["accepted_rows"] == sum(len(r["candidates"]) for r in data["races"])
    wy = next(r for r in data["races"] if r["state_code"] == "WY")
    # Wyoming's official statewide candidate summary, checked November 17, 2026.
    assert {c["name"]: c["votes"] for c in wy["candidates"]} == {
        "Eric Barlow": 128496, "Rebecca Bextel": 31444, "Kenneth R. Casner": 27472, "Write-in": 1212}
