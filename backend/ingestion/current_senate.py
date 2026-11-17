"""Acquire and validate provisional Senate counts; never publish canonical identities.

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

YEAR = 2026
ELECTION_DATE = "2026-11-03"
BASE_URL = f"https://www.callthemap.com/results/data/{YEAR}"
MANIFEST_URL = BASE_URL + "/manifest.json"
RESULTS_URL = BASE_URL + "/races.csv"
RULESET = "call-the-map-senate-v1"
# Official calendar: https://www.fec.gov/resources/cms-content/documents/2026pdates.pdf
# Class II: https://www.senate.gov/senators/Class_II.htm
REGULAR_STATES = frozenset("AK AL AR CO DE GA IA ID IL KS KY LA MA ME MI MN MS MT NC NE NH NJ NM OK OR RI SC SD TN TX VA WV WY".split())
SPECIAL_STATES = frozenset({"FL", "OH"})
EXPECTED_STATES = REGULAR_STATES | SPECIAL_STATES
REQUIRED = {"race_id", "state", "office", "title", "status", "outcome", "candidate",
            "party", "votes", "share_pct", "total_votes", "seats", "called_utc",
            "count_updated_utc", "source", "source_url", "source_read_utc", "page_url"}


class SenateSourceError(ValueError):
    """Source contract or count reconciliation failed; retain the previous snapshot."""


def utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SenateSourceError("Source timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def public_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ElectoralAtlas/1.0 (daily Senate research cache)",
                                    "Accept": "text/csv, application/json"})
    with urlopen(request, timeout=30) as response:
        body = response.read(16 * 1024 * 1024 + 1)
    if len(body) > 16 * 1024 * 1024:
        raise SenateSourceError("Source exceeds the 16 MiB download limit")
    return body


def manifest_entry(raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "ctm-results-open-data-v1":
        raise SenateSourceError("Unsupported results manifest version")
    utc_timestamp(manifest["generated_utc"])
    if manifest.get("license", {}).get("name") != "CC BY 4.0":
        raise SenateSourceError("Source license changed; review before refreshing")
    entries = [item for item in manifest["files"] if item["path"] == "races.csv"]
    if len(entries) != 1:
        raise SenateSourceError("Manifest must identify exactly one races.csv")
    entry = entries[0]
    if (entry.get("table") != "races" or entry.get("format") != "csv"
            or not isinstance(entry.get("rows"), int) or entry["rows"] <= 0
            or not isinstance(entry.get("bytes"), int) or entry["bytes"] <= 0
            or len(entry.get("sha256", "")) != 64):
        raise SenateSourceError("Invalid results manifest entry")
    return manifest, entry


def parse_results(raw: bytes, expected_rows: int) -> dict[str, Any]:
    """Validate all Senate rows before promotion; other offices are counted as excluded.

    Source labels (including write-ins and party lines) remain distinct. Shares
    use the source contest total, reconciled to every candidate/bucket, never
    just the top two. Media calls remain separate from source certification.
    """
    try:
        frame = pl.read_csv(BytesIO(raw), infer_schema=False, row_index_name="source_row_number",
                            row_index_offset=1).fill_null("")
        if not REQUIRED <= set(frame.columns) or frame.height != expected_rows:
            raise SenateSourceError("CSV schema or manifest row count mismatch")
        senate = frame.filter(pl.col("office") == "Senate")
        # A changed office label must not silently remove a Senate race.
        if frame.filter(pl.col("race_id").str.starts_with("SEN-") & (pl.col("office") != "Senate")).height:
            raise SenateSourceError("Senate race has an unexpected office label")
        if senate.is_empty():
            raise SenateSourceError("Source contains no Senate results")
        senate = senate.with_columns(pl.col("votes", "total_votes", "seats").cast(pl.Int64, strict=True))
        if senate.filter((pl.col("votes") < 0) | (pl.col("total_votes") < 0) | (pl.col("seats") != 1)).height:
            raise SenateSourceError("Negative votes or unsupported multi-seat contest")
        if senate.group_by("race_id", "candidate", "party").len().filter(pl.col("len") > 1).height:
            raise SenateSourceError("Duplicate candidate/party lines require source review")
        races = []
        for group in senate.partition_by("race_id", maintain_order=True):
            rows = group.to_dicts()
            first = rows[0]
            state = first["state"]
            if state not in EXPECTED_STATES or first["race_id"] != f"SEN-{state}":
                raise SenateSourceError("Unexpected Senate contest identifier")
            shared = ("state", "title", "status", "total_votes", "called_utc", "count_updated_utc",
                      "source", "source_url", "source_read_utc", "page_url")
            if any(any(row[key] != first[key] for key in shared) for row in rows):
                raise SenateSourceError("Inconsistent contest metadata")
            if first["status"] not in {"counting", "called", "final"}:
                raise SenateSourceError("Unknown source result status")
            if sum(row["votes"] for row in rows) != first["total_votes"]:
                raise SenateSourceError("Candidate votes do not reconcile to contest total")
            if not first["source"].strip() or not first["title"].strip():
                raise SenateSourceError("Missing source or contest title")
            if not all(public_url(first[key]) for key in ("source_url", "page_url")):
                raise SenateSourceError("Invalid source evidence URL")
            for key in ("count_updated_utc", "source_read_utc", "called_utc"):
                if first[key]:
                    utc_timestamp(first[key])
            if not first["source_read_utc"]:
                raise SenateSourceError("Missing source retrieval timestamp")
            winners = sum(row["outcome"] == "won" for row in rows)
            if (winners > 1 or (first["status"] == "counting" and winners)
                    or (first["status"] in {"called", "final"} and winners != 1)):
                raise SenateSourceError("Inconsistent source call/certification")
            candidates = []
            for row in rows:
                if not row["candidate"].strip() or row["outcome"] not in {"", "leads", "won"}:
                    raise SenateSourceError("Missing candidate label or unknown outcome")
                share = 100 * row["votes"] / row["total_votes"] if row["total_votes"] else None
                if row["share_pct"]:
                    reported_share = float(row["share_pct"])
                    if not isfinite(reported_share) or share is None or abs(reported_share - share) > 0.02:
                        raise SenateSourceError("Source share disagrees with reconciled votes")
                candidates.append({"name": row["candidate"], "party": row["party"], "votes": row["votes"],
                    "share_pct": share, "source_share_pct": row["share_pct"], "outcome": row["outcome"],
                    "source_row_number": row["source_row_number"]})
            candidates.sort(key=lambda row: (-row["votes"], row["name"], row["party"]))
            races.append({"id": first["race_id"], "state_code": state, "state_name": STATE_NAMES[state].title(),
                "seat_class": 3 if state in SPECIAL_STATES else 2, "special": state in SPECIAL_STATES,
                "status": first["status"], "total_votes": first["total_votes"], "candidates": candidates,
                "count_updated_at": first["count_updated_utc"] or None,
                "source_read_at": first["source_read_utc"], "called_at": first["called_utc"] or None,
                "source": first["source"], "source_url": first["source_url"], "page_url": first["page_url"]})
        races.sort(key=lambda row: row["state_name"])
        return {"races": races, "missing_states": sorted(EXPECTED_STATES - {r["state_code"] for r in races}),
                "input_rows": frame.height, "accepted_rows": senate.height,
                "excluded_rows": frame.height - senate.height, "rejected_rows": 0}
    except (pl.exceptions.PolarsError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, SenateSourceError):
            raise
        raise SenateSourceError("Malformed Senate results payload") from exc
