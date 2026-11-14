"""Official Census CBP/NES state and county reference tables.

These multi-year *product* ranges are NOT verified legal effective-date intervals.
CBP explicitly batches geography revisions; see docs/geography/STEP6.md.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl

from ingestion.medsl import STATE_FIPS
from ingestion.source import SourceInfo

CBP = "https://www2.census.gov/programs-surveys/cbp/technical-documentation/reference/state-county-geography-reference/"
NES = "https://www2.census.gov/programs-surveys/nonemployer-statistics/datasets/2022/historical-datasets/"
# Each source file is a versioned reference of a statistical publication series, not a legal gazette.
RELEASES = {
    2000: (1996, 2001, "georef96_01.txt", CBP, "cbp"),
    2004: (2002, 2011, "georef02.txt", CBP, "cbp"),
    2008: (2002, 2011, "georef02.txt", CBP, "cbp"),
    2012: (2012, 2016, "georef12.txt", CBP, "cbp"),
    2016: (2012, 2016, "georef12.txt", CBP, "cbp"),
    2020: (2017, 2021, "georef17.txt", CBP, "cbp"),
    2024: (2022, 2024, "georef2022.txt", NES, "nes"),
}


from ingestion.geography.rules import name_key


def parse_reference(path: Path) -> pl.DataFrame:
    """Parse both published official layouts using Polars, preserving raw names."""
    source = pl.read_csv(path, infer_schema_length=0, encoding="utf8-lossy", ignore_errors=False)
    layouts = [
        ("fipstate", "fipscty", "ctyname"),
        ("fipstate", "fipscty", "county_name"),  # 2017–2021 CBP
        ("st", "cty", "county_name"),
    ]
    fields = next((layout for layout in layouts if set(layout).issubset(source.columns)), None)
    if fields is None:
        raise ValueError(f"Unsupported Census reference layout: {source.columns}")
    frame = source.select(
        pl.col(fields[0]).cast(pl.String).str.strip_chars().alias("state_raw"),
        pl.col(fields[1]).cast(pl.String).str.strip_chars().alias("county_code_raw"),
        pl.col(fields[2]).cast(pl.String).str.strip_chars().alias("county_name_raw"),
    ).with_row_index("source_row_number", offset=2)
    frame = frame.with_columns(
        pl.when(pl.col("state_raw").str.contains(r"^\d{1,2}$"))
          .then(pl.col("state_raw").str.pad_start(2, "0"))
          .otherwise(None).alias("state_fips"),
        pl.when(pl.col("county_code_raw").str.contains(r"^\d{1,3}$"))
          .then(pl.col("county_code_raw").str.pad_start(3, "0"))
          .otherwise(None).alias("county_code"),
    ).with_columns(
        pl.concat_str(["state_fips", "county_code"]).alias("geoid"),
        pl.col("county_name_raw").map_elements(name_key, return_dtype=pl.String).alias("name_key"),
    )
    return frame


def validate_reference(frame: pl.DataFrame, *, require_complete: bool = True) -> dict:
    """Hard-fail malformed geography. 999 is deliberately a non-county reporting sentinel."""
    if not frame.height:
        raise ValueError("Empty Census geography reference")
    state_codes = set(STATE_FIPS.values())
    bad = frame.filter(
        pl.col("state_fips").is_null() | ~pl.col("state_fips").is_in(list(state_codes)) |
        pl.col("county_code").is_null() |
        pl.col("county_name_raw").is_null() | (pl.col("name_key") == "")
    )
    # Census products may include Puerto Rico; Step 6 covers 50 states + DC only.
    outside = frame.filter(pl.col("state_fips").is_not_null() &
                           ~pl.col("state_fips").is_in(list(state_codes)))
    malformed = bad.filter(pl.col("state_fips").is_null() |
                           pl.col("county_code").is_null() |
                           pl.col("county_name_raw").is_null() | (pl.col("name_key") == ""))
    if malformed.height:
        raise ValueError(f"Census reference has {malformed.height} malformed rows: {malformed.head(5).to_dicts()}")
    counties = frame.filter(pl.col("state_fips").is_in(list(state_codes)) &
                            (~pl.col("county_code").is_in(["000", "999"])))
    duplicates = counties.group_by("geoid").agg(pl.len().alias("n")).filter(pl.col("n") != 1)
    if duplicates.height:
        raise ValueError(f"Census reference has duplicate county GEOIDs: {duplicates.head(5).to_dicts()}")
    state_count = frame.filter(pl.col("state_fips").is_in(list(state_codes))).get_column("state_fips").n_unique()
    if require_complete and (counties.height < 3000 or state_count != 51):
        raise ValueError("Census geographic file appears partial; expected all 50 states and DC")
    return {"records_in_file": frame.height, "county_rows": counties.height,
            "excluded_999_or_nonstate": frame.height - counties.height,
            "outside_50_states_dc": outside.height,
            "distinct_states": state_count}


class Job:
    geographic_reference = True
    key = "census_state_county_georef"
    source_url = "https://www.census.gov/programs-surveys/cbp/technical-documentation/reference/state-county-geography-reference.html"
    supported_vintages = frozenset(RELEASES)

    def __init__(self, vintage: int | None = None):
        self.vintage = vintage

    @property
    def range(self) -> tuple[int, int]:
        if self.vintage not in RELEASES:
            raise ValueError(f"Specify --vintage from {sorted(RELEASES)}")
        first, last, *_ = RELEASES[self.vintage]
        return first, last

    def describe(self) -> SourceInfo:
        first, last, filename, base, series = RELEASES[self.vintage]
        return SourceInfo(
            source_name=self.key,
            doi=f"Census {series.upper()} geographic reference {filename}",
            version=f"{series}-{first}-{last}",
            file_id=first, filename=filename,
            download_url=f"{base}{filename}", expected_size=None,
            published_at=None,  # Publication date not exposed by these plaintext files.
            metadata={"provider": "U.S. Census Bureau", "series": series,
                      "vintage_start": first, "vintage_end": last,
                      "vintage_semantics": "statistical product reference range; NOT legal effective dates",
                      "source_page": self.source_url if series == "cbp" else
                      "https://www.census.gov/programs-surveys/nonemployer-statistics/technical-documentation/reference/state-county-geography-reference.html",
                      "file": filename, "license": "U.S. government public-domain data; attribution requested"},
        )

    def parse(self, path: Path) -> pl.DataFrame:
        return parse_reference(path)

    def validate(self, frame: pl.DataFrame) -> dict:
        return validate_reference(frame)

    def load(self, engine, source_id, run_id, asset, frame, validation, *, started_at=None) -> dict:
        from ingestion.geography.load import load_reference
        return load_reference(engine, source_id, run_id, asset, frame, validation, started_at=started_at)
