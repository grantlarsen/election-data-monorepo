"""Transactional PostgreSQL loading; deliberately no ORM row-by-row inserts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterator
from uuid import UUID, uuid4

import polars as pl
from sqlalchemy import Engine, func, select, insert, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.core import DataSource, PoliticalParty
from app.models.ingestion import (ElectionResultObservation, IngestionRejection, IngestionRun,
                                  SourceActiveYear, SourceRelease)
from ingestion.source import AcquiredFile


class DataQualityError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadStats:
    inserted: int = 0
    updated: int = 0
    existing: int = 0
    switched_years: int = 0


def _chunks(items: list[dict[str, Any]], size: int = 500) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def register_run(engine: Engine, run_id: UUID, source_name: str, source_url: str, started_at: Any, options: dict) -> UUID:
    with engine.begin() as conn:
        stmt = pg_insert(DataSource.__table__).values(id=uuid4(), name=source_name, url=source_url)
        conn.execute(stmt.on_conflict_do_nothing(index_elements=["name"]))
        source_id = conn.execute(select(DataSource.id).where(DataSource.name == source_name)).scalar_one()
        conn.execute(insert(IngestionRun.__table__).values(
            id=run_id, source_id=source_id, status="RUNNING", started_at=started_at,
            records_read=0, records_inserted=0, records_updated=0, records_rejected=0,
            warnings_json=[], errors_json=[], options_json=options,
        ))
    return source_id


def finish_failed(engine: Engine, run_id: UUID, *, status: str, completed_at: Any,
                  duration_ms: int, records_read: int, raw_sha256: str | None,
                  warnings: list[dict], errors: list[dict], rejections: list[dict]) -> None:
    # Separate small audit transaction: a failed import does not erase its error report.
    with engine.begin() as conn:
        conn.execute(update(IngestionRun.__table__).where(IngestionRun.id == run_id).values(
            status=status, completed_at=completed_at, duration_ms=duration_ms,
            records_read=records_read, records_rejected=len(rejections),
            warnings_json=warnings, errors_json=errors, raw_sha256=raw_sha256,
        ))
        rows = [{"id": uuid4(), "run_id": run_id, "source_row_number": r["source_row_number"],
                 "reasons_json": r["reasons_json"], "raw_json": r["raw_json"]} for r in rejections]
        for chunk in _chunks(rows):
            conn.execute(insert(IngestionRejection.__table__), chunk)


def preview(engine: Engine, source_name: str, version: str, sha256: str, years: set[int]) -> dict:
    with engine.connect() as conn:
        source_id = conn.execute(select(DataSource.id).where(DataSource.name == source_name)).scalar_one_or_none()
        if source_id is None:
            return {"source_exists": False, "known_release": False, "active_years": []}
        release_id = conn.execute(select(SourceRelease.id).where(SourceRelease.source_id == source_id,
                                  SourceRelease.version == version, SourceRelease.sha256 == sha256)).scalar_one_or_none()
        active = conn.execute(select(SourceActiveYear.year, SourceActiveYear.release_id)
                              .where(SourceActiveYear.source_id == source_id,
                                     SourceActiveYear.year.in_(sorted(years)))).all()
        return {"source_exists": True, "known_release": release_id is not None,
                "already_loaded_rows": int(conn.scalar(select(func.count()).select_from(ElectionResultObservation)
                     .where(ElectionResultObservation.release_id == release_id,
                            ElectionResultObservation.year.in_(sorted(years)))) or 0) if release_id else 0,
                "active_years": [{"year": y, "same_release": r == release_id} for y, r in active]}


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()


def to_records(df: pl.DataFrame, release_id: UUID, party_ids: dict[str, UUID]) -> list[dict]:
    """Polars did all tabular computation; serialization yields mappings for batched SQL."""
    records: list[dict] = []
    for row in df.to_dicts():
        raw = row["raw_json"]
        identity = [row["year_int"], row["state_code"], row["county_fips_normalized"] or row["county_name"],
                    row["candidate"], row["party"], row["mode"]]
        fips = row["county_fips_normalized"]
        per_row_warnings = []
        if fips is None or not fips.startswith(row["state_fips"]):
            per_row_warnings.append("fips_unresolved")
            fips = None  # Never link a mismatched county code to a canonical jurisdiction.
        if row["votes_int"] is None:
            per_row_warnings.append("candidate_votes_unreported")
        records.append({
            "id": uuid4(), "release_id": release_id, "source_row_number": row["source_row_number"],
            "row_sha256": _hash(raw), "logical_key": _hash(identity),
            "year": row["year_int"], "state_raw": row["state"], "state_code_raw": row["state_po"],
            "state_code": row["state_code"], "state_fips": row["state_fips"],
            "county_raw": row["county_name"], "county_normalized": row["county_normalized"],
            "county_fips_raw": row["county_fips"], "county_fips": fips,
            "office_raw": row["office"], "candidate_raw": row["candidate"],
            "candidate_normalized": row["candidate_normalized"] or None, "candidate_kind": row["candidate_kind"],
            "party_raw": row["party"], "party_normalized": row["party_normalized"] or None,
            "mode_raw": row["mode"], "mode_normalized": row["mode_normalized"] or None,
            "version_raw": row["version"], "candidate_votes": row["votes_int"], "total_votes": row["total_int"],
            "party_id": party_ids.get(row["party_normalized"]), "jurisdiction_id": None,
            "candidacy_id": None, "raw_json": raw, "warnings_json": per_row_warnings,
        })
    return records


def load(engine: Engine, source_id: UUID, run_id: UUID, asset: AcquiredFile, df: pl.DataFrame,
         years: set[int], warnings: list[dict], started_at: Any, completed_at: Any,
         duration_ms: int, *, records_read: int | None = None) -> LoadStats:
    release_info = asset.info
    release_id: UUID
    with engine.begin() as conn:
        # A source-level lock serializes imports and active-pointer switching.
        conn.execute(select(DataSource.id).where(DataSource.id == source_id).with_for_update()).scalar_one()
        stmt = pg_insert(SourceRelease.__table__).values(
            id=uuid4(), source_id=source_id, version=release_info.version, sha256=asset.sha256,
            filename=release_info.filename, file_id=release_info.file_id,
            download_url=release_info.download_url, raw_path=str(asset.path),
            retrieved_at=asset.retrieved_at, published_at=release_info.published_at,
            metadata_json=release_info.metadata,
        ).on_conflict_do_nothing(index_elements=["source_id", "version", "sha256"])
        conn.execute(stmt)
        release_id = conn.execute(select(SourceRelease.id).where(
            SourceRelease.source_id == source_id, SourceRelease.version == release_info.version,
            SourceRelease.sha256 == asset.sha256)).scalar_one()

        active = dict(conn.execute(select(SourceActiveYear.year, SourceActiveYear.release_id)
                        .where(SourceActiveYear.source_id == source_id, SourceActiveYear.year.in_(sorted(years)))).all())
        previous_counts = dict(conn.execute(
            select(ElectionResultObservation.year, func.count()).join(
                SourceActiveYear, (SourceActiveYear.release_id == ElectionResultObservation.release_id) &
                (SourceActiveYear.year == ElectionResultObservation.year))
            .where(SourceActiveYear.source_id == source_id, SourceActiveYear.year.in_(sorted(years)))
            .group_by(ElectionResultObservation.year)).all())
        new_counts = dict(df.group_by("year_int").agg(pl.len().alias("n")).select("year_int", "n").iter_rows())
        for year, new in new_counts.items():
            old = int(previous_counts.get(year, 0))
            if old and active.get(year) != release_id:
                drift = abs(new - old) / old
                if drift > 0.2:
                    raise DataQualityError(f"Year {year}: {drift:.1%} row-count change from active release exceeds 20% safety threshold")
                if drift > 0.05:
                    warnings.append({"code":"ROW_COUNT_CHANGE", "severity":"WARNING", "count":1,
                                     "description":f"Year {year}: {old} active rows -> {new} rows ({drift:.1%} change)", "sample_rows":[]})

        party_ids = dict(conn.execute(select(PoliticalParty.name, PoliticalParty.id)).all())
        # Serialize/inject only one chunk at a time to avoid duplicating a full
        # multi-year Polars DataFrame into a second list of Python dictionaries.
        inserted = 0
        for offset in range(0, df.height, 500):
            chunk = to_records(df.slice(offset, 500), release_id, party_ids)
            stmt = pg_insert(ElectionResultObservation.__table__).values(chunk)
            inserted += conn.execute(stmt.on_conflict_do_nothing(
                index_elements=["release_id", "source_row_number"])).rowcount
        loaded_count = int(conn.scalar(select(func.count()).select_from(ElectionResultObservation).where(
            ElectionResultObservation.release_id == release_id,
            ElectionResultObservation.year.in_(sorted(years)))) or 0)
        if loaded_count != df.height:
            raise DataQualityError(f"Expected {df.height} rows in release/year scope, found {loaded_count}; transaction rolled back")

        changed_years = [year for year in years if active.get(year) != release_id]
        updated = sum(int(new_counts.get(y, 0)) for y in changed_years if y in active)
        for year in sorted(years):
            stmt = pg_insert(SourceActiveYear.__table__).values(
                source_id=source_id, year=year, release_id=release_id, run_id=run_id,
            ).on_conflict_do_update(index_elements=["source_id", "year"], set_={
                "release_id": release_id, "run_id": run_id, "applied_at": func.now(),
            })
            conn.execute(stmt)
        finished_at = datetime.now(timezone.utc)
        elapsed_ms = int((finished_at - started_at).total_seconds() * 1000)
        conn.execute(update(IngestionRun.__table__).where(IngestionRun.id == run_id).values(
            release_id=release_id, status="SUCCEEDED", records_read=records_read if records_read is not None else df.height,
            records_inserted=inserted, records_updated=updated, records_rejected=0,
            warnings_json=warnings, errors_json=[], raw_sha256=asset.sha256,
            completed_at=finished_at, duration_ms=elapsed_ms,
        ))
    return LoadStats(inserted=inserted, updated=updated, existing=df.height - inserted,
                     switched_years=len(changed_years))
