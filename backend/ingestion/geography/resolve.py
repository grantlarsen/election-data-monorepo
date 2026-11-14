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
from ingestion.geography.rules import (RULESET_VERSION, name_key, non_county_classification,
                                       CENSUS_CT_CHANGE, CENSUS_2015_CHANGES,
                                       county_equivalent_name_match, retired_identifier_evidence,
                                       CENSUS_INDEPENDENT_CITIES)
from ingestion.loader import _chunks
from ingestion.medsl import STATE_FIPS


def assess_observation(obs: dict, by_code: dict, by_name: dict,
                       latest: dict, release_id: UUID,
                       vintage_start: int, vintage_end: int, *, aliases: list[dict] | None = None,
                       legacy_by_code: dict | None = None,
                       verified_changes: list[dict] | None = None,
                       cross_release_by_code: dict | None = None,
                       supplemental_2000_by_code: dict | None = None) -> dict:
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

    # Validate the state independently. No reporting-unit category should conceal
    # a source state mismatch, even if its label looks like a district.
    if state_code not in STATE_FIPS or state_fips != STATE_FIPS[state_code]:
        return outcome("INVALID", "MEDSL state abbreviation and state FIPS disagree")
    # The namespace of the observation is established *before* interpreting any
    # numeric field as Census FIPS. Alaska district 20 is NOT Anchorage (02020).
    special = non_county_classification(obs)
    if special is not None:
        return outcome(special["status"], special["reason"], special["method"],
                       geographic_kind=special["kind"],identifier_scheme=special["namespace"],
                       reporting_unit_id=special["identifier"],evidence_url=special["evidence_url"],
                       county_link_intentionally_null=True)
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
    retired = retired_identifier_evidence(state_code, fips, year)
    if retired:
        # The retirement evidence itself has a "reason" key. Passing **retired
        # would collide with outcome(status, reason, method, ...).
        # Keep the documentary evidence intact as a nested payload.
        return outcome(
            "PENDING_REVIEW",
            "Officially retired geographic identifier used in source election results; do not silently remap",
            "RETIRED_OFFICIAL_GEOID",
            retirement_evidence=retired,
        )
    ref = by_code.get(fips)
    if ref is None:
        # Exact 2000 Census snapshot is an independently versioned source.
        # It may fill gaps in a statistical-series reference (e.g. DC/Miami-Dade),
        # but never override a contradictory county entry in that reference.
        if year == 2000 and supplemental_2000_by_code:
            supplement = supplemental_2000_by_code.get(fips)
            if supplement and county_equivalent_name_match(
                state_code, fips, raw_label, supplement["name_raw"], year
            ):
                return outcome("RESOLVED_HISTORICAL", "Matched authoritative Census 2000 county Gazetteer missing from statistical-series reference",
                               "CENSUS_2000_GAZETTEER_SUPPLEMENT", ref=supplement,
                               supplemental_release_id=str(supplement["release_id"]),
                               supplemental_vintage=2000,
                               supplemental_source="census_2000_counties_gazetteer")
        # Connecticut's 2024 election source still reports the legacy eight
        # county areas. Do not equate them to the nine new planning regions.
        if state_code == "CT" and year == 2024 and legacy_by_code:
            old = legacy_by_code.get(fips)
            if old is not None and label and label == name_key(old["name_raw"]):
                return outcome("RESOLVED_HISTORICAL", "Election uses legacy Connecticut county reporting geography; not a current Census county equivalent",
                               "CT_LEGACY_COUNTY", ref=old, geographic_kind="legacy_county_reporting_area",
                               evidence_url=CENSUS_CT_CHANGE, reference_vintage=old.get("vintage_end"),
                               legal_effective_dates_verified=False)
        # Evidence-backed code change, only if an independently verified event
        # and exact post-change label/code are both present.
        for change in (verified_changes or []):
            if fips == change["new_geoid"] and year >= change["effective_date"].year:
                newer=(cross_release_by_code or {}).get(fips)
                if newer and label == name_key(change["new_name"]) and label == name_key(newer["name_raw"]):
                    return outcome("RESOLVED_HISTORICAL", "Authoritative dated recoding and later Census identifier agree",
                                   "VERIFIED_CODE_CHANGE", ref=newer, geographic_kind="county",
                                   evidence_url=change["evidence_url"], change_effective_date=str(change["effective_date"]),
                                   reference_vintage=newer.get("vintage_end"))
            if fips == change["old_geoid"] and year >= change["effective_date"].year:
                return outcome("PENDING_REVIEW", "Retired FIPS appears after its official change date; check source reporting convention",
                               "RETIRED_FIPS", suggested_new_fips=change["new_geoid"],
                               evidence_url=change["evidence_url"])
        return outcome("UNRESOLVED", "FIPS does not occur in selected Census reference",
                       "FIPS_NOT_IN_REFERENCE")
    if not label:
        return outcome("AMBIGUOUS", "Source county label missing or unparseable", "LABEL_MISSING", ref=ref)
    # Re-normalize the *raw* reference name: persisted Step 6 name_key values
    # used a buggy rule that removed CITY, and must not be trusted after upgrade.
    name_match = county_equivalent_name_match(
        state_code, fips, raw_label, ref["name_raw"], year
    )
    if name_match is None:
        approved = [a for a in (aliases or []) if a["state_code"] == state_code
                    and a["source_label_key"] == label
                    and a["first_year"] <= year <= a["last_year"]]
        targets = {a["target_geoid"] for a in approved}
        if targets == {fips}:
            # Aliases are evidence-backed and approved, never fuzzy matches.
            return outcome("RESOLVED_ALIAS", "Reviewed source-specific alias agrees with Census FIPS",
                           "APPROVED_SOURCE_ALIAS", ref=ref, geographic_kind="county",
                           alias_ids=[str(a["id"]) for a in approved],
                           alias_evidence_urls=[a["evidence_url"] for a in approved])
        return outcome("AMBIGUOUS", "FIPS and geographic label conflict; manual review required",
                       "CODE_LABEL_CONFLICT", ref=ref, conflicting_alias_targets=sorted(targets))
    # County code already matched; a recognized Census independent-city suffix
    # is an entity-typed match, not a general city/county string equivalence.
    independent_city = name_match == "CENSUS_INDEPENDENT_CITY_SUFFIX"
    # An exact code/name match can also be historically significant if a
    # separately verified effective-date event establishes that this code was
    # newly assigned before the election. Do not infer this from CBP ranges.
    for change in (verified_changes or []):
        if (fips == change["new_geoid"] and year >= change["effective_date"].year
                and label == name_key(change["new_name"])):
            return outcome("RESOLVED_HISTORICAL", "Exact county match with verified dated FIPS recoding",
                           "VERIFIED_CODE_CHANGE", ref=ref,
                           evidence_url=change["evidence_url"],
                           change_effective_date=str(change["effective_date"]),
                           legal_effective_dates_verified=True)
    # A historical flag is an evidence-based comparison with the newest ingested
    # reference, not an assertion of the legal date of a rename or code change.
    most_recent = latest.get(fips)
    is_historical = bool(most_recent and most_recent[0] > vintage_end and
                         most_recent[1] != name_key(ref["name_raw"]))
    if latest and fips not in latest:
        is_historical = True
    # latest map contains only latest reference, therefore removed old code qualifies.
    return outcome("RESOLVED_HISTORICAL" if is_historical else "RESOLVED",
                   "Exact state, five-digit county GEOID, and normalized county name match",
                   "CENSUS_INDEPENDENT_CITY" if independent_city else "CENSUS_FIPS_AND_NAME", ref=ref,
                   geographic_kind="independent_city_county_equivalent" if independent_city else "county",
                   evidence_url=CENSUS_INDEPENDENT_CITIES if independent_city else None,
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
                  source_name: str = "census_state_county_georef",
                  publish: bool = True, approve_changes: bool = False,
                  actor: str | None = None,
                  expected_proposal_sha256: str | None = None,
                  allow_downgrades: bool = False,
                  allow_jurisdiction_reassignment: bool = False,
                  context_sha256: str | None = None,
                  context_manifest: dict | None = None) -> tuple[dict, list[dict]]:
    """Compatible interface delegating to the reviewed Step 6.1 resolver."""
    from ingestion.geography.resolution_v2 import resolve_medsl_v2
    return resolve_medsl_v2(engine, vintage=vintage, years=years,
                            release_id=release_id, dry_run=dry_run,
                            source_name=source_name, publish=publish,
                            approve_changes=approve_changes, actor=actor,
                            expected_proposal_sha256=expected_proposal_sha256,
                            allow_downgrades=allow_downgrades,
                            allow_jurisdiction_reassignment=allow_jurisdiction_reassignment,
                            context_sha256=context_sha256, context_manifest=context_manifest)
