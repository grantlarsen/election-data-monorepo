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
    is_substate_release = bool(refs) and all(r.kind in {"place", "congressional_district"} for r in refs)
    errors = []
    codes = set()
    for r in refs:
        if (r.kind, r.geoid) in codes:
            errors.append({"code": "DUPLICATE_GEOID", "geoid": r.geoid})
        codes.add((r.kind, r.geoid))
        if r.kind == "state" and (len(r.geoid) != 2 or r.geoid != r.state_fips):
            errors.append({"code": "INVALID_STATE_FIPS", "geoid": r.geoid})
        if r.kind == "county" and (len(r.geoid) != 5 or not r.geoid.isascii() or
                                    not r.geoid.isdecimal() or r.geoid[:2] != r.state_fips or
                                    r.geoid[-3:] in {"000", "999"}):
            errors.append({"code": "INVALID_COUNTY_GEOID", "geoid": r.geoid})
        if r.kind == "place" and (len(r.geoid)!=7 or not r.geoid.isascii() or
                                   not r.geoid.isdecimal() or r.geoid[:2]!=r.state_fips):
            errors.append({"code":"INVALID_PLACE_GEOID","geoid":r.geoid})
        if r.kind == "congressional_district" and (len(r.geoid)!=4 or not r.geoid.isascii()
                or not r.geoid.isdecimal() or r.geoid[:2]!=r.state_fips):
            errors.append({"code":"INVALID_CONGRESSIONAL_DISTRICT_GEOID","geoid":r.geoid})
        if r.kind == "county" and r.state_fips not in state_ids:
            errors.append({"code": "MISSING_PARENT_STATE", "geoid": r.geoid})
    ids = {i.reference_id: i for i in identifiers}
    rels = {r.reference_id: r for r in relations}
    for r in refs:
        i = ids.get(r.id)
        if (i is None or i.value != r.geoid or i.jurisdiction_id != r.jurisdiction_id or
            i.scheme != ({"county":"FIPS_COUNTY","state":"FIPS_STATE",
                          "place":"CENSUS_PLACE_GEOID", "congressional_district":"CENSUS_CD_GEOID"}[r.kind])):
            errors.append({"code": "INVALID_IDENTIFIER", "geoid": r.geoid})
        if r.kind in {"county", "place", "congressional_district"}:
            rel = rels.get(r.id)
            from ingestion.geography.load import stable_jurisdiction_id
            expected_parent = (stable_jurisdiction_id("state",r.state_fips, "")
                               if is_substate_release else state_ids.get(r.state_fips))
            if (rel is None or rel.parent_id != expected_parent or
                rel.child_id != r.jurisdiction_id or rel.parent_id == rel.child_id):
                errors.append({"code": "INVALID_HIERARCHY", "geoid": r.geoid})
    if not is_substate_release and len(state_ids) != 51:
        errors.append({"code": "INCOMPLETE_STATES", "actual": len(state_ids), "expected": 51})
    coverage_gaps = []
    if refs and not is_substate_release and min(r.vintage_start for r in refs) <= 2000:
        known={r.geoid for r in refs if r.kind=="county"}
        for fips,why in [("11001","District of Columbia county-equivalent"),
                         ("12086","Miami-Dade 2000 county")]:
            if fips not in known:
                coverage_gaps.append({"geoid":fips,"reason":why,
                  "action":"Supplement from contemporaneous Census 2000 evidence; do not fabricate rows"})
    return {"release_id": str(release_id), "state_count": len(state_ids),
            "county_count": len([r for r in refs if r.kind=="county"]),
            "place_count": len([r for r in refs if r.kind=="place"]),
            "congressional_district_count": len([r for r in refs if r.kind=="congressional_district"]),
            "known_reference_coverage_gaps":coverage_gaps, "identifier_count": len(identifiers),
            "hierarchy_count": len(relations), "errors": errors, "ok": not errors,
            "limitations": ["Product ranges do not verify legal effective dates",
                            "No boundary geometry loaded",
                            "Name/code-change identity continuity requires human review"]}


def unresolved_rows(engine: Engine, release_id: UUID) -> list[dict]:
    with engine.connect() as conn:
        r, o = GeographicResolution, ElectionResultObservation
        child=r.__table__.alias("superseding")
        rows = conn.execute(select(
            o.source_row_number, o.year, o.state_code, o.county_raw, o.county_fips_raw,
            o.county_fips, r.status, r.method, r.reason, r.observation_id
        ).join(o, o.id == r.observation_id).where(
            r.reference_release_id == release_id,
            ~r.status.in_(["RESOLVED", "RESOLVED_HISTORICAL", "RESOLVED_ALIAS", "NON_COUNTY_CLASSIFIED"]),
            ~select(child.c.id).where(child.c.supersedes_id==r.id).exists()
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



def geographic_resolution_quality(engine: Engine, release_id: UUID) -> dict:
    """Report current decision leaves only, separating valid non-county geography.

    This does not assert that a classified unit has a verified canonical boundary.
    """
    r,o = GeographicResolution, ElectionResultObservation
    child=r.__table__.alias("superseding")
    with engine.connect() as conn:
        rows=conn.execute(select(o.year,o.state_code,o.county_raw,o.county_fips,
            o.candidate_votes,r.status,r.method,r.jurisdiction_id,r.observation_id).join(
                o,o.id==r.observation_id).where(r.reference_release_id==release_id,
                ~select(child.c.id).where(child.c.supersedes_id==r.id).exists())).mappings().all()
    if not rows:
        return {"release_id":str(release_id),"observations":0,"status_counts":{},
                "coverage_by_year_state":[],"limitations":["No decisions published for this reference release"]}
    frame=pl.DataFrame([{"year":x["year"],"state":x["state_code"],
        "status":x["status"],"method":x["method"],
        "unit_key":f"{x['county_raw']}:{x['county_fips']}",
        "votes":x["candidate_votes"] or 0} for x in rows])
    coverage=(frame.group_by(["year","state","status"]).agg(
        pl.len().alias("observations"),
        pl.col("unit_key").n_unique().alias("distinct_source_units"),
        pl.col("votes").sum().alias("candidate_votes_total"))
        .sort(["year","state","status"]).to_dicts())
    counts=frame.group_by("status").agg(pl.len().alias("n")).to_dicts()
    return {"release_id":str(release_id),"observations":len(rows),
        "status_counts":{x["status"]:x["n"] for x in counts},
        "coverage_by_year_state":coverage,
        "limitations":["County resolution and non-county classification are distinct",
          "An elected district does not acquire a Census county boundary by classification"]}
