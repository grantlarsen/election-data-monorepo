"""Replay reviewed, checksum-pinned candidate media without performing identity matching."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

CATALOG = Path(__file__).resolve().parent / "catalog/senate_portraits.json"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
LOGGER = logging.getLogger(__name__)
MIME_SUFFIXES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def read_catalog(path: Path = CATALOG) -> dict:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("candidates"), list):
        raise ValueError("Invalid candidate portrait catalog")
    keys = set()
    for row in catalog["candidates"]:
        key = (row["source"], row["year"], row["race_id"], row["name"], row["party"])
        media = row["portrait"]
        digest = media["sha256"]
        suffix = MIME_SUFFIXES.get(media["mime_type"])
        if (key in keys or not isinstance(row["year"], int) or not row["name"].strip()
                or row["race_id"] != f"SEN-{row['state_code']}"
                or not re.fullmatch(r"[A-Z]{2}", row["state_code"])
                or not re.fullmatch(r"[a-f0-9]{64}", digest) or not suffix
                or media["url"] != f"/media/candidates/{digest}.{suffix}"
                or not row.get("match_evidence") or not media["credit"].strip()
                or not media["license"].strip()):
            raise ValueError("Invalid or duplicate candidate portrait assignment")
        for field in ("source", "license_url", "original_url", "download_url"):
            parsed = urlparse(media[field])
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Candidate portrait evidence must use HTTPS")
        if urlparse(media["download_url"]).hostname not in {
            "raw.githubusercontent.com", "upload.wikimedia.org", "thumb.wikimedia.org",
        }:
            raise ValueError("Unsupported candidate portrait download host")
        retrieved = datetime.fromisoformat(media["retrieved_at"].replace("Z", "+00:00"))
        if retrieved.tzinfo is None:
            raise ValueError("Candidate portrait retrieval date must include a timezone")
        keys.add(key)
    return catalog


def validate_image(content: bytes, media: dict) -> None:
    mime = media["mime_type"]
    signature = ((mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
                 or (mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
                 or (mime == "image/webp" and content.startswith(b"RIFF") and content[8:12] == b"WEBP"))
    if not content or len(content) > MAX_IMAGE_BYTES or not signature:
        raise ValueError("Candidate portrait is not a supported raster image")
    if sha256(content).hexdigest() != media["sha256"]:
        raise ValueError("Candidate portrait checksum mismatch")


def fetch_image(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ElectoralAtlas/1.0 (reviewed candidate portraits)"})
    with urlopen(request, timeout=30) as response:
        if response.headers.get_content_type() not in MIME_SUFFIXES:
            raise ValueError("Candidate portrait response is not a raster image")
        return response.read(MAX_IMAGE_BYTES + 1)


def cache_portraits(catalog: dict, destination: Path, *, verify_only: bool = False, fetch=fetch_image) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    report = {"inserted": 0, "updated": 0, "unchanged": 0, "excluded": 0, "rejected": 0, "assets": []}
    # An image can be reviewed for multiple source candidacies or elections.
    assets = {row["portrait"]["url"]: row["portrait"] for row in catalog["candidates"]}
    for media in assets.values():
        path = destination / media["url"].rsplit("/", 1)[-1]
        existed = path.exists()
        try:
            if existed:
                try:
                    validate_image(path.read_bytes(), media)
                    report["unchanged"] += 1
                    report["assets"].append({"url": media["url"], "status": "unchanged"})
                    continue
                except ValueError:
                    if verify_only:
                        raise
            if verify_only:
                raise ValueError("Candidate portrait cache file is missing")
            content = fetch(media["download_url"])
            validate_image(content, media)
            temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_bytes(content)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            status = "updated" if existed else "inserted"
            report[status] += 1
            report["assets"].append({"url": media["url"], "status": status})
        except (OSError, ValueError) as exc:
            report["rejected"] += 1
            report["assets"].append({"url": media["url"], "status": "rejected", "reason": str(exc)})
            LOGGER.error("candidate_portrait_rejected", extra={"asset_url": media["url"], "reason": str(exc)})
    return {**report, "status": "failed" if report["rejected"] else "complete"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--destination", type=Path,
                        default=Path(__file__).resolve().parents[2] / "frontend/public/media/candidates")
    parser.add_argument("--report-dir", type=Path,
                        default=Path(__file__).resolve().parents[2] / "data/candidate-portraits/reports")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    run_id = str(uuid4())
    report = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "ruleset": "reviewed-candidate-portraits-v1"}
    try:
        catalog = read_catalog(args.catalog)
        report.update(catalog_sha256=sha256(args.catalog.read_bytes()).hexdigest(), assignments=len(catalog["candidates"]))
        report.update(cache_portraits(catalog, args.destination, verify_only=args.verify_only))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report.update(status="failed", reason=str(exc))
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / f"{run_id}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "assets"}))
    return int(report["status"] != "complete")


if __name__ == "__main__":
    raise SystemExit(main())
