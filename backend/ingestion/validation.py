"""Vectorized validation; every rejected CSV record remains reviewable."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from ingestion.medsl import OPTIONAL, REQUIRED, YEARS


@dataclass
class ValidationOutcome:
    issues: list[dict[str, Any]] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejections and not any(i["severity"] == "ERROR" for i in self.issues)

    def add(self, code: str, severity: str, frame: pl.DataFrame, description: str) -> None:
        if frame.height:
            self.issues.append({"code": code, "severity": severity, "count": frame.height,
                                "description": description,
                                "sample_rows": frame.get_column("source_row_number").head(5).to_list() if "source_row_number" in frame.columns else []})


def validate(df: pl.DataFrame, expected_years: set[int], *, state_totals_csv: Path | None = None) -> ValidationOutcome:
    result = ValidationOutcome()
    if not df.height:
        result.issues.append({"code":"EMPTY_SELECTION", "severity":"ERROR", "count":0, "description":"No rows for requested years", "sample_rows":[]})
        return result
    extra_columns = set(df.get_column("raw_json")[0].keys()) - REQUIRED - OPTIONAL
    if extra_columns:
        result.issues.append({"code":"UNEXPECTED_SOURCE_COLUMNS", "severity":"WARNING", "count":len(extra_columns),
                              "description":f"Additional original columns retained: {sorted(extra_columns)}", "sample_rows":[]})
    # Each structural invalidity is recorded with the complete unmodified row.
    checks: dict[str, pl.Expr] = {
        "INVALID_YEAR": pl.col("year_int").is_null() | ~pl.col("year_int").is_in(list(YEARS)),
        "INVALID_STATE": pl.col("state_fips").is_null(),
        # Only explicit missing-value markers are warnings. All other nonnumeric
        # strings, integer overflows, and negative totals remain hard errors.
        "INVALID_CANDIDATE_VOTES": (
            (pl.col("votes_int").is_null() & ~pl.col("candidate_votes_missing_marker")) |
            (pl.col("votes_int") < 0)
        ).fill_null(False),
        "INVALID_TOTAL_VOTES": (
            (pl.col("total_int").is_null() & ~pl.col("total_votes_missing_marker")) |
            (pl.col("total_int") < 0)
        ).fill_null(False),
        "MISSING_COUNTY_NAME": pl.col("county_name").is_null() | (pl.col("county_name").str.strip_chars() == ""),
        "INVALID_OFFICE": ~pl.col("office").str.to_uppercase().str.strip_chars().is_in(["US PRESIDENT", "PRESIDENT"]),
    }
    marked = df.with_columns([expr.fill_null(True).alias("_" + code) for code, expr in checks.items()])
    invalid_expr = pl.any_horizontal([pl.col("_" + code) for code in checks])
    for code in checks:
        bad = marked.filter(pl.col("_" + code))
        result.add(code, "ERROR", bad, f"Invalid mandatory field: {code}")
    invalid = marked.filter(invalid_expr).select(["source_row_number", "raw_json"] + ["_" + c for c in checks]).to_dicts()
    for row in invalid:
        result.rejections.append({"source_row_number": row["source_row_number"], "raw_json": row["raw_json"],
                                  "reasons_json": [c for c in checks if row["_" + c]]})

    # Non-fatal: special jurisdictions, missing vote components, missing/invalid FIPS, unknown party labels.
    result.add("MISSING_VOTE_COMPONENT", "WARNING", df.filter(pl.col("votes_int").is_null() &
               pl.col("candidate_votes_missing_marker")),
               "Candidate vote count absent; retain NULL, never substitute zero")
    result.add("MISSING_TOTAL", "WARNING", df.filter(pl.col("total_int").is_null() &
               pl.col("total_votes_missing_marker")),
               "Total count absent; retain NULL")
    result.add("FIPS_UNRESOLVED", "WARNING", df.filter(pl.col("county_fips_normalized").is_null()),
               "Missing or malformed county FIPS; leave canonical jurisdiction unmatched")
    result.add("STATE_NAME_CODE_MISMATCH", "WARNING", df.filter(
               pl.col("state_normalized").is_not_null() &
               (pl.col("state_normalized") != pl.col("state_name_expected"))),
               "State name does not agree with state postal abbreviation")
    result.add("FIPS_STATE_MISMATCH", "WARNING", df.filter(pl.col("county_fips_normalized").is_not_null() &
               (pl.col("county_fips_normalized").str.slice(0, 2) != pl.col("state_fips"))),
               "County FIPS prefix does not match state postal code")
    result.add("MISSING_PARTY", "WARNING", df.filter(pl.col("party_normalized").is_null() | (pl.col("party_normalized") == "")),
               "Party designation missing; no inference made")
    result.add("MISSING_CANDIDATE", "WARNING", df.filter(pl.col("candidate_kind") == "unresolved"),
               "Unresolved candidate label; no person created")
    result.add("MISSING_VERSION", "WARNING", df.filter(pl.col("version").is_null() | (pl.col("version").str.strip_chars() == "")),
               "Per-row version missing")

    actual_years = set(df.get_column("year_int").drop_nulls().to_list())
    missing_years = expected_years - actual_years
    if missing_years:
        result.issues.append({"code":"MISSING_YEARS", "severity":"ERROR", "count":len(missing_years),
                              "description":f"No data for expected years {sorted(missing_years)}", "sample_rows":[]})

    keys = ["year_int", "state_code", "county_name", "county_fips", "candidate", "party", "mode"]
    duplicates = df.group_by(keys).agg(pl.len().alias("n"), pl.col("source_row_number").min().alias("source_row_number")).filter(pl.col("n") > 1)
    result.add("DUPLICATE_LOGICAL_KEY", "WARNING", duplicates,
               "Multiple source rows share a logical identity; all are preserved separately")

    grouping = ["year_int", "state_code", "county_name", "county_fips", "mode"]
    grouped = df.group_by(grouping).agg(
        pl.col("total_int").drop_nulls().n_unique().alias("distinct_totals"),
        pl.col("total_int").max().alias("reported_total"),
        pl.col("votes_int").sum().alias("sum_candidate_votes"),
        pl.col("source_row_number").min().alias("source_row_number"),
    )
    result.add("CONFLICTING_REPORTED_TOTALS", "WARNING", grouped.filter(pl.col("distinct_totals") > 1),
               "County-year-mode has multiple reported total-vote values")
    result.add("CANDIDATE_SUM_EXCEEDS_TOTAL", "WARNING", grouped.filter(pl.col("reported_total").is_not_null() &
               (pl.col("sum_candidate_votes") > pl.col("reported_total"))),
               "Candidate components exceed reported total; may indicate double-counting or overlapping modes")
    result.add("CANDIDATE_SUM_BELOW_TOTAL", "WARNING", grouped.filter(pl.col("reported_total").is_not_null() &
               (pl.col("sum_candidate_votes") < pl.col("reported_total"))),
               "Candidate components do not explain all votes; do not fabricate residual votes")
    # Fusion lines and historical identity changes may be legitimate, so they only warrant review.
    mixed_party = (df.filter((pl.col("candidate_kind") == "candidate") & pl.col("candidate_normalized").is_not_null())
                   .group_by(["year_int", "state_code", "candidate_normalized"])
                   .agg(pl.col("party_normalized").n_unique().alias("parties"),
                        pl.col("source_row_number").min().alias("source_row_number"))
                   .filter(pl.col("parties") > 1))
    result.add("CANDIDATE_MULTIPLE_PARTIES", "WARNING", mixed_party,
               "Candidate has multiple party lines in a state-year (fusion may be legitimate)")
    fips_by_name = (df.filter(pl.col("county_fips_normalized").is_not_null())
                    .group_by(["state_code", "county_name"])
                    .agg(pl.col("county_fips_normalized").n_unique().alias("n"),
                         pl.col("source_row_number").min().alias("source_row_number"))
                    .filter(pl.col("n") > 1))
    result.add("COUNTY_CODE_CHANGED", "WARNING", fips_by_name,
               "County label maps to multiple FIPS identifiers; investigate boundaries or source errors")
    names_by_fips = (df.filter(pl.col("county_fips_normalized").is_not_null())
                     .group_by(["state_code", "county_fips_normalized"])
                     .agg(pl.col("county_name").n_unique().alias("n"),
                          pl.col("source_row_number").min().alias("source_row_number"))
                     .filter(pl.col("n") > 1))
    result.add("COUNTY_LABEL_CHANGED", "WARNING", names_by_fips,
               "FIPS identifier maps to multiple labels; investigate renames, recodes or collisions")

    if state_totals_csv is not None:
        reference = pl.read_csv(state_totals_csv, infer_schema_length=0)
        if not {"year", "state_po", "totalvotes"}.issubset(reference.columns):
            raise ValueError("Reference state totals CSV requires year,state_po,totalvotes")
        reference = reference.select(pl.col("year").cast(pl.Int32, strict=False).alias("year_int"),
                                     pl.col("state_po").str.to_uppercase().alias("state_code"),
                                     pl.col("totalvotes").cast(pl.Int64, strict=False).alias("official_total"))
        # Modes can overlap. Prefer an explicit TOTAL mode; if absent, accept only
        # a county-year with exactly one reported mode. Never sum overlapping modes.
        geo = ["year_int", "state_code", "county_name", "county_fips"]
        with_preference = grouped.join(
            grouped.group_by(geo).agg(
                pl.col("mode").n_unique().alias("mode_count"),
                (pl.col("mode").str.to_uppercase() == "TOTAL").any().alias("has_total_mode")),
            on=geo, how="left")
        usable = with_preference.filter(
            (pl.col("has_total_mode") & (pl.col("mode").str.to_uppercase() == "TOTAL")) |
            (~pl.col("has_total_mode") & (pl.col("mode_count") == 1)))
        by_county = usable.group_by(["year_int", "state_code"]).agg(
            pl.col("reported_total").sum().alias("county_sum"))
        compare = by_county.join(reference, on=["year_int", "state_code"], how="inner")
        outside = compare.filter((pl.col("official_total") > 0) &
                                 (((pl.col("county_sum") - pl.col("official_total")).abs() /
                                  pl.col("official_total")) > 0.005))
        result.add("STATE_TOTAL_DISCREPANCY", "WARNING", outside,
                   "County aggregate differs >0.5% from provided independent state total")
    return result
