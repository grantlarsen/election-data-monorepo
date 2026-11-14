"""Atomic, idempotent Census geographic reference loads using Step 5 audit tables."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import polars as pl
from sqlalchemy import Engine, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.core import DataSource, Jurisdiction
from app.models.geography import (GeographicReference, JurisdictionIdentifier,
                                  JurisdictionRelationship)
from app.models.ingestion import IngestionRun, SourceRelease
from ingestion.medsl import STATE_FIPS, STATE_NAMES
from ingestion.source import AcquiredFile
from ingestion.loader import _chunks

STATE_BY_FIPS = {v: k for k, v in STATE_FIPS.items()}
JURISDICTION_NS = uuid5(NAMESPACE_URL, "electoral-platform:us-jurisdiction:v1")
REFERENCE_NS = uuid5(NAMESPACE_URL, "electoral-platform:geographic-reference:v1")


def stable_jurisdiction_id(kind: str, geoid: str, name_key: str) -> UUID:
    # A code/name change deliberately creates a reviewable distinct identity;
    # it cannot silently merge separate legal entities via recycled FIPS numbers.
    return uuid5(JURISDICTION_NS, f"{kind}:{geoid}:{name_key if kind == 'county' else ''}")


def load_reference(engine: Engine, source_id: UUID, run_id: UUID,
                   asset: AcquiredFile, frame: pl.DataFrame, summary: dict,
                   started_at: datetime | None = None) -> dict:
    a, b = asset.info.metadata["vintage_start"], asset.info.metadata["vintage_end"]
    county_rows = frame.filter(~pl.col("county_code").is_in(["000", "999"]))
    county_rows = county_rows.filter(pl.col("state_fips").is_in(list(STATE_BY_FIPS)))
    # Polars is the only DataFrame engine; Python mappings are used for batched SQL commands.
    county_records = county_rows.to_dicts()
    # Some historical files represent DC as 11999 (aggregate only). Still load the DC state.
    states = sorted(frame.filter(pl.col("state_fips").is_in(list(STATE_BY_FIPS)))
                    .get_column("state_fips").unique().to_list())
    count = 0
    with engine.begin() as conn:
        conn.execute(select(DataSource.id).where(DataSource.id == source_id).with_for_update()).scalar_one()
        rel = (pg_insert(SourceRelease.__table__).values(
            id=uuid4(), source_id=source_id, version=asset.info.version,
            sha256=asset.sha256, filename=asset.info.filename,
            file_id=asset.info.file_id, download_url=asset.info.download_url,
            raw_path=str(asset.path), retrieved_at=asset.retrieved_at,
            published_at=asset.info.published_at, metadata_json=asset.info.metadata,
        ).on_conflict_do_nothing(index_elements=["source_id", "version", "sha256"]))
        conn.execute(rel)
        release_id = conn.execute(select(SourceRelease.id).where(
            SourceRelease.source_id == source_id,
            SourceRelease.version == asset.info.version,
            SourceRelease.sha256 == asset.sha256)).scalar_one()

        state_jids = {fips: stable_jurisdiction_id("state", fips, "") for fips in states}
        jurisdiction_rows = [{"id": state_jids[fips], "name": STATE_NAMES[STATE_BY_FIPS[fips]].title(),
                              "level": "state", "state_code": STATE_BY_FIPS[fips]}
                             for fips in states]
        # States are introduced first, with counties following. Existing canonical rows are never rewritten.
        for chunk in _chunks(jurisdiction_rows):
            conn.execute(pg_insert(Jurisdiction.__table__).values(chunk).on_conflict_do_nothing(index_elements=["id"]))
        county_jids = {(r["geoid"], r["name_key"]):
                       stable_jurisdiction_id("county", r["geoid"], r["name_key"])
                       for r in county_records}
        county_entities = [{"id": county_jids[(r["geoid"], r["name_key"])],
                            "name": r["county_name_raw"].split(",", 1)[0].strip(),
                            "level": "county", "state_code": STATE_BY_FIPS[r["state_fips"]]}
                           for r in county_records]
        for chunk in _chunks(county_entities):
            conn.execute(pg_insert(Jurisdiction.__table__).values(chunk).on_conflict_do_nothing(index_elements=["id"]))

        ref_rows = [{"id": uuid5(REFERENCE_NS, f"{release_id}:state:{fips}"),
                     "release_id": release_id, "jurisdiction_id": state_jids[fips],
                     "kind": "state", "geoid": fips, "state_fips": fips,
                     "name_raw": STATE_NAMES[STATE_BY_FIPS[fips]].title(),
                     "name_key": STATE_NAMES[STATE_BY_FIPS[fips]],
                     "vintage_start": a, "vintage_end": b,
                     "source_row_number": None,
                     "note": "State FIPS verified in source; display name from local static state list"}
                    for fips in states]
        ref_rows += [{"id": uuid5(REFERENCE_NS, f"{release_id}:county:{r['geoid']}"),
                      "release_id": release_id, "jurisdiction_id": county_jids[(r["geoid"], r["name_key"])],
                      "kind": "county", "geoid": r["geoid"], "state_fips": r["state_fips"],
                      "name_raw": r["county_name_raw"], "name_key": r["name_key"],
                      "vintage_start": a, "vintage_end": b,
                      "source_row_number": r["source_row_number"],
                      "note": "Product reference coverage only; legal validity not established"}
                     for r in county_records]
        for chunk in _chunks(ref_rows):
            stmt = pg_insert(GeographicReference.__table__).values(chunk).on_conflict_do_nothing(
                index_elements=["release_id", "kind", "geoid"]).returning(GeographicReference.id)
            count += len(conn.execute(stmt).all())
        id_rows = [{"id": uuid5(REFERENCE_NS, f"identifier:{r['id']}"),
                    "jurisdiction_id": r["jurisdiction_id"], "reference_id": r["id"],
                    "scheme": "FIPS_STATE" if r["kind"] == "state" else "FIPS_COUNTY",
                    "value": r["geoid"], "valid_from": None, "valid_until": None}
                   for r in ref_rows]
        for chunk in _chunks(id_rows):
            conn.execute(pg_insert(JurisdictionIdentifier.__table__).values(chunk).on_conflict_do_nothing(
                index_elements=["reference_id", "scheme"]))
        relationship_rows = [
            {"id": uuid5(REFERENCE_NS, f"relationship:{r['id']}"),
             "parent_id": state_jids[r["state_fips"]], "child_id": r["jurisdiction_id"],
             "reference_id": r["id"], "relationship": "contains"}
            for r in ref_rows if r["kind"] == "county"
        ]
        for chunk in _chunks(relationship_rows):
            conn.execute(pg_insert(JurisdictionRelationship.__table__).values(chunk).on_conflict_do_nothing(
                index_elements=["reference_id"]))
        now = datetime.now(timezone.utc)
        elapsed = int((now - (started_at or now)).total_seconds() * 1000)
        conn.execute(update(IngestionRun.__table__).where(IngestionRun.id == run_id).values(
            release_id=release_id, status="SUCCEEDED", records_read=frame.height,
            records_inserted=count, records_updated=0, records_rejected=0,
            warnings_json=[{"code": "STATISTICAL_VINTAGE_NOT_LEGAL_DATES", "severity": "WARNING",
                            "description": "Do not infer legal effective dates from multi-year CBP/NES ranges"}],
            errors_json=[], raw_sha256=asset.sha256, completed_at=now,
            duration_ms=max(0, elapsed),
        ))
    return {"release_id": str(release_id), "records_inserted": count,
            "records_already_present": len(ref_rows) - count, "state_rows": len(states),
            "county_rows": len(county_records), **summary}
