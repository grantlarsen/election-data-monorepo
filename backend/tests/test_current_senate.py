"""Offline contract, cache lifecycle, failure recovery, API and scheduler checks."""
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
from app.services import senate_results as cache
from ingestion import current_senate as source

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


@pytest.fixture
def rows():
    def row(name, party, votes, **extra):
        return dict(race_id="SEN-FL", state="FL", office="Senate", title="Florida Senate",
            status="counting", outcome="leads" if party == "R" else "", candidate=name,
            party=party, votes=str(votes), share_pct="", total_votes="100", seats="1",
            called_utc="", count_updated_utc="2026-11-16T12:00:00Z",
            source="civicAPI", source_url="https://civicapi.org/race/example",
            source_read_utc="2026-11-16T13:00:00Z", page_url="https://www.callthemap.com/results/senate/fl",
            **extra)
    return [row("Candidate R", "R", 60), row("Candidate D", "D", 35), row("Write-in", "O", 5)]


def payload(rows):
    return pl.DataFrame(rows).write_csv().encode()


def manifest(raw, row_count=3, **extra):
    return json.dumps(dict(schema_version="ctm-results-open-data-v1", generated_utc="2026-11-16T15:00:00Z",
        license={"name": "CC BY 4.0"}, files=[dict(path="races.csv", table="races", format="csv",
            rows=row_count, bytes=len(raw), sha256=sha256(raw).hexdigest())], **extra)).encode()


def upstream(monkeypatch, rows):
    raw = payload(rows)
    calls = []
    def download(url):
        calls.append(url)
        return manifest(raw, len(rows)) if url == source.MANIFEST_URL else raw
    monkeypatch.setattr(source, "download", download)
    return raw, calls


def test_scope_shares_specials_buckets_and_exclusions(rows):
    other = {**rows[0], "office": "House", "race_id": "FL-01"}
    result = source.parse_results(payload(rows + [other]), 4)
    assert (result["input_rows"], result["accepted_rows"], result["excluded_rows"], result["rejected_rows"]) == (4, 3, 1, 0)
    race = result["races"][0]
    assert race["special"] and race["seat_class"] == 3
    assert race["status"] == "counting" and race["candidates"][0]["outcome"] == "leads"
    assert [c["share_pct"] for c in race["candidates"]] == [60, 35, 5]
    assert race["candidates"][2]["name"] == "Write-in"
    assert len(result["missing_states"]) == 34
    for state, special, seat_class in (("OH", True, 3), ("WY", False, 2)):
        changed = [{**r, "race_id": f"SEN-{state}", "state": state} for r in rows]
        race = source.parse_results(payload(changed), 3)["races"][0]
        assert (race["special"], race["seat_class"]) == (special, seat_class)


@pytest.mark.parametrize("change", [
    {"votes": "-1"}, {"votes": ""}, {"votes": "1.5"}, {"total_votes": "101"},
    {"status": "projected"}, {"outcome": "won"}, {"candidate": ""},
    {"share_pct": "99"}, {"share_pct": "NaN"}, {"source_url": "javascript:alert(1)"},
    {"source_read_utc": "2026-11-16T13:00:00"}, {"state": "DC"},
    {"race_id": "SEN-FL-special"}, {"office": "US Senate"}, {"seats": "2"},
])
def test_rejects_invalid_records(rows, change):
    rows[0].update(change)
    with pytest.raises(source.SenateSourceError):
        source.parse_results(payload(rows), len(rows))


def test_duplicate_and_manifest_mismatch_fail(rows):
    with pytest.raises(source.SenateSourceError, match="Duplicate"):
        source.parse_results(payload(rows + [rows[0]]), 4)
    with pytest.raises(source.SenateSourceError, match="row count"):
        source.parse_results(payload(rows), 99)


def test_zero_counts_have_no_share_and_calls_are_not_certification(rows):
    for row in rows:
        row.update(votes="0", total_votes="0", outcome="")
    race = source.parse_results(payload(rows), 3)["races"][0]
    assert all(candidate["share_pct"] is None for candidate in race["candidates"])
    for row in rows:
        row["status"] = "called"
    rows[0]["outcome"] = "won"
    assert source.parse_results(payload(rows), 3)["races"][0]["status"] == "called"
    for row in rows:
        row["status"] = "final"
    assert source.parse_results(payload(rows), 3)["races"][0]["status"] == "final"


def test_daily_cache_replay_and_persistent_restart(tmp_path, monkeypatch, rows):
    raw, calls = upstream(monkeypatch, rows)
    report = cache.refresh_snapshot(tmp_path, now=NOW)
    assert (report["inserted"], report["updated"], report["unchanged"]) == (3, 0, 0)
    first = cache.read_snapshot(tmp_path, NOW)
    assert not first["stale"] and not first["refresh_failed"]
    assert first["races"][0]["total_votes"] == 100
    assert len(calls) == 2
    assert cache.refresh_snapshot(tmp_path, now=NOW + timedelta(hours=23))["status"] == "cached"
    assert len(calls) == 2
    report = cache.refresh_snapshot(tmp_path, now=NOW + timedelta(days=1))
    assert (report["status"], report["inserted"], report["updated"], report["unchanged"]) == ("unchanged", 0, 0, 3)
    assert calls == [source.MANIFEST_URL, source.RESULTS_URL, source.MANIFEST_URL]
    restarted = cache.read_snapshot(tmp_path, NOW + timedelta(days=1))
    assert restarted["retrieved_at"] == first["retrieved_at"]
    assert restarted["checked_at"] != first["checked_at"]
    assert len(list((tmp_path / "raw").glob("*.csv"))) == 1
    assert cache.read_snapshot(tmp_path, NOW + timedelta(days=2))["stale"]


def test_changed_counts_report_updates_without_duplicate_inputs(tmp_path, monkeypatch, rows):
    upstream(monkeypatch, rows)
    first = cache.refresh_snapshot(tmp_path, now=NOW)
    rows[0]["votes"], rows[1]["votes"] = "59", "36"  # Legitimate correction downward.
    upstream(monkeypatch, rows)
    report = cache.refresh_snapshot(tmp_path, force=True, now=NOW + timedelta(hours=1))
    assert (report["inserted"], report["updated"], report["unchanged"]) == (0, 2, 1)
    assert report["sha256"] != first["sha256"]
    assert len(list((tmp_path / "raw").glob("*.csv"))) == 2


@pytest.mark.parametrize("failure", ["network", "checksum", "validation", "missing_race", "manifest_version", "license"])
def test_bad_refresh_retains_last_good_snapshot(tmp_path, monkeypatch, rows, failure):
    raw, _ = upstream(monkeypatch, rows)
    cache.refresh_snapshot(tmp_path, now=NOW)
    pointer = (tmp_path / "latest.json").read_bytes()
    changed = deepcopy(rows)
    if failure == "validation":
        changed[0]["votes"] = "61"
    if failure == "missing_race":
        changed = [{**r, "race_id": "SEN-OH", "state": "OH"} for r in rows]
    new_raw = payload(changed)
    def download(url):
        if failure == "network":
            raise OSError("Sensitive upstream connection details")
        if url == source.RESULTS_URL:
            return b"invalid" if failure == "checksum" else new_raw
        new_manifest = json.loads(manifest(new_raw))
        if failure == "checksum":
            new_manifest["files"][0]["sha256"] = "a" * 64
        if failure == "manifest_version":
            new_manifest["schema_version"] = "unknown"
        if failure == "license":
            new_manifest["license"]["name"] = "restricted"
        return json.dumps(new_manifest).encode()
    monkeypatch.setattr(source, "download", download)
    with pytest.raises((source.SenateSourceError, OSError)):
        cache.refresh_snapshot(tmp_path, force=True, now=NOW + timedelta(hours=1))
    assert (tmp_path / "latest.json").read_bytes() == pointer
    data = cache.read_snapshot(tmp_path, NOW + timedelta(hours=1))
    assert data["sha256"] == sha256(raw).hexdigest() and data["refresh_failed"] and data["stale"]
    assert "Sensitive" not in (tmp_path / "last_attempt.json").read_text()


def test_corrupt_archives_fail_closed_and_api_is_read_only(tmp_path, monkeypatch, rows):
    from app.api.elections import get_read_session
    from app.api import senate
    raw, calls = upstream(monkeypatch, rows)
    cache.refresh_snapshot(tmp_path, now=NOW)
    monkeypatch.setenv("SENATE_RESULTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(senate, "enrich_snapshot", lambda session, snapshot: snapshot)
    # Source-cache contracts stay offline; entity enrichment is covered in PostgreSQL tests.
    monkeypatch.setattr(app, "dependency_overrides", {**app.dependency_overrides, get_read_session: lambda: None})
    with TestClient(app) as client:
        response = client.get("/api/v1/senate/2026/results")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["expected_contests"] == 35
        assert len(calls) == 2
        (tmp_path / "raw" / f"{sha256(raw).hexdigest()}.csv").write_bytes(b"corrupt")
        response = client.get("/api/v1/senate/2026/results")
        assert response.status_code == 503
        assert str(tmp_path) not in response.text
        assert client.get("/health").status_code == 200


def test_missing_cache_is_explicit_503(tmp_path, monkeypatch):
    monkeypatch.setenv("SENATE_RESULTS_CACHE_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/v1/senate/2026/results").status_code == 503


def test_scheduler_retries_failure(monkeypatch):
    attempts = []
    def refresh():
        attempts.append(True)
        raise OSError("offline")
    async def sleep(seconds):
        assert seconds == 3600
        if len(attempts) == 2:
            raise asyncio.CancelledError()
    monkeypatch.setattr(cache, "refresh_snapshot", refresh)
    monkeypatch.setattr(cache.asyncio, "sleep", sleep)
    async def run():
        with pytest.raises(asyncio.CancelledError):
            await cache.daily_refresh()
    asyncio.run(run())
    assert len(attempts) == 2


def test_lifespan_starts_and_stops_scheduler(monkeypatch):
    from importlib import import_module
    main_module = import_module("app.main")
    events = []
    async def refresh():
        events.append("started")
        try:
            await asyncio.Future()
        finally:
            events.append("stopped")
    monkeypatch.setenv("SENATE_RESULTS_AUTO_REFRESH", "1")
    monkeypatch.setattr(main_module, "daily_refresh", refresh)
    async def run():
        async with main_module.lifespan(app):
            await asyncio.sleep(0)
            assert events == ["started"]
        assert events == ["started", "stopped"]
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("CURRENT_SENATE_CACHE_DIR"), reason="Requires an explicitly retained live snapshot")
def test_retained_live_snapshot():
    data = cache.read_snapshot(Path(os.environ["CURRENT_SENATE_CACHE_DIR"]))
    assert len(data["races"]) == 35 and not data["missing_states"]
    assert data["accepted_rows"] == sum(len(r["candidates"]) for r in data["races"])
    # Independently checked official Wyoming summary, November 2026.
    wy = next(r for r in data["races"] if r["state_code"] == "WY")
    assert {c["name"]: c["votes"] for c in wy["candidates"]} == {
        "Harriet Hageman": 122174, "James Byrd": 65105, "Write-in": 1039}
