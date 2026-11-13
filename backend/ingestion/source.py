"""Source acquisition, Dataverse guestbook authorization, and immutable caching.

Only the user-supplied guestbook responses are submitted; no identity values are
invented. Raw files and cached manifests never contain signed URLs or responses.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

LOG = logging.getLogger(__name__)


class AcquisitionError(RuntimeError):
    """An upstream file or metadata could not be acquired safely."""


@dataclass(frozen=True)
class SourceInfo:
    source_name: str
    doi: str
    version: str
    file_id: int
    filename: str
    download_url: str
    expected_size: int | None
    published_at: datetime | None
    metadata: dict[str, Any]
    guestbook_id: int | None = None


@dataclass(frozen=True)
class AcquiredFile:
    info: SourceInfo
    path: Path
    sha256: str
    retrieved_at: datetime


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + f".{uuid4().hex}.tmp")
    try:
        with part.open("w", encoding="utf-8") as f:
            json.dump(payload, f, sort_keys=True, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def _safe_url(url: str) -> str:
    """Never log time-limited signed URL tokens or personal query parameters."""
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _request(
    url: str,
    *,
    destination: Path | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> bytes | None:
    """Transfer data using the stdlib; retry transient failures, not HTTP 4xx.

    If a destination is provided and the server returns JSON (typically a signed
    URL), return that JSON instead of writing an error/success envelope as CSV.
    """
    body = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    headers = {
        "User-Agent": "ElectionDataIngestion/0.2 (research; source attribution)",
        "Accept": "*/*",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if urlsplit(url).hostname == "dataverse.harvard.edu":
        api_token = os.getenv("DATAVERSE_API_TOKEN")
        if api_token:
            headers["X-Dataverse-key"] = api_token

    for attempt in range(3):
        try:
            req = Request(url, headers=headers, data=body, method=method)
            with urlopen(req, timeout=90) as response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if destination is None or content_type == "application/json" or content_type.endswith("+json"):
                    return response.read()
                with destination.open("wb") as handle:
                    while block := response.read(1024 * 1024):
                        handle.write(block)
                    handle.flush()
                    os.fsync(handle.fileno())
                return None
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            status = getattr(exc, "code", None)
            details = ""
            if isinstance(exc, HTTPError):
                raw = exc.read(2048)
                try:
                    decoded = json.loads(raw)
                    message = decoded.get("message") if isinstance(decoded, dict) else None
                    if isinstance(message, dict):
                        message = message.get("message")
                    details = str(message or "")[:500]
                except (UnicodeDecodeError, ValueError):
                    details = raw.decode("utf-8", errors="replace")[:300]
            explanation = f"HTTP {status}: {details}" if status else str(exc)
            if status is not None and status < 500 and status != 429:
                raise AcquisitionError(f"Upstream rejected {_safe_url(url)}: {explanation}") from exc
            if attempt == 2:
                raise AcquisitionError(f"Cannot retrieve {_safe_url(url)}: {explanation}") from exc
            LOG.warning("Request attempt %s failed for %s: %s", attempt + 1, _safe_url(url), explanation)
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


class SourceAdapter(Protocol):
    key: str

    def describe(self) -> SourceInfo: ...


class DataverseMEDSL:
    key = "medsl_presidential_county"
    DOI = "doi:10.7910/DVN/VOQCHQ"
    METADATA_URL = "https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/VOQCHQ"
    HOST = "https://dataverse.harvard.edu"

    def describe(self) -> SourceInfo:
        response = json.loads(_request(self.METADATA_URL) or b"{}")
        if response.get("status") != "OK":
            raise AcquisitionError("Dataverse returned an unsuccessful metadata response")
        dataset = response["data"]
        release = dataset["latestVersion"]
        if release.get("versionState") != "RELEASED":
            raise AcquisitionError("Latest Dataverse version is not released")
        files = [f for f in release["files"]
                 if f.get("dataFile", {}).get("originalFileName") == "countypres_2000-2024.csv"]
        if len(files) != 1:
            raise AcquisitionError(f"Expected exactly one original MEDSL county CSV; found {len(files)}")
        df = files[0]["dataFile"]
        version = f"{release['versionNumber']}.{release['versionMinorNumber']}"
        file_id = int(df["id"])
        published = release.get("releaseTime")
        guestbook_id = dataset.get("guestbookId") or release.get("guestbookId")
        return SourceInfo(
            source_name=self.key,
            doi=self.DOI,
            version=version,
            file_id=file_id,
            filename=df["originalFileName"],
            download_url=f"{self.HOST}/api/access/datafile/{file_id}?format=original",
            expected_size=df.get("originalFileSize"),
            published_at=datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None,
            metadata={
                "dataset_id": dataset["id"],
                "dataset_doi": self.DOI,
                "dataset_unf": release.get("UNF"),
                "dataset_publication_date": dataset.get("publicationDate"),
                "release_time": release.get("releaseTime"),
                "guestbook_id": guestbook_id,
                "file": files[0],
                "license": release.get("license"),
                "citation": f"MIT Election Data and Science Lab, Harvard Dataverse, V{version}, {self.DOI}",
            },
            guestbook_id=int(guestbook_id) if guestbook_id is not None else None,
        )


def _guestbook_response(info: SourceInfo, data_dir: Path) -> dict[str, Any]:
    """Load the user's truthful response and validate against live guestbook fields."""
    assert info.guestbook_id is not None
    guestbook_url = f"https://dataverse.harvard.edu/api/guestbooks/{info.guestbook_id}"
    guestbook_payload = json.loads(_request(guestbook_url) or b"{}")
    guestbook = guestbook_payload.get("data", guestbook_payload)
    if not isinstance(guestbook, dict) or guestbook_payload.get("status") == "ERROR":
        raise AcquisitionError(f"Cannot inspect required guestbook at {guestbook_url}")

    response_path = Path(os.getenv("DATAVERSE_GUESTBOOK_RESPONSE_FILE", str(data_dir / "guestbook_response.json")))
    if not response_path.is_file():
        required = [field for field in ("name", "email", "institution", "position")
                    if guestbook.get(f"{field}Required") is True]
        questions = [
            {"id": q.get("id"), "question": q.get("question")}
            for q in guestbook.get("customQuestions", []) if q.get("required")
        ]
        raise AcquisitionError(
            f"MEDSL requires Dataverse guestbook {info.guestbook_id}. "
            f"Inspect {guestbook_url}; provide your actual answers in {response_path} "
            f"(required fields: {required}; required custom questions: {questions}). "
            "The file must contain a guestbookResponse JSON object."
        )
    try:
        data = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AcquisitionError(f"Cannot parse guestbook response file {response_path}: {exc}") from exc
    response = data.get("guestbookResponse", data) if isinstance(data, dict) else None
    if not isinstance(response, dict):
        raise AcquisitionError("Guestbook response must be a JSON object")

    for field in ("name", "email", "institution", "position"):
        if guestbook.get(f"{field}Required") is True and not response.get(field):
            raise AcquisitionError(f"Guestbook requires an actual value for '{field}'")
    answers = response.get("answers", [])
    if not isinstance(answers, list):
        raise AcquisitionError("Guestbook response 'answers' must be an array")
    filled = {str(a["id"]) for a in answers if isinstance(a, dict) and a.get("id") is not None
              and a.get("value") not in (None, "", [])}
    for question in guestbook.get("customQuestions", []):
        if question.get("required") and str(question.get("id")) not in filled:
            raise AcquisitionError(
                f"Guestbook requires an answer to question ID {question.get('id')}: "
                f"{question.get('question')!r}"
            )
    return {"guestbookResponse": response}


def _download_with_guestbook(info: SourceInfo, destination: Path, data_dir: Path) -> None:
    request_body = _guestbook_response(info, data_dir)
    # POST directly to the numeric file ID; Dataverse returns a temporary signed URL.
    result = _request(info.download_url, method="POST", json_body=request_body, destination=destination)
    if result is None:
        return  # Some Dataverse installations directly stream the original file.
    try:
        response = json.loads(result)
    except (UnicodeDecodeError, ValueError) as exc:
        raise AcquisitionError("Dataverse POST returned an unexpected non-JSON response") from exc
    if not isinstance(response, dict) or response.get("status") == "ERROR":
        message = response.get("message", "unknown error") if isinstance(response, dict) else "bad response"
        raise AcquisitionError(f"Dataverse rejected guestbook response: {message}")
    data = response.get("data", response)
    if isinstance(data, str):
        signed_url = data
    elif isinstance(data, dict):
        signed_url = data.get("signedUrl") or data.get("signedURL") or data.get("url")
    else:
        signed_url = None
    if not isinstance(signed_url, str) or urlsplit(signed_url).scheme != "https":
        raise AcquisitionError(
            "Dataverse accepted the guestbook response but did not return an HTTPS signedUrl; "
            f"response keys: {list(response)}"
        )
    # Signed URLs expire quickly. Always use immediately; never persist or print them.
    downloaded = _request(signed_url, destination=destination)
    if downloaded is not None:
        raise AcquisitionError("Signed download returned JSON rather than the original CSV")


def acquire(adapter: SourceAdapter, data_dir: Path, *, refresh: bool = False) -> AcquiredFile:
    info = adapter.describe()  # Check official release metadata even if cache exists.
    safe_ver = re.sub(r"[^A-Za-z0-9._-]", "_", info.version)
    folder = data_dir / "raw" / adapter.key / safe_ver
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / f"file_{info.file_id}.json"
    if manifest_path.is_file() and not refresh:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        path = folder / manifest["local_filename"]
        if not path.is_file() or sha256_file(path) != manifest["sha256"]:
            raise AcquisitionError(f"Cached file failed SHA-256 verification: {path}; use --refresh")
        if info.expected_size is not None and path.stat().st_size != info.expected_size:
            raise AcquisitionError("Cached original file has unexpected byte length; use --refresh")
        return AcquiredFile(info, path, manifest["sha256"], datetime.fromisoformat(manifest["retrieved_at"]))

    part = folder / f".download-{uuid4().hex}.tmp"
    try:
        if info.guestbook_id is not None:
            _download_with_guestbook(info, part, data_dir)
        else:
            downloaded = _request(info.download_url, destination=part)
            if downloaded is not None:
                raise AcquisitionError("Source returned JSON rather than the original CSV")
        if not part.is_file() or part.stat().st_size == 0:
            raise AcquisitionError("Downloaded source file was empty")
        if info.expected_size is not None and part.stat().st_size != info.expected_size:
            raise AcquisitionError(f"Original file size mismatch: expected {info.expected_size}, got {part.stat().st_size}")
        digest = sha256_file(part)
        path = folder / f"{digest}{Path(info.filename).suffix or '.bin'}"
        if path.exists() and sha256_file(path) != digest:
            if not refresh:
                raise AcquisitionError(f"Existing immutable file is corrupt: {path}")
            quarantine = folder / f"corrupt-{uuid4().hex}.bin"
            LOG.error("Quarantining corrupted cached file %s -> %s", path, quarantine)
            os.replace(path, quarantine)
        os.replace(part, path)  # Content-addressed cache preserves old file versions.
        timestamp = datetime.now(timezone.utc)
        atomic_json(manifest_path, {
            "local_filename": path.name,
            "sha256": digest,
            "download_url": info.download_url,  # Never store signed URLs or guestbook contents.
            "retrieved_at": timestamp.isoformat(),
            "source_metadata": info.metadata,
            "version": info.version,
        })
        return AcquiredFile(info, path, digest, timestamp)
    finally:
        part.unlink(missing_ok=True)
