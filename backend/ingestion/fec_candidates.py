"""Offline replay of checksum-pinned FEC candidate master and all-candidates files.

No latest-release fetches: callers supply the original ZIP, its SHA-256 and retrieval
timestamp. All transformations use Polars; source strings remain in raw_json.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import shutil
from uuid import uuid4
from zipfile import ZipFile

import polars as pl
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.candidate_identity import CandidateFinanceSummary, FecCandidateRecord
from app.models.identity import ExternalIdentifier
from app.models.ingestion import IngestionRun, SourceRelease
from ingestion.loader import finish_failed, register_run
from ingestion.medsl import STATE_NAMES
from ingestion.source import sha256_file

MASTER = "CAND_ID CAND_NAME CAND_PTY_AFFILIATION CAND_ELECTION_YR CAND_OFFICE_ST CAND_OFFICE CAND_OFFICE_DISTRICT CAND_ICI CAND_STATUS CAND_PCC CAND_ST1 CAND_ST2 CAND_CITY CAND_ST CAND_ZIP".split()
SUMMARY = "CAND_ID CAND_NAME CAND_ICI PTY_CD CAND_PTY_AFFILIATION TTL_RECEIPTS TRANS_FROM_AUTH TTL_DISB TRANS_TO_AUTH COH_BOP COH_COP CAND_CONTRIB CAND_LOANS OTHER_LOANS CAND_LOAN_REPAY OTHER_LOAN_REPAY DEBTS_OWED_BY TTL_INDIV_CONTRIB CAND_OFFICE_ST CAND_OFFICE_DISTRICT SPEC_ELECTION PRIM_ELECTION RUN_ELECTION GEN_ELECTION GEN_ELECTION_PRECENT OTHER_POL_CMTE_CONTRIB POL_PTY_CONTRIB CVG_END_DT INDIV_REFUNDS CMTE_REFUNDS".split()
CANDIDATE_ID = re.compile(r"^[HSP][0-9A-Z]{8}$")
COMMITTEE_ID = re.compile(r"^C[0-9]{8}$")


class FecValidationError(ValueError):
    def __init__(self, message: str, records_read: int, rejections: list[dict]):
        super().__init__(message)
        self.records_read = records_read
        self.rejections = rejections


def money(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Malformed FEC monetary amount") from exc
    if not amount.is_finite() or abs(amount) >= Decimal("1e16") or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Invalid precision or range in FEC monetary amount")
    return amount


def parse(path: Path, kind: str, *, cycle: int | None = None) -> list[dict]:
    if kind not in {"master", "summary"}:
        raise ValueError("Unsupported FEC file kind")
    if cycle is not None and (cycle < 1788 or cycle > 9998 or cycle % 2):
        raise ValueError("FEC cycle must be an even year")
    columns = MASTER if kind == "master" else SUMMARY
    with ZipFile(path) as archive:
        pattern = r"cn\.txt" if kind == "master" else r"weball(?:\d{2})?\.txt"
        members = [name for name in archive.namelist() if re.fullmatch(pattern, name)]
        if len(members) != 1:
            raise ValueError("ZIP must contain exactly one candidate data member")
        member = members[0]
        if kind == "summary" and cycle is not None and member != "weball.txt" and member != f"weball{cycle % 100:02}.txt":
            raise ValueError("Summary ZIP member does not match the requested cycle")
        data = archive.read(member)
    frame = pl.read_csv(data, separator="|", has_header=False, new_columns=columns,
                        infer_schema=False, quote_char=None, encoding="utf8")
    if frame.width != len(columns) or frame.is_empty():
        raise ValueError("Unexpected or empty FEC schema")
    original_rows = frame.to_dicts()
    frame = frame.with_columns(pl.all().str.strip_chars())
    duplicates = set(frame.filter(pl.col("CAND_ID").is_duplicated())["CAND_ID"].to_list())
    rows = frame.to_dicts()
    rejections = []
    for ordinal, (row, original) in enumerate(zip(rows, original_rows, strict=True), 1):
        row["_raw"] = original
        try:
            if row["CAND_ID"] in duplicates:
                raise ValueError("Duplicate FEC candidate IDs in release")
            if not CANDIDATE_ID.fullmatch(row["CAND_ID"] or ""):
                raise ValueError("Invalid FEC candidate ID")
            if kind == "master":
                if (not row["CAND_NAME"] or row["CAND_OFFICE"] not in {"H", "S", "P"}
                        or not re.fullmatch(r"\d{4}", row["CAND_ELECTION_YR"] or "")
                        or not 1788 <= int(row["CAND_ELECTION_YR"]) <= 9998
                        or row["CAND_OFFICE_ST"] not in (set(STATE_NAMES) | {"US", "AS", "GU", "MP", "PR", "VI"})
                        or (row["CAND_OFFICE_DISTRICT"] and not re.fullmatch(r"\d{1,2}", row["CAND_OFFICE_DISTRICT"]))):
                    raise ValueError("Invalid FEC candidate scope or name")
                if row["CAND_PCC"] and not COMMITTEE_ID.fullmatch(row["CAND_PCC"]):
                    raise ValueError("Invalid principal committee ID")
            else:
                for field in ("TTL_RECEIPTS", "TTL_DISB", "TRANS_FROM_AUTH", "TRANS_TO_AUTH", "COH_COP", "DEBTS_OWED_BY"):
                    money(row[field])
                if row["CVG_END_DT"]:
                    datetime.strptime(row["CVG_END_DT"], "%m/%d/%Y")
        except ValueError as exc:
            rejections.append(dict(source_row_number=ordinal, reasons_json=[str(exc)], raw_json=original))
    if rejections:
        raise FecValidationError(rejections[0]["reasons_json"][0], len(rows), rejections)
    return rows


def load(engine: Engine, *, path: Path, kind: str, cycle: int, sha256: str,
         retrieved_at: datetime, data_dir: Path) -> dict:
    if cycle < 1788 or cycle > 9998 or cycle % 2:
        raise ValueError("FEC cycle must be an even year")
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must include timezone")
    if not re.fullmatch(r"[a-f0-9]{64}", sha256) or sha256_file(path) != sha256:
        raise ValueError("Pinned SHA-256 does not match input")
    started = datetime.now(timezone.utc)
    run_id = uuid4()
    source_name = "fec_candidate_master" if kind == "master" else "fec_candidate_summary"
    filename = f"cn{cycle % 100:02}.zip" if kind == "master" else f"weball{cycle % 100:02}.zip"
    url = f"https://www.fec.gov/files/bulk-downloads/{cycle}/{filename}"
    source_id = register_run(engine, run_id, source_name, url, started,
                             {"kind": kind, "cycle": cycle, "sha256": sha256,
                              "retrieved_at": retrieved_at.isoformat(), "input_path": str(path.resolve())})
    rows: list[dict] = []
    try:
        rows = parse(path, kind, cycle=cycle)
        destination = data_dir / "raw" / source_name / str(cycle) / f"{sha256}.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and sha256_file(destination) != sha256:
            raise ValueError("Immutable FEC cache is corrupt")
        if not destination.exists():
            with path.open("rb") as original, destination.open("xb") as cached:
                shutil.copyfileobj(original, cached)
        if sha256_file(destination) != sha256:
            raise ValueError("Input changed while caching")
        with Session(engine) as session, session.begin():
            session.execute(insert(SourceRelease).values(id=uuid4(), source_id=source_id,
                version=str(cycle), sha256=sha256, filename=filename, file_id=0,
                download_url=url, raw_path=str(destination.resolve()), retrieved_at=retrieved_at,
                metadata_json={"kind": kind, "cycle": cycle, "format": "FEC pipe-delimited ZIP"})
                .on_conflict_do_nothing(index_elements=["source_id", "version", "sha256"]))
            release = session.scalar(select(SourceRelease).where(SourceRelease.source_id == source_id,
                SourceRelease.version == str(cycle), SourceRelease.sha256 == sha256))
            identifiers = [dict(id=uuid4(), namespace="fec", identifier_type="candidate", value=r["CAND_ID"],
                source_id=source_id, release_id=release.id, source_record_key=r["CAND_ID"], label_raw=r["CAND_NAME"]) for r in rows]
            for start in range(0, len(rows), 500):
                session.execute(insert(ExternalIdentifier).values(identifiers[start:start + 500])
                    .on_conflict_do_nothing(index_elements=["namespace", "identifier_type", "value"]))
            ids = dict(session.execute(select(ExternalIdentifier.value, ExternalIdentifier.id).where(
                ExternalIdentifier.namespace == "fec", ExternalIdentifier.identifier_type == "candidate")).all())
            model = FecCandidateRecord if kind == "master" else CandidateFinanceSummary
            values = []
            for row in rows:
                item = dict(id=uuid4(), release_id=release.id, identifier_id=ids[row["CAND_ID"]], cycle=cycle, raw_json=row["_raw"])
                if kind == "master":
                    item.update(election_year=int(row["CAND_ELECTION_YR"]), name=row["CAND_NAME"],
                        office=row["CAND_OFFICE"], state_code=row["CAND_OFFICE_ST"],
                        district=row["CAND_OFFICE_DISTRICT"].zfill(2) if row["CAND_OFFICE_DISTRICT"] else "00" if row["CAND_OFFICE"] in {"P", "S"} else None,
                        principal_committee=row["CAND_PCC"] or None)
                else:
                    item.update(coverage_end=datetime.strptime(row["CVG_END_DT"], "%m/%d/%Y").date() if row["CVG_END_DT"] else None,
                        receipts=money(row["TTL_RECEIPTS"]), disbursements=money(row["TTL_DISB"]),
                        transfers_from_authorized=money(row["TRANS_FROM_AUTH"]), transfers_to_authorized=money(row["TRANS_TO_AUTH"]),
                        cash_on_hand=money(row["COH_COP"]), debts=money(row["DEBTS_OWED_BY"]))
                values.append(item)
            inserted = 0
            for start in range(0, len(values), 500):
                inserted += len(session.execute(insert(model).values(values[start:start + 500])
                    .on_conflict_do_nothing().returning(model.id)).all())
            run = session.get(IngestionRun, run_id)
            run.release_id, run.status = release.id, "SUCCESS"
            run.records_read, run.records_inserted = len(rows), inserted
            run.raw_sha256, run.completed_at = sha256, datetime.now(timezone.utc)
            run.duration_ms = int((run.completed_at - started).total_seconds() * 1000)
            run.options_json = {**run.options_json, "unchanged": len(rows) - inserted, "excluded": 0}
            if kind == "master":
                missing = sum(not row["CAND_OFFICE_DISTRICT"] and row["CAND_OFFICE"] == "H" for row in rows)
                run.warnings_json = [{"code": "MISSING_HOUSE_DISTRICT", "count": missing,
                    "action": "Retained with null district; ineligible for scope matching"}] if missing else []
                conflicts = sum(row["CAND_ID"][0] != row["CAND_OFFICE"] for row in rows)
                if conflicts:
                    run.warnings_json = [*run.warnings_json, {"code": "ID_OFFICE_CONFLICT", "count": conflicts,
                        "action": "Retained conflicting source fields; ineligible for scope matching"}]
            return dict(release_id=str(release.id), read=len(rows), inserted=inserted,
                        updated=0, unchanged=len(rows) - inserted, excluded=0, rejected=0)
    except Exception as exc:
        finish_failed(engine, run_id, status="FAILED", completed_at=datetime.now(timezone.utc),
            duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            records_read=exc.records_read if isinstance(exc, FecValidationError) else len(rows), raw_sha256=sha256, warnings=[],
            errors=[{"type": type(exc).__name__, "message": str(exc)}],
            rejections=exc.rejections if isinstance(exc, FecValidationError) else [])
        raise
