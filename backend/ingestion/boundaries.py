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
DISTRICT_SHA256 = "2b4238aed7e865df75d0c9cfcd8dffa1b79007b24519ecc4b213e683078b031a"
PRESIDENTIAL_YEARS = (2000, 2004, 2008, 2012, 2016, 2020, 2024)


def configuration(year: int, office: str) -> dict:
    """Pinned display sources; the requested election year is not a boundary date."""
    if office == 'president' and year == 2008:
        return dict(boundary_vintage='2008-01-01', documentation_url=DOCUMENTATION,
            vintage_note='Census 2008 current geography; generally January 1, 2008. Not a certification of election-day boundaries.',
            sources=[dict(level=level, sha256=digest, source_year=2008, file_id=index,
                filename=f'tl_2008_us_{level}.zip',
                url=f'https://www2.census.gov/geo/tiger/TIGER2008/tl_2008_us_{level}.zip')
                for index, (level, digest) in enumerate(SOURCES.items(), 1)])
    if office == 'house' and year == 2024:
        return dict(boundary_vintage='119th Congress / 2024 election',
            documentation_url='https://www.census.gov/geographies/mapping-files/2024/geo/carto-boundary-file.html',
            vintage_note='Census 2024 cartographic 119th congressional districts, 1:500,000. Display shapes, not measurements or reconstructed returns.',
            sources=[dict(level='congressional_district', sha256=DISTRICT_SHA256, source_year=2024, file_id=2024,
                filename='cb_2024_us_cd119_500k.zip',
                url='https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_cd119_500k.zip')])
    catalog = json.loads((Path(__file__).parent / 'catalog' / 'election_boundaries.json').read_text())
    if office != 'president' or str(year) not in catalog['presidential']:
        raise ValueError('Unsupported display year and office')
    return catalog['presidential'][str(year)]


def merge_manifest(existing: dict, prepared: dict) -> dict:
    """Replace only the prepared grains, preserving other same-year display layers."""
    if not existing:
        return prepared
    if existing['year'] != prepared['year'] or existing['version'] != prepared['version']:
        raise ValueError('Existing boundary manifest has an incompatible year/version')
    levels = set(prepared['reporting_levels'])
    previous = existing.get('reporting_levels', sorted({key.split(':')[0] for key in existing['outputs']}))
    if not set(previous) - levels and 'layers' not in existing:
        return prepared
    layers = dict(existing.get('layers', {level: {k: v for k, v in existing.items() if k != 'outputs'}
                                          for level in previous}))
    metadata = {k: v for k, v in prepared.items() if k != 'outputs'}
    layers.update({level: metadata for level in levels})
    outputs = {key: value for key, value in existing['outputs'].items() if key.split(':')[0] not in levels}
    outputs.update(prepared['outputs'])
    return dict(version=prepared['version'], year=prepared['year'],
        reporting_levels=sorted(set(previous) | levels), layers=layers, outputs=outputs)


def encode(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def prepare(connection: Connection, *, data_dir: Path, output: Path, year: int = 2008,
            office: str | None = None) -> dict:
    import shapefile  # Optional ingestion dependency, not required by the API.

    groups = defaultdict(list)
    sources = []
    repairs = defaultdict(int)
    excluded = defaultdict(int)
    fips_to_state = {value: key for key, value in STATE_FIPS.items()}
    office = office or ('house' if year == 2024 else 'president')
    config = configuration(year, office)
    selected_levels = list(dict.fromkeys(source['level'] for source in config['sources']))
    for spec in config['sources']:
        level, expected, filename, url = (spec[key] for key in ['level', 'sha256', 'filename', 'url'])
        info = SourceInfo("census_tiger_boundaries" if office == 'president' else "census_congressional_boundaries",
                          "", str(spec['source_year']), spec['file_id'], filename,
                          url, None, None, {"vintage": spec['source_year'], "level": level})
        acquired = acquire(SimpleNamespace(key=info.source_name, describe=lambda: info), data_dir)
        if acquired.sha256 != expected:
            raise ValueError(f"Pinned Census {level} archive checksum differs")
        source = dict(level=level, url=url, sha256=expected, retrieved_at=acquired.retrieved_at.isoformat())
        for key in ['include_states', 'exclude_states']:
            if key in spec:
                source[key] = spec[key]
        sources.append(source)
        with ZipFile(acquired.path) as archive:
            stem = filename[:-4]
            projection = archive.read(stem + ".prj").decode()
            if "North_American_1983" not in projection or "Degree" not in projection:
                raise ValueError("Expected Census geographic NAD83 coordinates")
            encoding = archive.read(stem + '.cpg').decode().strip() if stem + '.cpg' in archive.namelist() else 'latin1'
            reader = shapefile.Reader(shp=io.BytesIO(archive.read(stem + ".shp")),
                                      shx=io.BytesIO(archive.read(stem + ".shx")),
                                      dbf=io.BytesIO(archive.read(stem + ".dbf")), encoding=encoding)
            for record in reader.iterShapeRecords():
                attrs = record.record.as_dict()
                state_fips = attrs[spec.get('state_field', 'STATEFP')]
                state_code = fips_to_state.get(state_fips)
                if state_code is None:
                    excluded[level] += 1  # Territories are outside the presidential scope.
                    continue
                if (state_code in spec.get('exclude_states', []) or
                        ('include_states' in spec and state_code not in spec['include_states'])):
                    continue
                geoid = attrs['GEOID'] if level == 'congressional_district' else state_fips + (
                    attrs[spec.get('county_field', 'COUNTYFP')] if level == 'county' else '')
                if geoid.endswith("ZZ"):
                    excluded["undefined_district"] += 1
                    continue
                if (not isinstance(geoid, str) or not geoid.isdigit() or
                        len(geoid) != {'state': 2, 'county': 5, 'congressional_district': 4}[level] or
                        not geoid.startswith(state_fips)):
                    raise ValueError('Boundary GEOID, state or grain differs')
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
                key = "state" if level == "state" else f"{level}:{state_code}"
                repairs[key] += int(not row["original_valid"])
                groups[key].append(dict(type="Feature", id=geoid, geometry=row["geometry"],
                    properties=dict(geoid=geoid, name=attrs.get(spec.get('name_field', 'NAME')) or attrs.get("NAMELSAD") or geoid, state_code=state_code)))
    if office == 'president' and (len(groups["state"]) != 51 or any(f"county:{code}" not in groups for code in STATE_FIPS)):
        raise ValueError("Boundary package lacks states/DC or county files")
    if config.get('expected_counties') is not None and sum(len(v) for k, v in groups.items() if k.startswith('county:')) != config['expected_counties']:
        raise ValueError('County boundary count differs from pinned vintage')
    if office == 'house':
        if sum(len(v) for v in groups.values()) != 436 or len(groups) != 51:
            raise ValueError("Expected 435 voting districts and DC across 51 jurisdictions")
        groups["congressional_district"] = [f for values in list(groups.values()) for f in values]
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
    manifest = dict(version=f"tiger{year}-display-v1", year=year, reporting_levels=selected_levels,
        boundary_vintage=config['boundary_vintage'], vintage_note=config['vintage_note'],
        documentation_url=config['documentation_url'], crs="EPSG:4326", source_crs="EPSG:4269",
        simplification_degrees=0.005, precision_degrees=0.00001,
        sources=sources, excluded_territory_features=dict(excluded), outputs=outputs)
    path = output / f"{year}.json"
    if config.get('approximate'):
        manifest['approximate'] = True
    existing = json.loads(path.read_text()) if path.exists() else {}
    manifest = merge_manifest(existing, manifest)
    unchanged = existing == manifest
    if not unchanged:
        atomic_json(path, manifest)
    return dict(status="unchanged" if unchanged else "prepared", states=51,
                districts=len(groups.get("congressional_district", [])),
                counties=sum(len(v) for k, v in groups.items() if k.startswith("county:")),
                repaired=sum(repairs.values()), manifest=str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/ingestion"))
    parser.add_argument("--output", type=Path, default=Path("data/boundaries"))
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--year", type=int, choices=PRESIDENTIAL_YEARS)
    selection.add_argument('--all-presidential', action='store_true', help='Prepare all seven presidential state/county packages')
    parser.add_argument('--office', choices=['president', 'house'], help='Defaults to House for --year 2024, otherwise President')
    args = parser.parse_args()
    if args.all_presidential and args.office == 'house':
        parser.error('--all-presidential cannot be used with --office house')
    from app.database import engine
    with engine.connect() as connection:
        for year in PRESIDENTIAL_YEARS if args.all_presidential else [args.year or 2008]:
            print(json.dumps(prepare(connection, data_dir=args.data_dir, output=args.output, year=year,
                                    office='president' if args.all_presidential else args.office)), flush=True)


if __name__ == "__main__":
    main()
