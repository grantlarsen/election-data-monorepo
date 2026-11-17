"""Acquire and validate provisional election counts; never publish canonical identities.

Contract and attribution: https://www.callthemap.com/results/data/2026/README.txt
The source is a CC BY 4.0 compilation of state returns, partly via civicAPI.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from math import isfinite
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import polars as pl

from ingestion.medsl import STATE_NAMES

REQUIRED = {"race_id", "state", "office", "title", "status", "outcome", "candidate",
            "party", "votes", "share_pct", "total_votes", "seats", "called_utc",
            "count_updated_utc", "source", "source_url", "source_read_utc", "page_url"}


class ResultsSourceError(ValueError):
    """Source contract or count reconciliation failed; retain the previous snapshot."""


def utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ResultsSourceError("Source timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def public_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ElectoralAtlas/1.0 (daily election research cache)",
                                    "Accept": "text/csv, application/json"})
    with urlopen(request, timeout=30) as response:
        body = response.read(16 * 1024 * 1024 + 1)
    if len(body) > 16 * 1024 * 1024:
        raise ResultsSourceError("Source exceeds the 16 MiB download limit")
    return body


def manifest_entry(raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "ctm-results-open-data-v1":
        raise ResultsSourceError("Unsupported results manifest version")
    utc_timestamp(manifest["generated_utc"])
    if manifest.get("license", {}).get("name") != "CC BY 4.0":
        raise ResultsSourceError("Source license changed; review before refreshing")
    entries = [item for item in manifest["files"] if item["path"] == "races.csv"]
    if len(entries) != 1:
        raise ResultsSourceError("Manifest must identify exactly one races.csv")
    entry = entries[0]
    if (entry.get("table") != "races" or entry.get("format") != "csv"
            or not isinstance(entry.get("rows"), int) or entry["rows"] <= 0
            or not isinstance(entry.get("bytes"), int) or entry["bytes"] <= 0
            or len(entry.get("sha256", "")) != 64):
        raise ResultsSourceError("Invalid results manifest entry")
    return manifest, entry


def parse_contests(raw: bytes, expected_rows: int, *, office: str,
                   expected_contests: dict[str, dict[str, Any]], identifier_pattern: str,
                   allow_missing_votes: bool = False) -> dict[str, Any]:
    """Validate one office's candidate lines without inferring identities or winners."""
    try:
        frame = pl.read_csv(BytesIO(raw), infer_schema=False, row_index_name="source_row_number",
                            row_index_offset=1).fill_null("")
        if not REQUIRED <= set(frame.columns) or frame.height != expected_rows:
            raise ResultsSourceError("CSV schema or manifest row count mismatch")
        contests = frame.filter(pl.col("office") == office)
        # A changed office label must not silently remove an in-scope race.
        if frame.filter(pl.col("race_id").str.contains(identifier_pattern) & (pl.col("office") != office)).height:
            raise ResultsSourceError("Election race has an unexpected office label")
        if contests.is_empty():
            raise ResultsSourceError("Source contains no election results")
        if allow_missing_votes:
            contests = contests.with_columns(pl.col("votes", "total_votes").replace("", None))
        contests = contests.with_columns(pl.col("votes", "total_votes", "seats").cast(pl.Int64, strict=True))
        if contests.filter((pl.col("votes") < 0) | (pl.col("total_votes") < 0) | (pl.col("seats") != 1)).height:
            raise ResultsSourceError("Negative votes or unsupported multi-seat contest")
        if contests.group_by("race_id", "candidate", "party").len().filter(pl.col("len") > 1).height:
            raise ResultsSourceError("Duplicate candidate/party lines require source review")
        races = []
        for group in contests.partition_by("race_id", maintain_order=True):
            rows = group.to_dicts()
            first = rows[0]
            state = first["state"]
            if first["race_id"] not in expected_contests or state != expected_contests[first["race_id"]]["state_code"]:
                raise ResultsSourceError("Unexpected contest identifier")
            shared = ("state", "title", "status", "total_votes", "called_utc", "count_updated_utc",
                      "source", "source_url", "source_read_utc", "page_url")
            if any(any(row[key] != first[key] for key in shared) for row in rows):
                raise ResultsSourceError("Inconsistent contest metadata")
            if first["status"] not in {"counting", "called", "final"}:
                raise ResultsSourceError("Unknown source result status")
            missing_total = first["total_votes"] is None
            if any((row["votes"] is None) != missing_total for row in rows):
                raise ResultsSourceError("Partially missing contest counts require source review")
            if not missing_total and sum(row["votes"] for row in rows) != first["total_votes"]:
                raise ResultsSourceError("Candidate votes do not reconcile to contest total")
            if not first["source"].strip() or not first["title"].strip():
                raise ResultsSourceError("Missing source or contest title")
            if not all(public_url(first[key]) for key in ("source_url", "page_url")):
                raise ResultsSourceError("Invalid source evidence URL")
            for key in ("count_updated_utc", "source_read_utc", "called_utc"):
                if first[key]:
                    utc_timestamp(first[key])
            if not first["source_read_utc"]:
                raise ResultsSourceError("Missing source retrieval timestamp")
            winners = sum(row["outcome"] == "won" for row in rows)
            if (winners > 1 or (first["status"] == "counting" and winners)
                    or (first["status"] in {"called", "final"} and winners != 1)):
                raise ResultsSourceError("Inconsistent source call/certification")
            candidates = []
            for row in rows:
                if not row["candidate"].strip() or row["outcome"] not in {"", "leads", "won"}:
                    raise ResultsSourceError("Missing candidate label or unknown outcome")
                share = 100 * row["votes"] / row["total_votes"] if row["total_votes"] else None
                if row["share_pct"]:
                    reported_share = float(row["share_pct"])
                    if not isfinite(reported_share) or share is None or abs(reported_share - share) > 0.02:
                        raise ResultsSourceError("Source share disagrees with reconciled votes")
                candidates.append({"name": row["candidate"], "party": row["party"], "votes": row["votes"],
                    "share_pct": share, "source_share_pct": row["share_pct"], "outcome": row["outcome"],
                    "source_row_number": row["source_row_number"]})
            candidates.sort(key=lambda row: (-(row["votes"] if row["votes"] is not None else -1), row["name"], row["party"]))
            races.append({"id": first["race_id"], "state_code": state, "state_name": STATE_NAMES[state].title(),
                **expected_contests[first["race_id"]],
                "status": first["status"], "total_votes": first["total_votes"], "candidates": candidates,
                "count_updated_at": first["count_updated_utc"] or None,
                "source_read_at": first["source_read_utc"], "called_at": first["called_utc"] or None,
                "source": first["source"], "source_url": first["source_url"], "page_url": first["page_url"]})
        races.sort(key=lambda row: (row["state_name"], row["id"]))
        return {"races": races, "missing_contests": sorted(expected_contests.keys() - {r["id"] for r in races}),
                "input_rows": frame.height, "accepted_rows": contests.height,
                "excluded_rows": frame.height - contests.height, "rejected_rows": 0}
    except (pl.exceptions.PolarsError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ResultsSourceError):
            raise
        raise ResultsSourceError("Malformed election results payload") from exc
