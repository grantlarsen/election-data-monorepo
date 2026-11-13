"""MEDSL-specific parsing and conservative canonical label normalization."""
from __future__ import annotations

import polars as pl

YEARS = frozenset(range(2000, 2025, 4))
STATE_FIPS: dict[str, str] = {
    "AL":"01","AK":"02","AZ":"04","AR":"05","CA":"06","CO":"08","CT":"09","DE":"10",
    "DC":"11","FL":"12","GA":"13","HI":"15","ID":"16","IL":"17","IN":"18","IA":"19",
    "KS":"20","KY":"21","LA":"22","ME":"23","MD":"24","MA":"25","MI":"26","MN":"27",
    "MS":"28","MO":"29","MT":"30","NE":"31","NV":"32","NH":"33","NJ":"34","NM":"35",
    "NY":"36","NC":"37","ND":"38","OH":"39","OK":"40","OR":"41","PA":"42","RI":"44",
    "SC":"45","SD":"46","TN":"47","TX":"48","UT":"49","VT":"50","VA":"51","WA":"53",
    "WV":"54","WI":"55","WY":"56",
}
STATE_NAMES: dict[str, str] = {
    "AL":"ALABAMA","AK":"ALASKA","AZ":"ARIZONA","AR":"ARKANSAS","CA":"CALIFORNIA",
    "CO":"COLORADO","CT":"CONNECTICUT","DE":"DELAWARE","DC":"DISTRICT OF COLUMBIA",
    "FL":"FLORIDA","GA":"GEORGIA","HI":"HAWAII","ID":"IDAHO","IL":"ILLINOIS",
    "IN":"INDIANA","IA":"IOWA","KS":"KANSAS","KY":"KENTUCKY","LA":"LOUISIANA",
    "ME":"MAINE","MD":"MARYLAND","MA":"MASSACHUSETTS","MI":"MICHIGAN","MN":"MINNESOTA",
    "MS":"MISSISSIPPI","MO":"MISSOURI","MT":"MONTANA","NE":"NEBRASKA","NV":"NEVADA",
    "NH":"NEW HAMPSHIRE","NJ":"NEW JERSEY","NM":"NEW MEXICO","NY":"NEW YORK",
    "NC":"NORTH CAROLINA","ND":"NORTH DAKOTA","OH":"OHIO","OK":"OKLAHOMA",
    "OR":"OREGON","PA":"PENNSYLVANIA","RI":"RHODE ISLAND","SC":"SOUTH CAROLINA",
    "SD":"SOUTH DAKOTA","TN":"TENNESSEE","TX":"TEXAS","UT":"UTAH","VT":"VERMONT",
    "VA":"VIRGINIA","WA":"WASHINGTON","WV":"WEST VIRGINIA","WI":"WISCONSIN",
    "WY":"WYOMING",
}
REQUIRED = frozenset({"year", "state", "state_po", "county_name", "county_fips", "office", "candidate", "party", "candidatevotes", "totalvotes", "version"})
OPTIONAL = frozenset({"mode"})
PARTY_MAP = {"DEMOCRAT": "DEMOCRATIC", "DEMOCRATIC": "DEMOCRATIC", "REPUBLICAN": "REPUBLICAN",
             "LIBERTARIAN": "LIBERTARIAN", "GREEN": "GREEN", "OTHER": "OTHER", "INDEPENDENT": "INDEPENDENT"}
AGGREGATES = {"OTHER", "OTHERS", "OTHER CANDIDATES", "NONE OF THESE CANDIDATES", "BLANK", "OVERVOTES", "UNDERVOTES", "TOTAL"}
WRITE_INS = {"WRITEIN", "WRITE-IN", "WRITE IN", "WRITE-INS", "WRITE INS", "SCATTERING", "WRITEIN VOTES"}
# MEDSL sometimes encodes unavailable numeric values with an explicit text marker.
# This allowlist is intentionally narrow: typos and malformed numeric text stay errors.
MISSING_NUMERIC_MARKERS = frozenset({"", "NA", "N/A", "NULL"})


class SchemaError(ValueError):
    pass


def _upper(name: str) -> pl.Expr:
    return pl.col(name).str.strip_chars().str.replace_all(r"\s+", " ").str.to_uppercase()


def parse_csv(path: str) -> pl.DataFrame:
    # Every original column stays a string so blank values, labels, and zero-prefixed FIPS are preserved.
    try:
        frame = pl.read_csv(path, infer_schema_length=0, try_parse_dates=False, ignore_errors=False)
    except Exception as exc:
        raise SchemaError(f"Cannot parse CSV as MEDSL observations: {exc}") from exc
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise SchemaError(f"MEDSL missing required columns: {sorted(missing)}")
    if not frame.height:
        raise SchemaError("MEDSL CSV contains zero observations")
    return frame.with_row_index("source_row_number", offset=2)


def normalize(raw: pl.DataFrame) -> pl.DataFrame:
    df = raw
    if "mode" not in df.columns:
        df = df.with_columns(pl.lit(None, dtype=pl.String).alias("mode"))
    # Preserve exact input columns separately in a struct, before modifications.
    raw_columns = [c for c in df.columns if c != "source_row_number"]
    df = df.with_columns(pl.struct(raw_columns).alias("raw_json"))
    df = df.with_columns(
        _upper("state_po").alias("state_code"),
        _upper("candidate").alias("candidate_normalized"),
        _upper("county_name").alias("county_normalized"),
        _upper("party").alias("party_key"),
        _upper("mode").alias("mode_normalized"),
        pl.col("year").str.strip_chars().cast(pl.Int32, strict=False).alias("year_int"),
        pl.col("candidatevotes").str.strip_chars().cast(pl.Int64, strict=False).alias("votes_int"),
        pl.col("totalvotes").str.strip_chars().cast(pl.Int64, strict=False).alias("total_int"),
        (pl.col("candidatevotes").is_null() |
         pl.col("candidatevotes").str.strip_chars().str.to_uppercase()
         .is_in(list(MISSING_NUMERIC_MARKERS))).fill_null(True)
         .alias("candidate_votes_missing_marker"),
        (pl.col("totalvotes").is_null() |
         pl.col("totalvotes").str.strip_chars().str.to_uppercase()
         .is_in(list(MISSING_NUMERIC_MARKERS))).fill_null(True)
         .alias("total_votes_missing_marker"),
    )
    # Values such as 1001 or 01001.0 may occur in source exports; do NOT guess codes from invalid input.
    df = df.with_columns(
        pl.col("state_code").replace_strict(STATE_FIPS, default=None).alias("state_fips"),
        pl.col("state_code").replace_strict(STATE_NAMES, default=None).alias("state_name_expected"),
        _upper("state").alias("state_normalized"),
        pl.col("party_key").replace_strict(PARTY_MAP, default=pl.col("party_key")).alias("party_normalized"),
        pl.when(pl.col("county_fips").str.contains(r"^\d{1,5}$"))
          .then(pl.col("county_fips").str.pad_start(5, "0"))
          .otherwise(None)
          .alias("county_fips_normalized"),
        pl.when(pl.col("candidate_normalized").is_in(list(WRITE_INS))).then(pl.lit("write_in"))
          .when(pl.col("candidate_normalized").is_in(list(AGGREGATES))).then(pl.lit("aggregate"))
          .when(pl.col("candidate_normalized").is_null() | (pl.col("candidate_normalized") == ""))
          .then(pl.lit("unresolved"))
          .otherwise(pl.lit("candidate")).alias("candidate_kind"),
    )
    return df
