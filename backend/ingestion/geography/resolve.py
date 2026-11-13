"""Conservative, append-only MEDSL-to-Census county resolution."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from uuid import UUID, uuid4

import polars as pl
from sqlalchemy import Engine, and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.core import DataSource
from app.models.geography import GeographicReference, GeographicResolution
from app.models.ingestion import ElectionResultObservation, SourceActiveYear, SourceRelease
from ingestion.adapters.census_state_county_georef import name_key
from ingestion.loader import _chunks
from ingestion.medsl import STATE_FIPS


def assess_observation(obs: dict, by_code: dict, by_name: dict,
                       latest: dict, release_id: UUID,
                       vintage_start: int, vintage_end: int) -> dict:
    """Pure decision function. Never resolve from name alone or a code/label conflict."""
    state_code = (obs.get("state_code") or "").upper()
    state_fips = obs.get("state_fips") or ""
    year = int(obs["year"])
    fips = obs.get("county_fips")
    raw_fips = (obs.get("county_fips_raw") or "").strip()
    raw_label = obs.get("county_raw") or ""
    label = name_key(raw_label)
    base = {"reference_id": None, "jurisdiction_id": None,
            "status": "UNRESOLVED", "method": "NO_MATCH",
            "reason": "", "evidence_json": {
                "source_fips_raw": raw_fips, "source_fips_normalized": fips,
                "source_county_label": raw_label, "source_state_code": state_code,
                "reference_release_id": str(release_id),
                "reference_product_start_year": vintage_start,
                "reference_product_end_year": vintage_end,
                "source_election_year": year,
            }}
    def outcome(status, reason, method="NO_MATCH", ref=None, **facts):
        decision = dict(base, status=status, reason=reason, method=method,
                        reference_id=ref["id"] if ref else None,
                        jurisdiction_id=ref["jurisdiction_id"] if ref and status.startswith("RESOLVED") else None)
        decision["evidence_json"] = {**base["evidence_json"], **facts}
        if ref is not None:
            decision["evidence_json"]["census_label"] = ref["name_raw"]
            decision["evidence_json"]["census_geoid"] = ref["geoid"]
        return decision

    if year < vintage_start or year > vintage_end:
        return outcome("OUT_OF_VINTAGE", "Election year outside this reference product range")
    if state_code not in STATE_FIPS or state_fips != STATE_FIPS[state_code]:
        return outcome("INVALID", "MEDSL state abbreviation and state FIPS disagree")
    if raw_fips and raw_fips.isascii() and raw_fips.isdecimal() and len(raw_fips) <= 5:
        if raw_fips.zfill(5)[:2] != state_fips:
            return outcome("INVALID", "Source county FIPS prefix conflicts with state", "STATE_PREFIX_CONFLICT")
    if fips is None:
        candidates = by_name.get((state_fips, label), [])
        return outcome("UNRESOLVED", "Missing or invalid county FIPS; no name-only linking",
                       "NAME_CANDIDATE_REVIEW" if candidates else "MISSING_FIPS",
                       name_candidate_geoids=[x["geoid"] for x in candidates[:10]])
    if not (len(fips) == 5 and fips.isascii() and fips.isdecimal()):
        return outcome("INVALID", "Stored normalized FIPS is malformed")
    if fips[:2] != state_fips:
        return outcome("INVALID", "Stored normalized county FIPS conflicts with state")
    if fips[-3:] in {"999", "000"}:
        return outcome("UNRESOLVED", "Non-county aggregate or special reporting code", "SPECIAL_REPORTING_UNIT")
    ref = by_code.get(fips)
    if ref is None:
        return outcome("UNRESOLVED", "FIPS does not occur in selected Census reference",
                       "FIPS_NOT_IN_REFERENCE")
    if not label:
        return outcome("AMBIGUOUS", "Source county label missing or unparseable", "LABEL_MISSING", ref=ref)
    if label != ref["name_key"]:
        return outcome("AMBIGUOUS", "FIPS and geographic label conflict; manual review required",
                       "CODE_LABEL_CONFLICT", ref=ref)
    # A historical flag is an evidence-based comparison with the newest ingested
    # reference, not an assertion of the legal date of a rename or code change.
    most_recent = latest.get(fips)
    is_historical = bool(most_recent and most_recent[0] > vintage_end and
                         most_recent[1] != ref["name_key"])
    if latest and fips not in latest:
        is_historical = True
    # latest map contains only latest reference, therefore removed old code qualifies.
    return outcome("RESOLVED_HISTORICAL" if is_historical else "RESOLVED",
                   "Exact state, five-digit county GEOID, and normalized county name match",
                   "CENSUS_FIPS_AND_NAME", ref=ref,
                   legal_effective_dates_verified=False,
                   historical_comparison=bool(is_historical))


def choose_release(conn, vintage: int, explicit_release_id: UUID | None = None,
                   *, source_name: str = "census_state_county_georef") -> tuple[UUID, int, int]:
    import importlib
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_]*", source_name):
        raise ValueError("Invalid geographic adapter name")
    adapter = importlib.import_module(f"ingestion.adapters.{source_name}").Job(vintage)
    if not getattr(adapter, "geographic_reference", False):
        raise ValueError("Source is not a geographic adapter")
    info = adapter.describe()
    if explicit_release_id:
        row = conn.execute(select(SourceRelease.id, SourceRelease.metadata_json).join(
            DataSource, SourceRelease.source_id == DataSource.id).where(
            SourceRelease.id == explicit_release_id, DataSource.name == adapter.key)).one_or_none()
        if row is None or row.metadata_json.get("vintage_start") != info.metadata["vintage_start"]:
            raise ValueError("--release-id is not a Census release for selected vintage")
        return row.id, info.metadata["vintage_start"], info.metadata["vintage_end"]
    rows = conn.execute(select(SourceRelease.id).join(
        DataSource, SourceRelease.source_id == DataSource.id).where(
        DataSource.name == adapter.key, SourceRelease.version == info.version
    ).order_by(SourceRelease.retrieved_at.desc(), SourceRelease.id).limit(2)).all()
    if not rows:
        raise ValueError(f"No Census reference loaded for {vintage}; first run census_state_county_georef --vintage {vintage}")
    if len(rows) > 1:
        # If source bytes changed under same version, requiring pinning prevents silent resolution drift.
        raise ValueError("Multiple source checksums for selected vintage; specify --release-id explicitly")
    return rows[0].id, info.metadata["vintage_start"], info.metadata["vintage_end"]


def resolve_medsl(engine: Engine, *, vintage: int, years: list[int] | None = None,
                  release_id: UUID | None = None, dry_run: bool = False,
                  source_name: str = "census_state_county_georef") -> tuple[dict, list[dict]]:
    """Save new decisions in one transaction. Old decisions and original observations are untouched."""
    with engine.begin() as conn:
        ref_release, begin, end = choose_release(conn, vintage, release_id, source_name=source_name)
        # The years are MEDSL elections rather than all geographic products.
        allowed = sorted(years if years is not None else
                         [y for y in range(begin, end + 1) if 2000 <= y <= 2024 and (y - 2000) % 4 == 0])
        if not allowed or any(y < 2000 or y > 2024 or (y - 2000) % 4 for y in allowed):
            raise ValueError("--years must contain MEDSL presidential election years 2000..2024")
        ref_rows = conn.execute(select(GeographicReference.id, GeographicReference.geoid,
                                       GeographicReference.name_raw, GeographicReference.name_key,
                                       GeographicReference.jurisdiction_id, GeographicReference.state_fips).where(
            GeographicReference.release_id == ref_release,
            GeographicReference.kind == "county")).mappings().all()
        by_code = {r["geoid"]: dict(r) for r in ref_rows}
        if len(by_code) != len(ref_rows) or not by_code:
            raise ValueError("Missing or duplicate county reference identifiers")
        by_name: dict[tuple[str, str], list] = defaultdict(list)
        for r in by_code.values():
            by_name[(r["state_fips"], r["name_key"])].append(r)
        # Use the latest *different* loaded vintage as a comparison, not as proof of legal change date.
        newest = conn.execute(select(func.max(GeographicReference.vintage_end)).where(
            GeographicReference.kind == "county")).scalar_one_or_none()
        latest = {}
        if newest is not None and newest > end:
            recent = conn.execute(select(GeographicReference.geoid, GeographicReference.name_key,
                                         GeographicReference.vintage_end).where(
                GeographicReference.kind == "county", GeographicReference.vintage_end == newest)).all()
            latest = {code: (yr, name) for code, name, yr in recent}
        o = ElectionResultObservation
        observations = conn.execute(select(
            o.id, o.source_row_number, o.year, o.state_code, o.state_fips,
            o.county_raw, o.county_fips_raw, o.county_fips
        ).join(SourceActiveYear, and_(o.release_id == SourceActiveYear.release_id,
                                      o.year == SourceActiveYear.year))
        .join(DataSource, DataSource.id == SourceActiveYear.source_id)
        .where(DataSource.name == "medsl_presidential_county", o.year.in_(allowed))
        .order_by(o.year, o.state_code, o.source_row_number)).mappings().all()
        if not observations:
            raise ValueError("No active MEDSL observations for requested election years")
        previous = conn.execute(select(GeographicResolution.observation_id,
                                       GeographicResolution.reference_id,
                                       GeographicResolution.jurisdiction_id,
                                       GeographicResolution.status,
                                       GeographicResolution.method,
                                       GeographicResolution.reason,
                                       GeographicResolution.evidence_json).where(
            GeographicResolution.reference_release_id == ref_release)).mappings().all()
        previous_by_observation = {r["observation_id"]: dict(r) for r in previous}
        mapped = []
        review = []
        decision_drift = 0
        for obs in observations:
            proposed = assess_observation(dict(obs), by_code, by_name, latest,
                                          ref_release, begin, end)
            saved = previous_by_observation.get(obs["id"])
            if saved is not None:
                if (saved["status"], saved["jurisdiction_id"], saved["reference_id"]) != (
                    proposed["status"], proposed["jurisdiction_id"], proposed["reference_id"]):
                    decision_drift += 1
                # A replay reports the actual persisted decision, not a fresh verdict.
                # Never silently rewrite previously audited matches.
                decision = {k: saved[k] for k in ("reference_id", "jurisdiction_id", "status",
                                                   "method", "reason", "evidence_json")}
            else:
                decision = proposed
            entry = {"id": uuid4(), "observation_id": obs["id"],
                     "reference_release_id": ref_release, **decision}
            mapped.append(entry)
            if not decision["status"].startswith("RESOLVED"):
                review.append({"observation_id": str(obs["id"]), "source_row_number": obs["source_row_number"],
                               "year": obs["year"], "state": obs["state_code"],
                               "fips_raw": obs["county_fips_raw"], "fips_normalized": obs["county_fips"],
                               "county_label": obs["county_raw"], "status": decision["status"],
                               "method": decision["method"], "reason": decision["reason"]})
        inserted = 0
        if not dry_run:
            for chunk in _chunks(mapped, 400):
                stmt = (pg_insert(GeographicResolution.__table__).values(chunk)
                        .on_conflict_do_nothing(index_elements=["observation_id", "reference_release_id"])
                        .returning(GeographicResolution.id))
                inserted += len(conn.execute(stmt).all())
        counts = dict(Counter(r["status"] for r in mapped))
        summary = pl.DataFrame([{"year": o["year"], "state": o["state_code"],
                                 "status": d["status"]} for o, d in zip(observations, mapped)])
        coverage = (summary.group_by(["year", "state", "status"])
                    .agg(pl.len().alias("observations"))
                    .sort(["year", "state", "status"]).to_dicts())
        return {"reference_release_id": str(ref_release), "vintage": vintage,
                "product_years": [begin, end], "election_years": allowed,
                "records_examined": len(mapped), "records_inserted": inserted,
                "records_already_present": len(mapped) - inserted if not dry_run else None,
                "dry_run": dry_run, "status_counts": counts,
                "coverage_by_year_state": coverage,
                "review_count": len(review),
                "previous_decisions_preserved": len(previous_by_observation),
                "decision_drift_for_review": decision_drift}, review
