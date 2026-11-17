"""Source-scoped current Senate contests/candidacies, without person matching.

Only entity identities are registered. Provisional counts remain in the verified
cache and are never inserted into canonical or certified vote publications.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.core import Candidacy, Contest, DataSource, Jurisdiction, PoliticalParty
from app.models.ingestion import IngestionRun, SourceRelease
from app.models.senate_returns import SenateContest, SenateSeat
from app.services import elections
from app.services.senate_results import cache_directory, read_snapshot
from app.services.election_map import summarize
from app.services.canonical_results import MaterializationError
from app.services.senate_control import senate_control
from app.services.candidate_media import candidate_portrait
from ingestion.current_senate import ELECTION_DATE, YEAR, utc_timestamp

SOURCE = "call_the_map_senate"
PREFIX = f"{SOURCE}:{YEAR}:"
RULESET = "current-senate-entities-v1"
CATALOG = Path(__file__).resolve().parents[2] / "ingestion/catalog/senate_incumbents.json"
BUCKETS = {"write-in", "write-ins", "write in", "write ins", "write-in totals", "other", "others", "scattering"}
PARTIES = {"D": "DEMOCRATIC", "R": "REPUBLICAN", "I": "INDEPENDENT", "L": "LIBERTARIAN", "G": "GREEN"}


def candidate_key(race_id: str, candidate: dict) -> str | None:
    if candidate["name"].strip().casefold() in BUCKETS:
        return None
    # Exact source labels and party lines, never a cross-source person identifier.
    key = json.dumps([race_id, candidate["name"], candidate["party"]], ensure_ascii=False)
    return PREFIX + sha256(key.encode()).hexdigest()


def incumbent_evidence(race: dict, candidate: dict, *, catalog: dict | None = None) -> dict | None:
    catalog = catalog or json.loads(CATALOG.read_text(encoding="utf-8"))
    if catalog["year"] != YEAR or catalog["as_of"] != ELECTION_DATE:
        raise ValueError("Incumbency evidence does not cover this election")
    matches = [item for item in catalog["candidates"] if
        (item["state"], item["name"], item["party"], item["class"]) ==
        (race["state_code"], candidate["name"], candidate["party"], race["seat_class"])]
    if len(matches) != 1:
        return None
    item = matches[0]
    return {**item, "as_of": catalog["as_of"], "reviewed_at": catalog["reviewed_at"],
            "url": catalog["sources"][str(item["class"])], "method": catalog["method"],
            "source_sha256": catalog.get("roster_sha256", {}).get(str(item["class"]))}


def enrich_snapshot(session: Session, snapshot: dict) -> dict:
    result = deepcopy(snapshot)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    candidates = {c.creation_key: c for c in session.scalars(select(Candidacy).where(Candidacy.creation_key.startswith(PREFIX, autoescape=True)))}
    contests = {c.creation_key: c for c in session.scalars(select(Contest).where(Contest.creation_key.startswith(PREFIX, autoescape=True)))}
    for race in result["races"]:
        contest = contests.get(PREFIX + race["id"])
        race["contest_id"] = str(contest.id) if contest else None
        for candidate in race["candidates"]:
            key = candidate_key(race["id"], candidate)
            identity = candidates.get(key)
            evidence = incumbent_evidence(race, candidate, catalog=catalog) if key else None
            candidate.update(candidacy_id=str(identity.id) if identity else None,
                kind="candidate" if key else "aggregate", incumbent=True if evidence else None,
                incumbent_evidence=evidence,
                portrait=candidate_portrait(SOURCE, YEAR, race["id"], candidate["name"], candidate["party"]) if key else None)
        summary = summarize([{"label": c["name"], "votes": c["votes"], "kind": c["kind"]} for c in race["candidates"]])
        race.update(summary_status=summary["status"], leader=summary["leader"],
                    margin_votes=summary["margin_votes"], margin_pct=summary["margin_pp"])
    result['control'] = senate_control(result)
    return result


def sync_entities(session: Session, snapshot: dict, directory: Path | None = None) -> dict:
    """Idempotently register source identities and an auditable source-row crosswalk."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), {"scope": PREFIX})
    source = session.scalar(select(DataSource).where(DataSource.name == SOURCE))
    if source is None:
        source = DataSource(name=SOURCE, url="https://www.callthemap.com/results/data")
        session.add(source)
        session.flush()
    version = snapshot["published_at"]
    release = session.scalar(select(SourceRelease).where(SourceRelease.source_id == source.id,
        SourceRelease.version == version, SourceRelease.sha256 == snapshot["sha256"]))
    if release is None:
        release = SourceRelease(source_id=source.id, version=version, sha256=snapshot["sha256"],
            filename="races.csv", file_id=1, download_url=snapshot["source_url"],
            raw_path=str((directory or cache_directory()) / "raw" / f"{snapshot['sha256']}.csv"),
            retrieved_at=utc_timestamp(snapshot["retrieved_at"]), published_at=utc_timestamp(version),
            metadata_json={"source": SOURCE, "ruleset": RULESET, "manifest_url": snapshot["manifest_url"],
                "file_id_semantics": "Adapter-local ordinal 1 for races.csv; not an upstream identifier",
                "result_status": "provisional compilation; certification is per race", "license": "CC BY 4.0"})
        session.add(release)
        session.flush()
    catalog_hash = sha256(CATALOG.read_bytes()).hexdigest()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    previous = session.scalar(select(IngestionRun).where(IngestionRun.release_id == release.id,
        IngestionRun.status == "COMPLETED", IngestionRun.options_json["ruleset"].astext == RULESET,
        IngestionRun.options_json["incumbency_catalog_sha256"].astext == catalog_hash).limit(1))
    if previous:
        return {"status": "unchanged", "run_id": str(previous.id), "release_id": str(release.id),
                "inserted": 0, "unchanged": previous.records_inserted + previous.options_json["records_unchanged"]}
    started = datetime.now(timezone.utc)
    jurisdictions = {}
    for jurisdiction in session.scalars(select(Jurisdiction).where(Jurisdiction.level == "state")):
        if jurisdiction.state_code in jurisdictions:
            raise ValueError("Ambiguous canonical state jurisdiction")
        jurisdictions[jurisdiction.state_code] = jurisdiction
    seats = {(s.state_code, s.seat_class): s for s in session.scalars(select(SenateSeat))}
    parties = {p.name: p.id for p in session.scalars(select(PoliticalParty))}
    known = set(session.scalars(select(Candidacy.creation_key).where(Candidacy.creation_key.startswith(PREFIX, autoescape=True))))
    rows, inserted, excluded = [], 0, 0
    for race in snapshot["races"]:
        jurisdiction = jurisdictions.get(race["state_code"])
        seat = seats.get((race["state_code"], race["seat_class"]))
        if jurisdiction is None or seat is None:
            raise ValueError("Prepare canonical state jurisdictions and Senate seat identities before profile registration")
        key = PREFIX + race["id"]
        event = elections.election(session, creation_key=key + ":event", election_date=date.fromisoformat(ELECTION_DATE),
            election_type="special" if race["special"] else "general", election_cycle=YEAR, jurisdiction_id=jurisdiction.id)
        contest = elections.contest(session, creation_key=key, office_name="U.S. Senate", election_id=event.id,
            jurisdiction_id=jurisdiction.id, office_id=seat.office_id)
        if session.get(SenateContest, contest.id) is None:
            session.add(SenateContest(contest_id=contest.id, scope_evidence_json={"source": SOURCE,
                "source_race_id": race["id"], "source_release_id": str(release.id), "year": YEAR,
                "seat_class": race["seat_class"], "special": race["special"], "source_url": race["source_url"]}))
        for candidate in race["candidates"]:
            candidate_id = candidate_key(race["id"], candidate)
            if candidate_id is None:
                excluded += 1
                continue
            entity = elections.candidacy(session, creation_key=candidate_id, contest_id=contest.id,
                source_label=candidate["name"], candidate_kind="candidate",
                party_id=parties.get(PARTIES.get(candidate["party"], "")))
            inserted += candidate_id not in known
            rows.append({"candidacy_id": str(entity.id), "source_row_number": candidate["source_row_number"],
                "race_id": race["id"], "name": candidate["name"], "party": candidate["party"],
                "incumbent_evidence": incumbent_evidence(race, candidate, catalog=catalog)})
    finished = datetime.now(timezone.utc)
    run = IngestionRun(source_id=source.id, release_id=release.id, status="COMPLETED", started_at=started,
        completed_at=finished, duration_ms=int((finished - started).total_seconds() * 1000),
        records_read=snapshot["accepted_rows"], records_inserted=inserted, records_updated=0, records_rejected=0,
        raw_sha256=snapshot["sha256"], options_json={"ruleset": RULESET, "records_unchanged": len(rows) - inserted,
            "excluded_anonymous_buckets": excluded, "incumbency_catalog_sha256": catalog_hash,
            "source_rows": rows, "note": "No person matching or vote publication; source-scoped candidacies only"})
    session.add(run)
    session.flush()
    return {"status": "registered", "run_id": str(run.id), "release_id": str(release.id),
            "inserted": inserted, "unchanged": len(rows) - inserted, "excluded_buckets": excluded}


def sync_cached_entities(directory: Path | None = None) -> dict:
    from app.database import SessionLocal
    with SessionLocal() as session, session.begin():
        return sync_entities(session, read_snapshot(directory), directory)


def provisional_profile(session: Session, candidate: Candidacy) -> dict | None:
    if not (candidate.creation_key or "").startswith(PREFIX):
        return None
    try:
        snapshot = enrich_snapshot(session, read_snapshot())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MaterializationError("Current Senate source snapshot is unavailable") from exc
    for race in snapshot["races"]:
        if any(c["candidacy_id"] == str(candidate.id) for c in race["candidates"]):
            return {"race": race, "checked_at": snapshot["checked_at"], "stale": snapshot["stale"],
                    "sha256": snapshot["sha256"], "retrieved_at": snapshot["retrieved_at"]}
    return None
