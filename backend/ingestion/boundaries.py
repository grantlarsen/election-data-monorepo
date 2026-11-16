"""Reproducible Census display packages; never modify canonical geography/results.

Run with ``python -m ingestion.boundaries``. Raw archives use the existing
content-addressed acquisition cache. PostGIS validates, transforms and simplifies
polygons; the final manifest is published atomically only after all files pass.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ingestion.medsl import STATE_FIPS
from ingestion.source import SourceInfo, acquire, atomic_json, sha256_file

VERSION = "tiger2008-display-v1"
DOCUMENTATION = "https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2008/TGRSHP08.pdf"
SOURCES = {
    "state": "7e384585322cf39de8bfac2723c5cbba709da65050cee51ebe16460bcb007a8e",
    "county": "956511da5ad39ca31ed3134c7beb0d26092ab647995a5db75920234a19eeba21",
}


def encode(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def prepare(connection: Connection, *, data_dir: Path, output: Path) -> dict:
    import shapefile  # Optional ingestion dependency, not required by the API.

    groups = defaultdict(list)
    sources = []
    repairs = defaultdict(int)
    excluded = defaultdict(int)
    fips_to_state = {value: key for key, value in STATE_FIPS.items()}
    for file_id, (level, expected) in enumerate(SOURCES.items(), 1):
        filename = f"tl_2008_us_{level}.zip"
        url = f"https://www2.census.gov/geo/tiger/TIGER2008/{filename}"
        info = SourceInfo("census_tiger_boundaries", "", "2008", file_id, filename,
                          url, None, None, {"vintage": 2008, "level": level})
        acquired = acquire(SimpleNamespace(key=info.source_name, describe=lambda: info), data_dir)
        if acquired.sha256 != expected:
            raise ValueError(f"Pinned Census {level} archive checksum differs")
        sources.append(dict(level=level, url=url, sha256=expected,
                            retrieved_at=acquired.retrieved_at.isoformat()))
        with ZipFile(acquired.path) as archive:
            stem = filename[:-4]
            projection = archive.read(stem + ".prj").decode()
            if "North_American_1983" not in projection or "Degree" not in projection:
                raise ValueError("Expected Census geographic NAD83 coordinates")
            reader = shapefile.Reader(shp=io.BytesIO(archive.read(stem + ".shp")),
                                      shx=io.BytesIO(archive.read(stem + ".shx")),
                                      dbf=io.BytesIO(archive.read(stem + ".dbf")), encoding="latin1")
            for record in reader.iterShapeRecords():
                attrs = record.record.as_dict()
                state_code = fips_to_state.get(attrs["STATEFP"])
                if state_code is None:
                    excluded[level] += 1  # Territories are outside the presidential scope.
                    continue
                geoid = attrs["STATEFP"] + (attrs["COUNTYFP"] if level == "county" else "")
                raw = json.dumps(record.shape.__geo_interface__)
                # Report every repair. Precision reduction avoids invalid ring rounding.
                row = connection.execute(text("""
                    WITH original AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:raw),4269) g),
                    display AS (SELECT ST_IsValid(g) original_valid,
                      ST_ReducePrecision(ST_SimplifyPreserveTopology(ST_Transform(
                        ST_CollectionExtract(ST_MakeValid(g),3),4326),0.005),0.00001) g
                      FROM original)
                    SELECT original_valid, ST_IsValid(g) valid, ST_IsEmpty(g) empty,
                           ST_AsGeoJSON(g,5)::json geometry FROM display
                """), {"raw": raw}).mappings().one()
                if not row["valid"] or row["empty"] or row["geometry"]["type"] not in {"Polygon", "MultiPolygon"}:
                    raise ValueError(f"Invalid display polygon: {geoid}")
                key = "state" if level == "state" else f"county:{state_code}"
                repairs[key] += int(not row["original_valid"])
                groups[key].append(dict(type="Feature", id=geoid, geometry=row["geometry"],
                    properties=dict(geoid=geoid, name=attrs["NAME"], state_code=state_code)))
    if len(groups["state"]) != 51 or any(f"county:{code}" not in groups for code in STATE_FIPS):
        raise ValueError("Boundary package lacks states/DC or county files")
    outputs = {}
    for key, features in sorted(groups.items()):
        features.sort(key=lambda feature: feature["id"])
        if len({feature["id"] for feature in features}) != len(features):
            raise ValueError(f"Duplicate Census identifiers: {key}")
        payload = encode(dict(type="FeatureCollection", features=features))
        digest = hashlib.sha256(payload).hexdigest()
        target = output / "objects" / f"{digest}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            # Identical concurrent builders write identical content to this object.
            atomic_json(target, json.loads(payload))
        elif encode(json.loads(target.read_text())) != payload:
            raise ValueError("Boundary object failed verification")
        # atomic_json uses pretty JSON, so pin its actual serialized bytes.
        file_digest = sha256_file(target)
        outputs[key] = dict(object=digest, sha256=file_digest, count=len(features), repaired=repairs[key])
    manifest = dict(version=VERSION, year=2008, boundary_vintage="2008-01-01",
        vintage_note="Census 2008 current geography; generally January 1, 2008. Not a certification of election-day boundaries.",
        documentation_url=DOCUMENTATION, crs="EPSG:4326", source_crs="EPSG:4269",
        simplification_degrees=0.005, precision_degrees=0.00001,
        sources=sources, excluded_territory_features=dict(excluded), outputs=outputs)
    path = output / "2008.json"
    unchanged = path.exists() and json.loads(path.read_text()) == manifest
    if not unchanged:
        atomic_json(path, manifest)
    return dict(status="unchanged" if unchanged else "prepared", states=51,
                counties=sum(len(v) for k, v in groups.items() if k != "state"),
                repaired=sum(repairs.values()), manifest=str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/ingestion"))
    parser.add_argument("--output", type=Path, default=Path("data/boundaries"))
    args = parser.parse_args()
    from app.database import engine
    with engine.connect() as connection:
        print(json.dumps(prepare(connection, data_dir=args.data_dir, output=args.output)))


if __name__ == "__main__":
    main()
