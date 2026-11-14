"""Step 6.1 resolver: source classification first, auditable revision chains.

No UPDATE or DELETE to election observations or existing geographic decisions.
Every changed publication must be explicitly authorized. `publish=False` is a
real read-only preview; `dry_run=True` is retained for existing callers.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from uuid import UUID, uuid4

import polars as pl
from sqlalchemy import Engine, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.core import DataSource
from app.models.geography import GeographicResolution, GeographicReportingUnit, GeographicResolutionContext
from app.models.ingestion import ElectionResultObservation
from ingestion.geography.rules import RULESET_VERSION, name_key
from ingestion.geography.publication import proposal_fingerprint, high_risk_changes, enforce_approval
from ingestion.geography import context
from ingestion.loader import _chunks


def current_resolution_rows(conn, release_id: UUID) -> dict:
    """Leaves of the immutable supersession chains (also handles migrated v1 roots)."""
    r=GeographicResolution.__table__
    child=r.alias("child")
    rows=conn.execute(select(r).where(r.c.reference_release_id==release_id,
        ~select(child.c.id).where(child.c.supersedes_id==r.c.id).exists())).mappings().all()
    result={}
    for row in rows:
        oid=row["observation_id"]
        if oid in result:
            raise ValueError(f"Multiple active geographic resolution chains for observation {oid}")
        result[oid]=dict(row)
    return result


def semantic_signature(decision: dict) -> tuple:
    return (decision["status"],decision["method"],decision["jurisdiction_id"],decision["reference_id"])


def decision_digest(decision: dict) -> str:
    payload={"status":decision["status"],"method":decision["method"],
             "jurisdiction_id":str(decision["jurisdiction_id"]),
             "reference_id":str(decision["reference_id"]),
             "evidence_json":decision["evidence_json"]}
    return sha256(json.dumps(payload,sort_keys=True,default=str,separators=(",", ":")).encode()).hexdigest()


def resolve_medsl_v2(engine: Engine, *, vintage: int, years: list[int] | None = None,
                     release_id: UUID | None = None, dry_run: bool = False,
                     source_name: str = "census_state_county_georef",
                     publish: bool = True, approve_changes: bool = False,
                     actor: str | None = None,
                     expected_proposal_sha256: str | None = None,
                     allow_downgrades: bool = False,
                     allow_jurisdiction_reassignment: bool = False,
                     context_sha256: str | None = None,
                     context_manifest: dict | None = None) -> tuple[dict,list[dict]]:
    from ingestion.geography.resolve import choose_release, assess_observation

    if publish and not dry_run and not (actor and actor.strip()):
        raise ValueError("Publishing requires --actor for an accountable audit trail")
    if context_sha256 and context_manifest is not None:
        raise ValueError('Choose a stored context digest or a preview manifest')
    with engine.begin() as conn:
        conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ' +
                          (' READ ONLY' if dry_run or not publish else '')))
        frozen = context.restore(conn, context_sha256) if context_sha256 else context_manifest
        if frozen is not None:
            if frozen.get('format') != 'data004-context-v1' or frozen.get('ruleset_version') != RULESET_VERSION:
                raise ValueError('Context format/ruleset differs; use its recorded resolver version')
            pinned = UUID(frozen['reference_release_id'])
            if release_id is not None and release_id != pinned:
                raise ValueError('Context primary reference release differs')
            release_id = pinned
        ref_release,begin,end=choose_release(conn,vintage,release_id,source_name=source_name)
        allowed=sorted(set(years if years is not None else
            [y for y in range(begin,end+1) if 2000<=y<=2024 and (y-2000)%4==0]))
        if not allowed or any(y < 2000 or y > 2024 or (y-2000)%4 for y in allowed):
            raise ValueError("--years must contain MEDSL presidential election years 2000..2024")
        # A release can be used only for its intended election-year range.
        if any(y<begin or y>end for y in allowed):
            raise ValueError("Election year outside reference product range")
        if publish and not dry_run:
            # Lock a single source row to serialize concurrent resolution publishers.
            conn.execute(select(DataSource.id).where(DataSource.name=="medsl_presidential_county")
                .with_for_update()).scalar_one()
        manifest = frozen if frozen is not None else context.capture(conn, ref_release, allowed)
        if manifest['election_years'] != allowed:
            raise ValueError('Context election-year scope differs')
        by_code, latest, legacy_by_code, newer_by_code, supplemental_2000_by_code, aliases, changes = context.indexes(manifest, begin, end)
        by_name=defaultdict(list)
        for v in by_code.values():
            by_name[(v["state_fips"],name_key(v["name_raw"]))].append(v)
        o=ElectionResultObservation
        scope = [(UUID(x['release_id']), x['year']) for x in manifest['observation_scope']]
        observations=conn.execute(select(o.id,o.source_row_number,o.year,o.state_code,o.state_fips,
            o.county_raw,o.county_fips_raw,o.county_fips,o.row_sha256,o.candidate_votes,
            o.total_votes).where(tuple_(o.release_id,o.year).in_(scope))
            .order_by(o.year,o.state_code,o.source_row_number)).mappings().all()
        if not observations:raise ValueError("No active MEDSL observations for years requested")
        observation_sha = context.digest([dict(x) for x in observations])
        if frozen is not None and manifest.get('observation_sha256') != observation_sha:
            raise ValueError('Recorded observation inputs changed')
        manifest = {**manifest, 'observation_sha256': observation_sha}
        input_sha = context.digest(manifest)
        previous=current_resolution_rows(conn,ref_release)
        proposals=[]
        review=[]
        differences=[]
        insert_rows=[]
        reporting_units={}
        for obs in observations:
            decision=assess_observation(dict(obs),by_code,by_name,latest,ref_release,begin,end,
                aliases=aliases,legacy_by_code=legacy_by_code,
                verified_changes=changes,cross_release_by_code=newer_by_code,
                supplemental_2000_by_code=supplemental_2000_by_code)
            old=previous.get(obs["id"])
            entry={"observation_id":obs["id"],"year":obs["year"],"state":obs["state_code"],
                "county_label":obs["county_raw"],"county_fips_raw":obs["county_fips_raw"],
                "county_fips":obs["county_fips"],"old_status":old["status"] if old else None,
                "proposed_status":decision["status"],"old_method":old["method"] if old else None,
                "proposed_method":decision["method"],"old_jurisdiction_id":str(old["jurisdiction_id"]) if old and old["jurisdiction_id"] else None,
                "proposed_jurisdiction_id":str(decision["jurisdiction_id"]) if decision["jurisdiction_id"] else None}
            changed=(old is None or semantic_signature(decision)!=semantic_signature(old))
            if changed:
                differences.append({**entry,"change":"NEW" if old is None else "REVISED"})
                if publish and not dry_run:
                    insert_rows.append({"id":uuid4(),"observation_id":obs["id"],
                        "reference_release_id":ref_release,"reference_id":decision["reference_id"],
                        "jurisdiction_id":decision["jurisdiction_id"],"status":decision["status"],
                        "method":decision["method"],"reason":decision["reason"],
                        "evidence_json":{**decision["evidence_json"],"ruleset_version":RULESET_VERSION},
                        "ruleset_version":RULESET_VERSION,"decision_sha256":decision_digest(decision),
                        "supersedes_id":old["id"] if old else None,"published_by":actor,
                        "context_sha256":input_sha})
            if publish and not dry_run and decision["status"] in {"NON_COUNTY_CLASSIFIED", "PENDING_REVIEW"}:
                ev=decision["evidence_json"]
                if ev.get("identifier_scheme"):
                    unit={"id":uuid4(),"source_name":"medsl_presidential_county",
                          "state_code":obs["state_code"],"election_year":obs["year"],
                          "source_label":obs["county_raw"] or "",
                          "identifier_scheme":ev["identifier_scheme"],
                          "identifier_value":ev["reporting_unit_id"],
                          "kind":ev["geographic_kind"],"status":decision["status"],
                          "evidence_url":ev.get("evidence_url")}
                    key=(unit["source_name"],unit["state_code"],unit["election_year"],
                         unit["identifier_scheme"],unit["identifier_value"])
                    reporting_units[key]=unit
            if decision["status"] not in {"RESOLVED","RESOLVED_HISTORICAL","RESOLVED_ALIAS","NON_COUNTY_CLASSIFIED"}:
                review.append({"observation_id":str(obs["id"]),"source_row_number":obs["source_row_number"],
                    "year":obs["year"],"state":obs["state_code"],"county_label":obs["county_raw"],
                    "fips_raw":obs["county_fips_raw"],"fips_normalized":obs["county_fips"],
                    "status":decision["status"],"method":decision["method"],
                    "reason":decision["reason"],"evidence":json.dumps(decision["evidence_json"],default=str)})
            proposals.append({**entry,"status":decision["status"],"method":decision["method"]})
        revised=sum(x["change"]=="REVISED" for x in differences)
        # The pure publish gate is separately unit-tested. The digest binds
        # review approval to this exact source release and set of proposals.
        proposal_sha256 = proposal_fingerprint(ref_release, RULESET_VERSION, differences,
                                               context_sha256=input_sha)
        downgrades, reassigned = high_risk_changes(differences)
        if publish and not dry_run:
            enforce_approval(revised=revised, actor=actor,
                approve_changes=approve_changes,
                preview_digest=expected_proposal_sha256,
                current_digest=proposal_sha256,
                downgrade_count=len(downgrades), reassignment_count=len(reassigned),
                allow_downgrades=allow_downgrades,
                allow_jurisdiction_reassignment=allow_jurisdiction_reassignment)
        inserted=0
        if publish and not dry_run:
            if insert_rows:
                conn.execute(pg_insert(GeographicResolutionContext.__table__).values(
                    sha256=input_sha, manifest=manifest).on_conflict_do_nothing())
            for chunk in _chunks(list(reporting_units.values()),400):
                conn.execute(pg_insert(GeographicReportingUnit.__table__).values(chunk)
                    .on_conflict_do_nothing(constraint="uq_geo_reporting_unit_scope"))
            for chunk in _chunks(insert_rows,400):
                result=conn.execute(pg_insert(GeographicResolution.__table__).values(chunk)
                    .returning(GeographicResolution.id)).all()
                inserted+=len(result)
        counts=Counter(p["status"] for p in proposals)
        summary=pl.DataFrame([{"year":x["year"],"state":x["state"],
            "status":x["status"],"method":x["method"],
            "unit_key":f"{x['county_label']}:{x['county_fips']}"} for x in proposals])
        coverage=(summary.group_by(["year","state","status"])
            .agg(pl.len().alias("observations"),pl.col("unit_key").n_unique().alias("distinct_reporting_units"))
            .sort(["year","state","status"]).to_dicts())
        # Database vote-sum reconciliation. No election observation SQL UPDATEs are issued.
        vote_rows=[{"year":x["year"],"state":x["state_code"],
            "votes":x["candidate_votes"] or 0} for x in observations]
        votes=(pl.DataFrame(vote_rows).group_by(["year","state"]).agg(
            pl.col("votes").sum().alias("candidate_votes_total"))
            .sort(["year","state"]).to_dicts())
        after=conn.execute(select(o.year,o.state_code,
            func.coalesce(func.sum(o.candidate_votes),0).label("votes"))
            .where(tuple_(o.release_id,o.year).in_(scope))
            .group_by(o.year,o.state_code).order_by(o.year,o.state_code)).all()
        expected={(x["year"],x["state"]):int(x["candidate_votes_total"]) for x in votes}
        actual={(y,st):int(amount) for y,st,amount in after}
        if expected!=actual:
            raise RuntimeError("Election vote totals changed during geographic resolution; transaction rolled back")
        return {"reference_release_id":str(ref_release),"ruleset_version":RULESET_VERSION,
            "context_sha256":input_sha,"context_manifest":manifest,
            "vintage":vintage,"product_years":[begin,end],"election_years":allowed,
            "records_examined":len(proposals),"records_inserted":inserted,
            "records_already_present":len(proposals)-inserted if publish and not dry_run else None,
            "dry_run":dry_run or not publish,"published":bool(publish and not dry_run),
            "status_counts":dict(counts),"coverage_by_year_state":coverage,
            "vote_totals_by_year_state":votes,"vote_totals_unchanged":True,
            "review_count":len(review),
            "previous_decisions_preserved":len(previous),
            "proposal_sha256":proposal_sha256,
            "resolved_match_downgrades":len(downgrades),
            "canonical_reassignments":len(reassigned),
            "decision_drift_for_review":revised,
            "new_decisions":len(differences)-revised,"changed_decisions":revised,
            "differences": [{k:(str(v) if isinstance(v,UUID) else v) for k,v in row.items()}
                            for row in differences]},review
