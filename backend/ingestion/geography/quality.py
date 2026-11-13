"""Geographic quality checks and audits; no writes to MEDSL observations."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import polars as pl
from sqlalchemy import Engine, and_, select
from sqlalchemy.orm import Session

from app.models.core import DataSource
from app.models.geography import (GeographicReference, GeographicResolution,
                                  JurisdictionIdentifier, JurisdictionRelationship)
from app.models.ingestion import ElectionResultObservation, SourceActiveYear
from ingestion.adapters.census_state_county_georef import name_key
from ingestion.medsl import STATE_FIPS
from ingestion.source import atomic_json


def validate_loaded_reference(engine: Engine, release_id: UUID) -> dict:
    # ORM Session is required: Core Connection.execute(select(Model)).scalars()
    # yields the *first column* (UUID), not mapped Model instances.
    with Session(engine) as session:
        refs = session.scalars(select(GeographicReference).where(
            GeographicReference.release_id == release_id)).all()
        identifiers = session.scalars(select(JurisdictionIdentifier).join(
            GeographicReference, JurisdictionIdentifier.reference_id == GeographicReference.id
        ).where(GeographicReference.release_id == release_id)).all()
        relations = session.scalars(select(JurisdictionRelationship).join(
            GeographicReference, JurisdictionRelationship.reference_id == GeographicReference.id
        ).where(GeographicReference.release_id == release_id)).all()
    state_ids = {r.state_fips: r.jurisdiction_id for r in refs if r.kind == "state"}
    errors = []
    codes = set()
    for r in refs:
        if (r.kind, r.geoid) in codes:
            errors.append({"code": "DUPLICATE_GEOID", "geoid": r.geoid})
        codes.add((r.kind, r.geoid))
        if r.kind == "state" and (len(r.geoid) != 2 or r.geoid != r.state_fips):
            errors.append({"code": "INVALID_STATE_FIPS", "geoid": r.geoid})
        if r.kind == "county" and (len(r.geoid) != 5 or not r.geoid.isdecimal() or
                                    r.geoid[:2] != r.state_fips or r.geoid[-3:] == "999"):
            errors.append({"code": "INVALID_COUNTY_GEOID", "geoid": r.geoid})
        if r.kind == "county" and r.state_fips not in state_ids:
            errors.append({"code": "MISSING_PARENT_STATE", "geoid": r.geoid})
    ids = {i.reference_id: i for i in identifiers}
    rels = {r.reference_id: r for r in relations}
    for r in refs:
        i = ids.get(r.id)
        if (i is None or i.value != r.geoid or i.jurisdiction_id != r.jurisdiction_id or
            i.scheme != ("FIPS_COUNTY" if r.kind == "county" else "FIPS_STATE")):
            errors.append({"code": "INVALID_IDENTIFIER", "geoid": r.geoid})
        if r.kind == "county":
            rel = rels.get(r.id)
            if (rel is None or rel.parent_id != state_ids.get(r.state_fips) or
                rel.child_id != r.jurisdiction_id or rel.parent_id == rel.child_id):
                errors.append({"code": "INVALID_HIERARCHY", "geoid": r.geoid})
    if len(state_ids) != 51:
        errors.append({"code": "INCOMPLETE_STATES", "actual": len(state_ids), "expected": 51})
    return {"release_id": str(release_id), "state_count": len(state_ids),
            "county_count": len(refs) - len(state_ids), "identifier_count": len(identifiers),
            "hierarchy_count": len(relations), "errors": errors, "ok": not errors,
            "limitations": ["Product ranges do not verify legal effective dates",
                            "No boundary geometry loaded",
                            "Name/code-change identity continuity requires human review"]}


def unresolved_rows(engine: Engine, release_id: UUID) -> list[dict]:
    with engine.connect() as conn:
        r, o = GeographicResolution, ElectionResultObservation
        rows = conn.execute(select(
            o.source_row_number, o.year, o.state_code, o.county_raw, o.county_fips_raw,
            o.county_fips, r.status, r.method, r.reason, r.observation_id
        ).join(o, o.id == r.observation_id).where(
            r.reference_release_id == release_id,
            ~r.status.in_(["RESOLVED", "RESOLVED_HISTORICAL"])
        ).order_by(o.year, o.state_code, o.source_row_number)).mappings().all()
    return [{k: str(v) if k == "observation_id" else v for k, v in row.items()}
            for row in rows]


def active_medsl_anomalies(engine: Engine) -> dict:
    """Detailed membership of grouped warnings; counts are groups vs observations, not additive."""
    with engine.connect() as conn:
        o = ElectionResultObservation
        rows = conn.execute(select(o.id, o.source_row_number, o.year, o.state_code,
                                   o.state_fips, o.county_raw, o.county_fips_raw, o.county_fips)
                            .join(SourceActiveYear, and_(o.release_id == SourceActiveYear.release_id,
                                                          o.year == SourceActiveYear.year))
                            .join(DataSource, DataSource.id == SourceActiveYear.source_id)
                            .where(DataSource.name == "medsl_presidential_county")).mappings().all()
    records = [dict(r) for r in rows]
    by_name: dict[tuple, set] = defaultdict(set)
    by_code: dict[tuple, set] = defaultdict(set)
    for r in records:
        fips = r["county_fips"]
        if fips:
            by_name[(r["state_code"], r["county_raw"])].add(fips)
            by_code[(r["state_code"], fips)].add(r["county_raw"])
    code_changes = {key for key, values in by_name.items() if len(values) > 1}
    label_changes = {key for key, values in by_code.items() if len(values) > 1}
    detail = []
    counts = Counter()
    for r in records:
        codes = []
        raw = (r["county_fips_raw"] or "").strip()
        raw_parsed = raw.zfill(5) if raw.isascii() and raw.isdecimal() and len(raw) <= 5 else None
        if raw_parsed is None:
            codes.append("FIPS_UNRESOLVED")
        elif raw_parsed[:2] != r["state_fips"]:
            codes.append("FIPS_STATE_MISMATCH")
        if r["county_fips"] and (r["state_code"], r["county_raw"]) in code_changes:
            codes.append("COUNTY_CODE_CHANGED")
        if r["county_fips"] and (r["state_code"], r["county_fips"]) in label_changes:
            codes.append("COUNTY_LABEL_CHANGED")
        for code in codes:
            counts[code] += 1
            detail.append({"code": code, "observation_id": str(r["id"]),
                           "source_row_number": r["source_row_number"],
                           "year": r["year"], "state": r["state_code"],
                           "county_raw": r["county_raw"],
                           "fips_raw": r["county_fips_raw"], "fips_normalized": r["county_fips"]})
    return {"active_observations": len(records), "warning_observation_membership_counts": dict(counts),
            "warning_group_counts": {"COUNTY_CODE_CHANGED": len(code_changes),
                                     "COUNTY_LABEL_CHANGED": len(label_changes)},
            "detail": detail}


def save_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("No records\n", encoding="utf-8")
    else:
        pl.DataFrame(rows).write_csv(path)


def reference_changes(engine: Engine) -> dict:
    """Diff code/name evidence across Census releases, never infer continuity automatically."""
    from collections import defaultdict
    with engine.connect() as conn:
        rows = conn.execute(select(
            GeographicReference.geoid, GeographicReference.state_fips,
            GeographicReference.name_raw, GeographicReference.name_key,
            GeographicReference.vintage_start, GeographicReference.vintage_end,
            GeographicReference.jurisdiction_id, GeographicReference.release_id,
        ).where(GeographicReference.kind == "county").order_by(
            GeographicReference.vintage_start, GeographicReference.geoid)).mappings().all()
    by_code: dict[str, list] = defaultdict(list)
    by_name: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        item = dict(row)
        for field in ("jurisdiction_id", "release_id"):
            item[field] = str(item[field])
        by_code[item["geoid"]].append(item)
        by_name[(item["state_fips"], item["name_key"])].append(item)
    changed_name = [{"type": "NAME_VARIATION_SAME_GEOID", "geoid": k, "evidence": v}
                    for k, v in by_code.items() if len({a["name_key"] for a in v}) > 1]
    changed_code = [{"type": "CODE_VARIATION_SAME_LABEL", "state_fips": k[0],
                     "name_key": k[1], "evidence": v}
                    for k, v in by_name.items() if len({a["geoid"] for a in v}) > 1]
    return {"reference_count": len(rows), "geoid_name_change_groups": len(changed_name),
            "name_geoid_change_groups": len(changed_code),
            "limitations": "These are comparison candidates, not confirmed legal successions.",
            "changes": changed_name + changed_code}
