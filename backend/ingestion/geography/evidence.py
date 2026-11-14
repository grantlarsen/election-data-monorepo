"""Explicit review/approval of geographic alias and dated-change evidence."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import polars as pl
from sqlalchemy import Engine, and_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.geography import (GeographicAlias, GeographicChange, GeographicReference,
                                  GeographicIdentityLink)
from ingestion.geography.rules import RULESET_VERSION, name_key


def import_alias_candidates(engine: Engine, file: Path) -> dict:
    frame = pl.read_csv(file, infer_schema_length=0)
    names = {"source_name", "state_code", "source_label", "target_geoid", "first_year", "last_year", "evidence_url", "evidence_note"}
    if not names.issubset(frame.columns):
        raise ValueError(f"Missing columns: {sorted(names - set(frame.columns))}")
    proposals = []
    for row in frame.to_dicts():
        state = row["state_code"].upper().strip()
        fips = row["target_geoid"].strip()
        if (not state.isalpha() or len(state)!=2 or not fips.isascii() or
            not fips.isdecimal() or len(fips)!=5):
            raise ValueError(f"Invalid alias identifier: {row}")
        first,last = int(row["first_year"]),int(row["last_year"])
        if first>last or first<1900 or last>2100:
            raise ValueError("Invalid alias year range")
        if not name_key(row["source_label"]) or not row["evidence_url"].startswith("https://"):
            raise ValueError("Alias must have a nonempty label and HTTPS evidence URL")
        proposals.append(dict(id=uuid4(),source_name=row["source_name"],state_code=state,
            source_label_raw=row["source_label"],source_label_key=name_key(row["source_label"]),
            target_geoid=fips,first_year=first,last_year=last,status="PROPOSED",
            evidence_url=row["evidence_url"],evidence_note=row["evidence_note"],
            ruleset_version=RULESET_VERSION))
    from ingestion.medsl import STATE_FIPS
    if any(STATE_FIPS.get(r['state_code'])!=r['target_geoid'][:2] for r in proposals):
        raise ValueError("Alias target FIPS state prefix does not match source state")
    inserted=0
    with engine.begin() as conn:
        for r in proposals:
            has_ref = conn.execute(select(GeographicReference.id).where(
                GeographicReference.kind=="county",GeographicReference.geoid==r["target_geoid"]).limit(1)).first()
            if not has_ref:
                raise ValueError(f"Target {r['target_geoid']} has no ingested Census county evidence")
            stmt=pg_insert(GeographicAlias.__table__).values(r).on_conflict_do_nothing(
                constraint="uq_geographic_alias_scope").returning(GeographicAlias.id)
            inserted += len(conn.execute(stmt).all())
    return {"candidates":len(proposals),"inserted":inserted,"already_present":len(proposals)-inserted,"approved":0}


def approve_alias(engine: Engine, alias_id: UUID, *, actor: str, evidence_url: str) -> dict:
    if not actor.strip() or not evidence_url.startswith("https://"):
        raise ValueError("--actor and an authoritative HTTPS --evidence-url are required")
    with engine.begin() as conn:
        row=conn.execute(select(GeographicAlias.__table__).where(
            GeographicAlias.id==alias_id).with_for_update()).mappings().one()
        if row["status"] == "REJECTED":
            raise ValueError("Rejected alias cannot be approved")
        overlapping = conn.execute(select(GeographicAlias.id,GeographicAlias.target_geoid).where(
            GeographicAlias.source_name==row["source_name"],
            GeographicAlias.state_code==row["state_code"],
            GeographicAlias.source_label_key==row["source_label_key"],
            GeographicAlias.status=="APPROVED",
            GeographicAlias.first_year<=row["last_year"],
            GeographicAlias.last_year>=row["first_year"],
            GeographicAlias.id!=alias_id)).all()
        if any(other!=row["target_geoid"] for _,other in overlapping):
            raise ValueError("Conflicting approved alias exists for overlapping years")
        refs=conn.execute(select(GeographicReference.geoid,GeographicReference.jurisdiction_id,
            GeographicReference.vintage_start,GeographicReference.vintage_end).where(
            GeographicReference.kind=="county", GeographicReference.geoid==row["target_geoid"])).all()
        # If name changes across references, canonical UUIDs could differ; do not
        # invent a single identity in that situation. Resolver uses vintage reference.
        jid=refs[0][1] if len({r[1] for r in refs}) == 1 else None
        conn.execute(update(GeographicAlias.__table__).where(GeographicAlias.id==alias_id).values(
            status="APPROVED",jurisdiction_id=jid,approved_by=actor,
            approved_at=datetime.now(timezone.utc),evidence_url=evidence_url))
        return {"alias_id":str(alias_id),"status":"APPROVED","jurisdiction_id":str(jid) if jid else None}


def import_change_candidates(engine: Engine, file: Path) -> dict:
    frame=pl.read_csv(file,infer_schema_length=0)
    expected={"old_geoid","new_geoid","old_name","new_name","effective_date","change_type","evidence_url","evidence_note"}
    if not expected.issubset(frame.columns):
        raise ValueError(f"Missing columns: {sorted(expected-set(frame.columns))}")
    inserted=0
    with engine.begin() as conn:
        for row in frame.to_dicts():
            old,new=row["old_geoid"],row["new_geoid"]
            if len(old)!=5 or len(new)!=5 or not old.isdecimal() or not new.isdecimal() or old[:2]!=new[:2]:
                raise ValueError(f"Invalid county change codes: {old} -> {new}")
            if not row["evidence_url"].startswith("https://"):
                raise ValueError("Official HTTPS source required")
            r={"id":uuid4(), "old_geoid":old,"new_geoid":new,
               "old_name":row["old_name"],"new_name":row["new_name"],
               "effective_date":date.fromisoformat(row["effective_date"]),
               "change_type":row["change_type"],"evidence_url":row["evidence_url"],
               "evidence_note":row["evidence_note"],"status":"PROPOSED"}
            inserted+=len(conn.execute(pg_insert(GeographicChange.__table__).values(r)
                .on_conflict_do_nothing(constraint="uq_geographic_change_event")
                .returning(GeographicChange.id)).all())
    return {"candidates":frame.height,"inserted":inserted,"approved":0}


def verify_change(engine: Engine, change_id: UUID, *, actor: str) -> dict:
    if not actor.strip(): raise ValueError("--actor is required")
    with engine.begin() as conn:
        row=conn.execute(select(GeographicChange.__table__).where(
            GeographicChange.id==change_id).with_for_update()).mappings().one()
        if row["status"] == "REJECTED": raise ValueError("Rejected change cannot be verified")
        conn.execute(update(GeographicChange.__table__).where(GeographicChange.id==change_id).values(
            status="VERIFIED", verified_by=actor,verified_at=datetime.now(timezone.utc)))
        return {"change_id":str(change_id),"status":"VERIFIED"}


def pending_evidence(engine: Engine) -> dict:
    with engine.connect() as conn:
        aliases=conn.execute(select(GeographicAlias.id, GeographicAlias.state_code,GeographicAlias.source_label_raw,
            GeographicAlias.target_geoid,GeographicAlias.first_year,GeographicAlias.last_year,
            GeographicAlias.status,GeographicAlias.evidence_url).order_by(GeographicAlias.state_code)).mappings().all()
        changes=conn.execute(select(GeographicChange.id,GeographicChange.old_geoid,GeographicChange.new_geoid,
            GeographicChange.effective_date,GeographicChange.status,GeographicChange.evidence_url)).mappings().all()
    def asdict(r):return {k: str(v) if isinstance(v,(UUID,date,datetime)) else v for k,v in r.items()}
    return {"aliases":[asdict(a) for a in aliases],"changes":[asdict(c) for c in changes]}



def approve_identity_link(engine: Engine, change_id: UUID, old_id: UUID, new_id: UUID,
                          *, actor: str, relationship: str = "SAME_ENTITY_RECODED") -> dict:
    if not actor.strip() or relationship not in {"SAME_ENTITY_RECODED", "SUCCESSOR"}:
        raise ValueError("Explicit --actor and recognized --relationship are required")
    with engine.begin() as conn:
        change=conn.execute(select(GeographicChange.__table__).where(
            GeographicChange.id==change_id)).mappings().one()
        if change["status"]!="VERIFIED":
            raise ValueError("Change must be verified before asserting identity continuity")
        present=set(conn.execute(select(GeographicReference.geoid,GeographicReference.jurisdiction_id)
            .where(GeographicReference.kind=="county",GeographicReference.geoid.in_(
                [change["old_geoid"],change["new_geoid"]]))).all())
        if ((change["old_geoid"],old_id) not in present or
            (change["new_geoid"],new_id) not in present):
            raise ValueError("Both jurisdiction IDs must have Census reference evidence for the specified codes")
        link={"id":uuid4(),"change_id":change_id,"old_jurisdiction_id":old_id,
              "new_jurisdiction_id":new_id,"relationship":relationship,"approved_by":actor}
        inserted=conn.execute(pg_insert(GeographicIdentityLink.__table__).values(link)
            .on_conflict_do_nothing(constraint="uq_geo_identity_link")
            .returning(GeographicIdentityLink.id)).scalar_one_or_none()
    return {"change_id":str(change_id),"old_jurisdiction_id":str(old_id),
            "new_jurisdiction_id":str(new_id),"relationship":relationship,
            "inserted":inserted is not None}
