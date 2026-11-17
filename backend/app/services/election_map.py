"""Join a pinned display vintage to existing published result accessors.

All pages are read in the request's repeatable-read snapshot. County joins use
the exact publication reference GEOID, never names or successor identifiers.
"""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.election_schemas import ElectionFilters, ResultFilters
from app.api.map_schemas import MapFilters
from app.models.geography import GeographicReference
from app.models.core import PoliticalParty
from app.models.ingestion import ElectionResultObservation
from app.services import election_queries
from app.services.canonical_results import MaterializationError
from ingestion.medsl import STATE_FIPS

METRIC_NOTE = ("Shares use the sum of published candidate and anonymous vote buckets in each unit. "
    "Margin is the top two named candidates' vote difference shown as a percentage of that same total. "
    "Partial publications may omit returns. No turnout or electoral-vote metric is calculated.")
SOURCE_NOTE = ("Published state authority totals and canonical reporting-unit returns are separate sources. "
    "They may not reconcile and must not be added together. The source panels identify the publications used.")

# Exact, election-scoped FEC summary buckets. These display labels are not person
# matching or canonical affiliations. Sources: the pinned presidential state
# workbook catalog and the separately reviewed FEC 2008 presidential publication.
PRESIDENTIAL_BUCKET_PARTIES = {
    2000: {'AL GORE': 'DEMOCRATIC', 'GEORGE W. BUSH': 'REPUBLICAN'},
    2004: {'JOHN KERRY': 'DEMOCRATIC', 'GEORGE W. BUSH': 'REPUBLICAN'},
    2008: {'BARACK OBAMA': 'DEMOCRATIC', 'JOHN MCCAIN': 'REPUBLICAN'},
    2012: {'BARACK OBAMA': 'DEMOCRATIC', 'MITT ROMNEY': 'REPUBLICAN'},
    2016: {'HILLARY CLINTON': 'DEMOCRATIC', 'DONALD TRUMP': 'REPUBLICAN'},
    2020: {'JOE BIDEN': 'DEMOCRATIC', 'DONALD TRUMP': 'REPUBLICAN'},
    2024: {'KAMALA HARRIS': 'DEMOCRATIC', 'DONALD TRUMP': 'REPUBLICAN'},
}


def _add_source_party_labels(session: Session, rows: list[dict]) -> None:
    """Use only the observations behind these published returns, in one lookup."""
    ids = {value for row in rows for value in row.get('observation_ids', [])}
    labels = {str(identifier): label for identifier, label in session.execute(
        select(ElectionResultObservation.id, ElectionResultObservation.party_normalized)
        .where(ElectionResultObservation.id.in_(ids))) if label} if ids else {}
    for row in rows:
        row['party_labels'] = sorted({labels[str(value)] for value in row.get('observation_ids', [])
                                      if str(value) in labels})


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return dict(status="no_results", total_votes=None, leader=None, margin_votes=None, margin_pp=None, candidates=[])
    total = sum(row["votes"] for row in rows)
    if any(row["votes"] < 0 for row in rows):
        raise MaterializationError("Negative map votes")
    candidates = [dict(row, share=row["votes"] / total * 100 if total else None) for row in rows]
    candidates.sort(key=lambda row: (-row["votes"], row["label"]))
    result = dict(status="zero_total" if not total else "indeterminate", total_votes=total,
                  leader=None, margin_votes=None, margin_pp=None, candidates=candidates)
    named = [row for row in candidates if row["kind"] in {"candidate", "source_candidate"}]
    anonymous = [row for row in candidates if row["kind"] not in {"candidate", "source_candidate"}]
    # An aggregate bucket could conceal the runner-up. Do not invent a margin.
    if total and len(named) >= 2 and sum(row["votes"] for row in anonymous) <= named[1]["votes"]:
        margin = named[0]["votes"] - named[1]["votes"]
        result.update(status="available" if margin else "tie", leader=named[0]["label"] if margin else None,
                      margin_votes=margin, margin_pp=margin / total * 100)
    return result


def load_boundaries(state_code: str | None, year: int = 2008,
                    reporting_level: str | None = None) -> tuple[dict | None, list[dict]]:
    root = Path(os.getenv("BOUNDARY_DATA_DIR", "data/boundaries"))
    manifest_path = root / f"{year}.json"
    if not manifest_path.exists():
        return None, []
    try:
        manifest = json.loads(manifest_path.read_text())
        if manifest["version"] != f"tiger{year}-display-v1" or manifest["year"] != year:
            raise ValueError("Unsupported boundary vintage")
        level = reporting_level or ('county' if state_code else 'state')
        if level not in manifest.get('reporting_levels', ['state', 'county', 'congressional_district']):
            return None, []
        key = f"{level}:{state_code}" if state_code and level != 'state' else level
        if level == 'congressional_district' and key not in manifest['outputs']:
            return None, []  # A county package cannot stand in for district boundaries.
        item = manifest["outputs"][key]
        digest = item["object"]
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("Invalid boundary object")
        raw = (root / "objects" / f"{digest}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Boundary checksum differs")
        collection = json.loads(raw)
        features = collection["features"]
        if len(features) != item["count"] or len({f["id"] for f in features}) != len(features):
            raise ValueError("Boundary count differs")
        codes = {fips: code for code, fips in STATE_FIPS.items()}
        for feature in features:
            props = feature['properties']
            geoid = props['geoid']
            if (not isinstance(geoid, str) or not geoid.isdigit() or
                len(geoid) != {'state': 2, 'county': 5, 'congressional_district': 4}[level] or
                feature['id'] != geoid or codes.get(geoid[:2]) != props['state_code'] or
                feature['geometry']['type'] not in {'Polygon','MultiPolygon'}):
                raise ValueError('Boundary GEOID, state or grain differs')
        if state_code and level == 'state':
            features = [f for f in features if f['properties']['state_code'] == state_code]
        metadata = {k: v for k, v in manifest.items() if k not in {'outputs', 'layers'}}
        if 'layers' in manifest:
            layer = manifest['layers'][level]
            if layer['year'] != year or layer['version'] != manifest['version'] or level not in layer['reporting_levels']:
                raise ValueError('Boundary layer has an incompatible year or grain')
            metadata.update(layer)
        metadata.update(display_sha256=item["sha256"], repaired_features=item["repaired"])
        return metadata, features
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise MaterializationError("Boundary package failed integrity validation") from exc


def _all_rows(session: Session, selection: MapFilters, reporting_level: str) -> list[dict]:
    model = ElectionFilters if reporting_level == 'state' else ResultFilters
    params = dict(year=selection.year, office=selection.office, stage=selection.stage,
                  state_code=selection.state_code, limit=200)
    if reporting_level != 'state':
        params['reporting_level'] = reporting_level
    filters = model(**params)
    query = election_queries.list_state_results if reporting_level == 'state' else election_queries.list_results
    rows = []
    while True:
        page = query(session, filters)
        rows.extend(page["items"])
        if not page["has_more"]:
            if reporting_level != 'state':
                _add_source_party_labels(session, rows)
            return rows
        filters = filters.model_copy(update={"offset": filters.offset + filters.limit})


def build_map(session: Session, filters: MapFilters) -> dict:
    office = filters.office.strip().casefold()
    federal_levels = {'u.s. president': 'county' if filters.state_code else 'state',
                      'president of the united states': 'county' if filters.state_code else 'state',
                      'u.s. house': 'congressional_district', 'u.s. senate': 'state'}
    level = filters.reporting_level or federal_levels.get(office, 'state')
    response = dict(year=filters.year, office=filters.office, stage=filters.stage,
        reporting_level=level, state_code=filters.state_code, selected_jurisdiction_id=filters.jurisdiction_id,
        drill_down_level='county' if level == 'state' and office in {'u.s. president', 'president of the united states'} else None,
        availability="unsupported_selection", boundary=None, features=dict(type="FeatureCollection", features=[]),
        units=[], publications=[], coverage=dict(boundary_units=0, units_with_results=0, missing_results=0,
                                               results_without_geometry=0),
        metric_note=METRIC_NOTE, source_note=SOURCE_NOTE)
    if office not in federal_levels or (level == 'county' and not filters.state_code):
        return response
    boundary, features = load_boundaries(filters.state_code, filters.year, level)
    rows = _all_rows(session, filters, level)
    groups = defaultdict(list)
    contexts = {}
    publications = {}
    parties = {}
    state_geoids = {}
    for row in rows:
        jurisdiction = row["jurisdiction"]
        if jurisdiction['state_code'] not in STATE_FIPS or jurisdiction['level'] != level:
            raise MaterializationError('Result reporting unit has an incompatible state or level')
        if level != "state":
            for party_id in row.get('party_ids', []):
                if party_id not in parties:
                    party = session.get(PoliticalParty, party_id)
                    if party:
                        parties[party_id] = party.name
            reference = session.get(GeographicReference, row["geographic_reference_id"])
            if (reference is None or reference.kind != level or
                reference.jurisdiction_id != jurisdiction["id"] or
                reference.state_fips != STATE_FIPS[jurisdiction['state_code']] or
                not reference.geoid.startswith(reference.state_fips) or
                len(reference.geoid) != {'county': 5, 'congressional_district': 4}[level] or
                not reference.vintage_start <= filters.year <= reference.vintage_end):
                raise MaterializationError("Map reference does not match result geography")
            geoid = reference.geoid
            candidate = dict(label=row["label"], votes=row["votes"], kind=row["candidate_kind"],
                party_labels=sorted(set(row.get('party_labels', [])) |
                                    {parties[p] for p in row.get("party_ids", []) if p in parties}),
                candidacy_id=row["candidacy_id"], geographic_reference_id=row["geographic_reference_id"],
                reference_vintage_start=reference.vintage_start, reference_vintage_end=reference.vintage_end,
                observation_ids=row["observation_ids"], correction_ids=row["correction_ids"])
        else:
            # Resolve the actual canonical jurisdiction, not a state-code-only paint join.
            if jurisdiction['id'] not in state_geoids:
                state_geoids[jurisdiction['id']] = set(session.scalars(select(GeographicReference.geoid).where(
                    GeographicReference.jurisdiction_id == jurisdiction['id'],
                    GeographicReference.kind == 'state',
                    GeographicReference.vintage_start <= filters.year,
                    GeographicReference.vintage_end >= filters.year)))
            references = state_geoids[jurisdiction['id']]
            if references and references != {STATE_FIPS[jurisdiction['state_code']]}:
                raise MaterializationError('State reference differs from published jurisdiction')
            geoid = next(iter(references)) if references else None
            party = (PRESIDENTIAL_BUCKET_PARTIES.get(filters.year, {}).get(row['candidate_bucket'])
                     if office in {'u.s. president', 'president of the united states'} and filters.stage == 'general' else None)
            candidate = dict(label=row["candidate_bucket"], votes=row["votes"], kind=row["bucket_kind"],
                             party_labels=[party] if party else [])
        key = geoid or f"jurisdiction:{jurisdiction['id']}"
        context = (jurisdiction["id"], row["contest_id"], row["publication"]["batch_id"])
        if key in contexts and contexts[key][0] != context:
            raise MaterializationError("Multiple result scopes target one map unit")
        contexts[key] = (context, jurisdiction, geoid)
        groups[key].append(candidate)
        publications[row["publication"]["batch_id"]] = row["publication"]
    units = {}
    for feature in features:
        props = feature["properties"]
        geoid = feature["id"]
        units[geoid] = dict(id=geoid, geoid=geoid, name=props["name"], state_code=props["state_code"],
            jurisdiction_id=None, contest_id=None, publication_batch_id=None, has_geometry=True,
            geometry_match='boundary_only', summary=summarize([]))
    if level == 'congressional_district' and any(key not in groups for key in units):
        # Missing-vote contests still need a canonical identity and race link.
        contests = election_queries.list_contests(session, ElectionFilters(
            year=filters.year, office=filters.office, stage=filters.stage,
            state_code=filters.state_code, limit=200))
        contest_rows = list(contests['items'])
        while contests['has_more']:
            contests = election_queries.list_contests(session, ElectionFilters(
                year=filters.year, office=filters.office, stage=filters.stage,
                state_code=filters.state_code, limit=200, offset=contests['offset'] + 200))
            contest_rows.extend(contests['items'])
        for contest in contest_rows:
            refs = session.scalars(select(GeographicReference).where(
                GeographicReference.jurisdiction_id == contest['jurisdiction']['id'],
                GeographicReference.kind == level,
                GeographicReference.vintage_start == filters.year,
                GeographicReference.vintage_end == filters.year)).all()
            for ref in refs:
                if ref.geoid in units and ref.geoid not in groups:
                    if units[ref.geoid]['contest_id'] not in {None, contest['id']}:
                        raise MaterializationError('Multiple contests target a missing-result district')
                    units[ref.geoid].update(jurisdiction_id=ref.jurisdiction_id, contest_id=contest['id'])
    for key, candidates in groups.items():
        (jurisdiction_id, contest_id, batch_id), jurisdiction, geoid = contexts[key]
        matched = key in units
        if matched and units[key]['state_code'] != jurisdiction['state_code']:
            raise MaterializationError('Display boundary state differs from result state')
        units[key] = dict(id=key, geoid=geoid, name=jurisdiction["name"],
            state_code=jurisdiction["state_code"], jurisdiction_id=jurisdiction_id, contest_id=contest_id,
            publication_batch_id=batch_id, has_geometry=matched,
            geometry_match='matched' if matched else 'missing_reference' if geoid is None else 'missing_geometry',
            summary=summarize(candidates))
    # Stamp each feature with its verified canonical identity for presentation joins.
    features = [dict(feature, properties=dict(feature['properties'], reporting_level=level,
        jurisdiction_id=units[feature['id']]['jurisdiction_id'])) for feature in features]
    if filters.jurisdiction_id and not any(u["jurisdiction_id"] == filters.jurisdiction_id for u in units.values()):
        # An arbitrary UUID must not silently fall back to the entire state.
        response.update(availability="no_matching_published_results", boundary=boundary)
        return response
    response.update(availability="boundaries_unavailable" if boundary is None else
        "available" if rows else "no_matching_published_results", boundary=boundary,
        features=dict(type="FeatureCollection", features=features),
        units=sorted(units.values(), key=lambda u: (u["name"], u["id"])),
        publications=list(publications.values()), coverage=dict(boundary_units=len(features),
            units_with_results=len(groups), missing_results=sum(u["summary"]["status"] == "no_results" for u in units.values()),
            results_without_geometry=sum(not u["has_geometry"] for u in units.values())))
    return response
