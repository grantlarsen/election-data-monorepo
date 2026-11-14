"""Census 2000 national counties Gazetteer (official 2000-vintage supplement).

Retains the downloaded ZIP using the existing acquisition/cache/provenance layer.
Its fixed-width records follow the published Census 2000 Gazetteer record
layout. It is an independent release; it never overwrites CBP/NES references.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from zipfile import ZipFile

import polars as pl

from ingestion.geography.rules import name_key
from ingestion.source import SourceInfo
from ingestion.medsl import STATE_FIPS
from ingestion.adapters.census_state_county_georef import validate_reference

URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/county2k.zip"
SOURCE_PAGE = "https://www.census.gov/geographies/reference-files/2000/geo/gazetter-file.html"
LAYOUT_PAGE = "https://www.census.gov/programs-surveys/geography/technical-documentation/records-layout/gaz-record-layouts.2000.html"


def parse_counties(path: Path) -> pl.DataFrame:
    """Census layout: [0:2] USPS, [2:4] state, [4:7] county, [7:71] name."""
    with ZipFile(path) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        if len(names) != 1:
            raise ValueError(f"Expected one Census county text file, got {names}")
        raw = archive.read(names[0]).decode("latin-1")
    rows = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        if len(line) < 71:
            raise ValueError(f"Short Census 2000 county record at line {line_no}")
        state = line[2:4]
        county = line[4:7]
        label = line[7:71].strip()
        if (not state.isascii() or not state.isdecimal() or len(state) != 2
                or not county.isascii() or not county.isdecimal() or len(county) != 3
                or not label):
            raise ValueError(f"Malformed Census 2000 county record at line {line_no}")
        rows.append({"source_row_number": line_no, "state_raw": state,
                     "county_code_raw": county, "county_name_raw": label,
                     "state_fips": state, "county_code": county,
                     "geoid": state + county, "name_key": name_key(label)})
    if not rows:
        raise ValueError("Census 2000 counties Gazetteer was empty")
    return pl.DataFrame(rows)


class Job:
    geographic_reference = True
    key = "census_2000_counties_gazetteer"
    source_url = SOURCE_PAGE
    supported_vintages = frozenset({2000})

    def __init__(self, vintage: int | None = None):
        if vintage != 2000:
            raise ValueError("Census 2000 county Gazetteer requires --vintage 2000")

    def describe(self) -> SourceInfo:
        return SourceInfo(
            source_name=self.key, doi="Census 2000 National Counties Gazetteer",
            version="census-2000-counties-2000-01-01", file_id=2000,
            filename="county2k.zip", download_url=URL, expected_size=None,
            published_at=None,
            metadata={"provider": "U.S. Census Bureau", "series": "Census 2000 Gazetteer",
                      "vintage_start": 2000, "vintage_end": 2000,
                      "vintage_semantics": "Census 2000 geography as of January 1, 2000",
                      "source_page": SOURCE_PAGE, "record_layout_url": LAYOUT_PAGE,
                      "file": "county2k.zip", "license": "U.S. federal public-domain data"},
        )

    def parse(self, path: Path) -> pl.DataFrame:
        return parse_counties(path)

    def validate(self, frame: pl.DataFrame) -> dict:
        return validate_reference(frame)

    def load(self, engine, source_id, run_id, asset, frame, validation, *, started_at=None) -> dict:
        from ingestion.geography.load import load_reference
        return load_reference(engine, source_id, run_id, asset, frame, validation,
                              started_at=started_at)
