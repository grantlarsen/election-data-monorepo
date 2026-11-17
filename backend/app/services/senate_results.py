"""Durable, content-addressed provisional results with daily refresh and failover.

The single API process owns the timer. Requests only read a verified snapshot;
they never contact the upstream. Immutable inputs and run reports permit replay.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from ingestion import current_senate as source
from ingestion.source import atomic_json

LOG = logging.getLogger(__name__)
REFRESH_INTERVAL = timedelta(days=1)
_REFRESH_LOCK = Lock()


def cache_directory() -> Path:
    return Path(os.getenv("SENATE_RESULTS_CACHE_DIR", "data/ingestion/current_senate"))


@contextmanager
def _writer_lock(directory: Path):
    """Serialize the API timer and operator CLI; OS locks release after a crash."""
    directory.mkdir(parents=True, exist_ok=True)
    with _REFRESH_LOCK, (directory / "refresh.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _archive(directory: Path, body: bytes, suffix: str) -> str:
    digest = sha256(body).hexdigest()
    path = directory / "raw" / f"{digest}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise source.SenateSourceError("Cached source archive failed checksum validation")
    else:
        temporary = path.with_name(f".{digest}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return digest


def _verified(directory: Path, digest: str, suffix: str) -> bytes:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise source.SenateSourceError("Invalid snapshot checksum")
    body = (directory / "raw" / f"{digest}.{suffix}").read_bytes()
    if sha256(body).hexdigest() != digest:
        raise source.SenateSourceError("Cached source archive failed checksum validation")
    return body


def read_snapshot(directory: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    directory = directory or cache_directory()
    now = now or datetime.now(timezone.utc)
    meta = json.loads((directory / "latest.json").read_text(encoding="utf-8"))
    if meta["ruleset"] != source.RULESET:
        raise source.SenateSourceError("Cached parser version requires a refresh")
    manifest, entry = source.manifest_entry(_verified(directory, meta["manifest_sha256"], "json"))
    raw = _verified(directory, meta["sha256"], "csv")
    if entry["sha256"] != meta["sha256"] or entry["bytes"] != len(raw):
        raise source.SenateSourceError("Cached source disagrees with archived manifest")
    result = source.parse_results(raw, entry["rows"])
    failed = False
    attempt_path = directory / "last_attempt.json"
    if attempt_path.exists():
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        failed = attempt["status"] == "failed" and source.utc_timestamp(attempt["attempted_at"]) >= source.utc_timestamp(meta["checked_at"])
    due = source.utc_timestamp(meta["checked_at"]) + REFRESH_INTERVAL
    return {**result, "year": source.YEAR, "election_date": source.ELECTION_DATE,
            "expected_contests": len(source.EXPECTED_STATES), "checked_at": meta["checked_at"],
            "retrieved_at": meta["retrieved_at"], "published_at": manifest["generated_utc"],
            "next_refresh_at": due.isoformat(), "stale": now >= due or failed,
            "refresh_failed": failed, "sha256": meta["sha256"], "ruleset": source.RULESET,
            "source_url": source.RESULTS_URL, "manifest_url": source.MANIFEST_URL}


def _records(snapshot: dict[str, Any] | None) -> dict[tuple[str, str, str], dict]:
    if snapshot is None:
        return {}
    return {(race["id"], candidate["name"], candidate["party"]):
            {**{k: v for k, v in candidate.items() if k != "source_row_number"},
             "status": race["status"], "total_votes": race["total_votes"]}
            for race in snapshot["races"] for candidate in race["candidates"]}


def refresh_snapshot(directory: Path | None = None, *, force: bool = False,
                     now: datetime | None = None) -> dict[str, Any]:
    """Promote only a checksum-verified, fully validated response; report every run."""
    directory = directory or cache_directory()
    with _writer_lock(directory):
        now = now or datetime.now(timezone.utc)
        run_id = str(uuid4())
        report: dict[str, Any] = {"run_id": run_id, "attempted_at": now.isoformat(),
                                 "ruleset": source.RULESET, "source_url": source.RESULTS_URL}
        try:
            previous = read_snapshot(directory, now) if (directory / "latest.json").exists() else None
            if previous and not force and now < source.utc_timestamp(previous["next_refresh_at"]):
                return {"status": "cached", "sha256": previous["sha256"], "checked_at": previous["checked_at"]}
            manifest_raw = source.download(source.MANIFEST_URL)
            report["manifest_sha256"] = _archive(directory, manifest_raw, "json")
            manifest, entry = source.manifest_entry(manifest_raw)
            if previous and source.utc_timestamp(manifest["generated_utc"]) < source.utc_timestamp(previous["published_at"]):
                raise source.SenateSourceError("Upstream manifest moved backwards in time")
            if previous and previous["sha256"] == entry["sha256"]:
                raw = _verified(directory, previous["sha256"], "csv")
                retrieved_at = previous["retrieved_at"]
            else:
                raw = source.download(source.RESULTS_URL)
                report["sha256"] = _archive(directory, raw, "csv")
                retrieved_at = now.isoformat()
            if sha256(raw).hexdigest() != entry["sha256"] or len(raw) != entry["bytes"]:
                raise source.SenateSourceError("Downloaded results disagree with manifest checksum/size")
            parsed = source.parse_results(raw, entry["rows"])
            if previous and {r["id"] for r in previous["races"]} - {r["id"] for r in parsed["races"]}:
                raise source.SenateSourceError("Previously available contests disappeared; retain last good snapshot")
            old, new = _records(previous), _records(parsed)
            report.update(status="updated" if old != new else "unchanged", sha256=entry["sha256"],
                input_rows=parsed["input_rows"], accepted_rows=parsed["accepted_rows"],
                excluded_rows=parsed["excluded_rows"], rejected_rows=0,
                inserted=sum(key not in old for key in new),
                updated=sum(key in old and old[key] != value for key, value in new.items()),
                unchanged=sum(key in old and old[key] == value for key, value in new.items()),
                removed=sum(key not in new for key in old), missing_states=parsed["missing_states"])
            metadata = {"ruleset": source.RULESET, "sha256": entry["sha256"],
                "manifest_sha256": report["manifest_sha256"], "checked_at": now.isoformat(),
                "retrieved_at": retrieved_at, "run_id": run_id}
            # The last-good pointer changes only after every input passes validation.
            atomic_json(directory / "reports" / f"{run_id}.json", report)
            atomic_json(directory / "latest.json", metadata)
            atomic_json(directory / "last_attempt.json", report)
            LOG.info("Senate results refresh completed", extra={"run_id": run_id, "status": report["status"],
                     "accepted_rows": parsed["accepted_rows"], "sha256": entry["sha256"]})
            return report
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__)
            if isinstance(exc, source.SenateSourceError):
                report["validation_error"] = str(exc)
            atomic_json(directory / "reports" / f"{run_id}.json", report)
            atomic_json(directory / "last_attempt.json", report)
            LOG.error("Senate results refresh failed; last good snapshot retained",
                      extra={"run_id": run_id, "error_type": type(exc).__name__,
                             "validation_error": report.get("validation_error")})
            raise


async def daily_refresh() -> None:
    """Refresh on startup when due, then check hourly; failures retry in one hour."""
    while True:
        try:
            await asyncio.to_thread(refresh_snapshot)
            from app.services.senate_entities import sync_cached_entities
            await asyncio.to_thread(sync_cached_entities)
        except Exception:
            # Never stop the API; include lock/filesystem failures in the log too.
            LOG.warning("Daily Senate refresh will retry in one hour")
        await asyncio.sleep(3600)
