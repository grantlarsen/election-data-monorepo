"""House source scope, missing counts, daily lifecycle, API and seat accounting."""
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
from app.services import house_results as cache
from ingestion import current_house as source

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


@pytest.fixture
def rows():
    common = dict(race_id="CA-01", state="CA", office="House", title="California 1st District",
        status="counting", outcome="", share_pct="", total_votes="100", seats="1", called_utc="",
        count_updated_utc="2026-11-16T12:00:00Z", source="civicAPI",
        source_url="https://civicapi.org/race/example", source_read_utc="2026-11-16T13:00:00Z",
        page_url="https://www.callthemap.com/results/house/ca-01")
    return [{**common, "candidate": "Candidate D", "party": "D", "votes": "60", "outcome": "leads"},
            {**common, "candidate": "Candidate R", "party": "R", "votes": "35"},
            {**common, "candidate": "Write-in", "party": "O", "votes": "5"}]


def upstream(monkeypatch, rows, *, bad_checksum=False):
    raw = pl.DataFrame(rows).write_csv().encode()
    manifest = json.dumps(dict(schema_version="ctm-results-open-data-v1", generated_utc="2026-11-17T05:00:00Z",
        license={"name": "CC BY 4.0"}, files=[dict(path="races.csv", table="races", format="csv", rows=len(rows),
        bytes=len(raw), sha256="a" * 64 if bad_checksum else sha256(raw).hexdigest())])).encode()
    calls = []
    def download(url):
        calls.append(url)
        return manifest if url == source.MANIFEST_URL else raw
    monkeypatch.setattr(source, "download", download)
    return raw, calls


def parse(rows):
    return source.parse_results(pl.DataFrame(rows).write_csv().encode(), len(rows))


def test_apportionment_scope_and_non_house_exclusions(rows):
    assert len(source.EXPECTED_CONTESTS) == sum(source.DISTRICT_COUNTS.values()) == 435
    result = parse(rows + [{**rows[0], "race_id": "AG-AL", "office": "Attorney General", "state": "AL"}])
    assert (result["accepted_rows"], result["excluded_rows"]) == (3, 1)
    assert len(result["missing_districts"]) == 434
    assert result["races"][0]["district_code"] == "01"
    assert result["races"][0]["candidates"][2]["name"] == "Write-in"
    for state in ("AK", "DE", "ND", "SD", "VT", "WY"):
        race = parse([{**r, "state": state, "race_id": f"{state}-AL"} for r in rows])["races"][0]
        assert race["district_code"] == "00"


@pytest.mark.parametrize("change", [{"race_id": "CA-53"}, {"race_id": "AK-01", "state": "AK"},
    {"race_id": "DC-AL", "state": "DC"}, {"state": "TX"}, {"office": "US House"},
    {"votes": "-1"}, {"votes": "1.5"}, {"votes": ""}, {"total_votes": ""}, {"total_votes": "101"},
    {"share_pct": "NaN"}, {"source_url": "javascript:alert(1)"}, {"outcome": "won"}])
def test_rejects_invalid_scope_and_counts(rows, change):
    rows[0].update(change)
    with pytest.raises(source.ResultsSourceError):
        parse(rows)


def test_missing_counts_and_zero_counts_remain_distinct(rows):
    missing = [{**rows[0], "votes": "", "total_votes": "", "status": "called", "outcome": "won"}]
    race = parse(missing)["races"][0]
    assert race["total_votes"] is None and race["candidates"][0]["votes"] is None
    assert race["candidates"][0]["share_pct"] is None
    assert cache.house_control({"races": [race]})["called"]["D"] == 1
    zero = parse([{**r, "votes": "0", "total_votes": "0"} for r in rows])["races"][0]
    assert zero["total_votes"] == 0 and all(c["share_pct"] is None for c in zero["candidates"])
    missing[0]["share_pct"] = "100"
    with pytest.raises(source.ResultsSourceError):
        parse(missing)


def test_daily_reuse_restart_correction_and_unchanged_manifest(tmp_path, monkeypatch, rows):
    raw, calls = upstream(monkeypatch, rows)
    report = cache.refresh_snapshot(tmp_path, now=NOW)
    assert (report["inserted"], report["updated"], report["unchanged"]) == (3, 0, 0)
    assert len(calls) == 2
    assert cache.refresh_snapshot(tmp_path, now=NOW + timedelta(hours=23))["status"] == "cached"
    assert len(calls) == 2
    report = cache.refresh_snapshot(tmp_path, now=NOW + timedelta(days=1))
    assert report["unchanged"] == 3 and len(calls) == 3
    data = cache.read_snapshot(tmp_path, NOW + timedelta(days=1))
    assert data["retrieved_at"] == NOW.isoformat() and not data["stale"]
    assert cache.read_snapshot(tmp_path, NOW + timedelta(days=2))["stale"]
    rows[0]["votes"], rows[1]["votes"] = "59", "36"
    upstream(monkeypatch, rows)
    report = cache.refresh_snapshot(tmp_path, now=NOW + timedelta(days=2))
    assert (report["inserted"], report["updated"], report["unchanged"]) == (0, 2, 1)
    assert len(list((tmp_path / "raw").glob("*.csv"))) == 2
    assert (tmp_path / "raw" / f"{sha256(raw).hexdigest()}.csv").read_bytes() == raw


@pytest.mark.parametrize("failure", ["checksum", "validation", "missing_race", "network", "older_manifest"])
def test_failed_refresh_retains_last_good(tmp_path, monkeypatch, rows, failure):
    upstream(monkeypatch, rows)
    cache.refresh_snapshot(tmp_path, now=NOW)
    pointer = (tmp_path / "latest.json").read_bytes()
    changed = deepcopy(rows)
    if failure == "validation": changed[0]["votes"] = "61"
    if failure == "missing_race":
        changed = [{**r, "race_id": "CA-02"} for r in rows]
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
    assert cache.read_snapshot(tmp_path, NOW + timedelta(hours=1))["refresh_failed"]
    assert "Sensitive" not in (tmp_path / "last_attempt.json").read_text()


def test_api_no_network_null_counts_and_corruption(tmp_path, monkeypatch, rows):
    from app.api import house
    from app.api.elections import get_read_session
    monkeypatch.setitem(app.dependency_overrides, get_read_session, lambda: None)
    monkeypatch.setattr(house, 'enrich_snapshot', lambda _session, snapshot: {**snapshot, 'control': cache.house_control(snapshot)})
    upstream(monkeypatch, [{**rows[0], "votes": "", "total_votes": "", "status": "called", "outcome": "won"}])
    cache.refresh_snapshot(tmp_path, now=NOW)
    monkeypatch.setenv("HOUSE_RESULTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(source, "download", lambda _: pytest.fail("API contacted upstream"))
    with TestClient(app) as client:
        response = client.get("/api/v1/house/2026/results")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["races"][0]["total_votes"] is None and data["control"]["called"]["D"] == 1
        (tmp_path / "raw" / f"{data['sha256']}.csv").write_bytes(b"corrupt")
        response = client.get("/api/v1/house/2026/results")
        assert response.status_code == 503 and str(tmp_path) not in response.text


def test_missing_cache_503(tmp_path, monkeypatch):
    from app.api.elections import get_read_session
    monkeypatch.setitem(app.dependency_overrides, get_read_session, lambda: None)
    monkeypatch.setenv("HOUSE_RESULTS_CACHE_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/v1/house/2026/results").status_code == 503


def test_control_only_counts_explicit_winners_and_requires_218(rows):
    template = parse(rows)["races"][0]
    races = []
    for identifier in list(source.EXPECTED_CONTESTS)[:218]:
        race = deepcopy(template); race["id"] = identifier
        race["status"] = "called"; race["candidates"][0]["outcome"] = "won"
        races.append(race)
    c = cache.house_control({"races": races[:-1]})
    assert c["control"] is None and c["unresolved"] == 218
    c = cache.house_control({"races": races})
    assert c["control"] == "D" and c["called"]["D"] == 218
    races[0]["status"] = "counting"; races[0]["candidates"][0]["outcome"] = "leads"
    races[1]["candidates"][0]["party"] = "I"
    c = cache.house_control({"races": races})
    assert c["control"] is None and c["called"]["other"] == 1
    assert sum(c["called"].values()) + c["unresolved"] == 435
    with pytest.raises(source.ResultsSourceError):
        cache.house_control({"races": [races[0], races[0]]})


def test_house_scheduler_lifespan_and_retry(monkeypatch):
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
    monkeypatch.setenv("HOUSE_RESULTS_AUTO_REFRESH", "1")
    monkeypatch.setattr(main, "daily_house_refresh", background)
    # Avoid the patched sleep while allowing the new task to run.
    async def lifecycle():
        async with main.lifespan(app):
            future = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(future.set_result, None)
            await future
        assert events[-2:] == ["start", "stop"]
    asyncio.run(lifecycle())


@pytest.mark.skipif(not os.getenv("CURRENT_HOUSE_CACHE_DIR"), reason="Requires explicitly retained live inputs")
def test_retained_live_house_snapshot():
    data = cache.read_snapshot(Path(os.environ["CURRENT_HOUSE_CACHE_DIR"]))
    assert len(data["races"]) == 435 and not data["missing_districts"]
    assert data["accepted_rows"] == sum(len(r["candidates"]) for r in data["races"])
    wy = next(r for r in data["races"] if r["id"] == "WY-AL")
    # Wyoming's official statewide candidate summary, verified November 17, 2026.
    assert {c["name"]: c["votes"] for c in wy["candidates"]} == {
        "Chuck Gray": 99906, "Lisa Kinney": 61689, "Shawn Johnson": 13667, "Jeffrey Haggit": 7961, "Write-in": 1031}
