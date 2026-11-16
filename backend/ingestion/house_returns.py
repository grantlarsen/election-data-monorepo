"""Lossless MEDSL House parsing and conservative 2024 regular-election selection."""
from pathlib import Path
from uuid import UUID, uuid4

import polars as pl
from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ingestion.loader import _chunks, _hash
from ingestion.medsl import STATE_FIPS, STATE_NAMES, PARTY_MAP, MISSING_NUMERIC_MARKERS, WRITE_INS
from ingestion.validation import ValidationOutcome

RULESET = "medsl-house-2024-v1"
BOOLEAN_FIELDS = ("special", "runoff", "writein", "unofficial", "fusion_ticket")
REQUIRED = {"year", "state", "state_po", "state_fips", "office", "district", "stage",
            "candidate", "party", "mode", "candidatevotes", "totalvotes", "version", *BOOLEAN_FIELDS}
NON_VOTES = {"BLANK", "BLANKS", "BLANK VOTES", "VOID", "OVER VOTES", "UNDER VOTES",
             "OVERVOTES", "UNDERVOTES", "EXHAUSTED BALLOTS"}
UNNAMED_WRITE_INS = WRITE_INS | {"OTHER WRITE-INS"}
AGGREGATES = {"OTHER", "OTHERS", "ALL OTHERS", "MISCELLANEOUS", "INDEPENDENT", "WORKING FAMILIES"}


def upper(name: str) -> pl.Expr:
    return pl.col(name).fill_null("").str.strip_chars().str.replace_all(r"\s+", " ").str.to_uppercase()


def parse(path: Path) -> pl.DataFrame:
    # Dataverse's V15 original .tab file is CSV, despite its declared MIME type.
    with path.open(encoding="utf-8-sig") as stream:
        header = stream.readline()
    frame = pl.read_csv(path, separator="\t" if "\t" in header else ",", infer_schema_length=0)
    if missing := REQUIRED - set(frame.columns):
        raise ValueError(f"MEDSL House missing required columns: {sorted(missing)}")
    if not frame.height:
        raise ValueError("MEDSL House file is empty")
    return frame.with_row_index("source_row_number", offset=2)


def normalize(frame: pl.DataFrame) -> pl.DataFrame:
    frame = frame.with_columns(pl.struct(pl.exclude("source_row_number")).alias("raw_json"))
    frame = frame.with_columns(
        upper("year").cast(pl.Int32, strict=False).alias("year_int"),
        upper("state_po").alias("state_code"),
        upper("district").str.pad_start(2, "0").alias("district_code"),
        upper("candidate").alias("candidate_normalized"), upper("party").alias("party_normalized"),
        upper("mode").alias("mode_normalized"), upper("stage").alias("stage_normalized"),
        upper("candidatevotes").alias("votes_text"), upper("totalvotes").alias("total_text"),
        *(upper(field).alias(field + "_normalized") for field in BOOLEAN_FIELDS),
    ).with_columns(
        pl.col("state_code").replace_strict(STATE_FIPS, default=None).alias("state_fips_normalized"),
        pl.col("party_normalized").replace(PARTY_MAP).alias("party_normalized"),
        # The paired (1,-1) unopposed sentinel is not one observed vote.
        ((pl.col("year_int") == 2024) &
         (((pl.col("state_code") == "FL") & (pl.col("district_code") == "20")) |
          ((pl.col("state_code") == "OK") & (pl.col("district_code") == "03"))) &
         (pl.col("votes_text") == "1") & (pl.col("total_text") == "-1")).alias("unopposed_placeholder"),
    ).with_columns(
        pl.when(pl.col("unopposed_placeholder")).then(None)
          .otherwise(pl.col("votes_text").cast(pl.Int64, strict=False)).alias("votes_int"),
        pl.when(pl.col("unopposed_placeholder")).then(None)
          .otherwise(pl.col("total_text").cast(pl.Int64, strict=False)).alias("total_int"),
        pl.when(pl.col("candidate_normalized").is_in(list(NON_VOTES | AGGREGATES))).then(pl.lit("aggregate"))
          .when(pl.col("candidate_normalized").is_in(list(UNNAMED_WRITE_INS))).then(pl.lit("write_in"))
          .when(pl.col("candidate_normalized").is_in(["", "NA", "N/A", "NULL"]))
          .then(pl.lit("unresolved")).otherwise(pl.lit("candidate")).alias("candidate_kind"),
    )
    return frame


def select_regular(frame: pl.DataFrame, years: set[int]) -> pl.DataFrame:
    invalid_year = pl.col("year_int").is_null() | ~pl.col("year_int").is_in(list(range(1976, 2025, 2)))
    invalid_selection = (~pl.col("stage_normalized").is_in(["GEN", "PRI", "RUNOFF"]) |
                         ~pl.col("special_normalized").is_in(["TRUE", "FALSE"]) |
                         ~pl.col("runoff_normalized").is_in(["TRUE", "FALSE"]))
    regular = ((pl.col("stage_normalized") == "GEN") & (pl.col("special_normalized") == "FALSE") &
               (pl.col("runoff_normalized") == "FALSE"))
    return frame.filter(invalid_year | (pl.col("year_int").is_in(sorted(years)) & (regular | invalid_selection)))


def validate(frame: pl.DataFrame, years: set[int]) -> ValidationOutcome:
    result = ValidationOutcome()
    checks = {
        "INVALID_YEAR": pl.col("year_int").is_null() | ~pl.col("year_int").is_in(sorted(years)),
        "INVALID_STATE": pl.col("state_fips_normalized").is_null() |
            (upper("state") != pl.col("state_code").replace_strict(STATE_NAMES, default="")) |
            (upper("state_fips").str.pad_start(2, "0") != pl.col("state_fips_normalized")),
        "INVALID_DISTRICT": ~pl.col("district_code").str.contains(r"^[0-9]{2}$"),
        "INVALID_OFFICE": upper("office") != "US HOUSE",
        "INVALID_STAGE": pl.col("stage_normalized") != "GEN",
        "INVALID_SPECIAL": pl.col("special_normalized") != "FALSE",
        "INVALID_RUNOFF": pl.col("runoff_normalized") != "FALSE",
    }
    for field in BOOLEAN_FIELDS:
        checks["INVALID_" + field.upper() + "_BOOLEAN"] = ~pl.col(field + "_normalized").is_in(["TRUE", "FALSE"])
    for field, text in (("votes", "votes_text"), ("total", "total_text")):
        checks["INVALID_" + field.upper()] = (~pl.col("unopposed_placeholder") &
            ((pl.col(field + "_int").is_null() & ~pl.col(text).is_in(list(MISSING_NUMERIC_MARKERS))) |
             (pl.col(field + "_int") < 0))).fill_null(False)
    reasons: dict[int, list[str]] = {}
    for code, condition in checks.items():
        bad = frame.filter(condition.fill_null(True))
        result.add(code, "ERROR", bad, code)
        for n in bad.get_column("source_row_number"):
            reasons.setdefault(n, []).append(code)
    for row in frame.filter(pl.col("source_row_number").is_in(list(reasons))).to_dicts():
        result.rejections.append(dict(source_row_number=row["source_row_number"],
            reasons_json=reasons[row["source_row_number"]], raw_json=row["raw_json"]))
    if set(frame.get_column("year_int").drop_nulls()) != years:
        result.issues.append(dict(code="MISSING_YEAR", severity="ERROR", count=1, description="Requested year absent"))
    result.add("MISSING_VOTES", "WARNING", frame.filter(pl.col("votes_int").is_null() | pl.col("total_int").is_null()),
               "Missing counts and known unopposed sentinels are retained as NULL, never imputed")
    return result


def records(frame: pl.DataFrame, release_id: UUID, party_ids: dict[str, UUID]) -> list[dict]:
    result = []
    for row in frame.to_dicts():
        result.append(dict(id=uuid4(), release_id=release_id, source_row_number=row["source_row_number"],
            row_sha256=_hash(row["raw_json"]), logical_key=_hash([row[k] for k in
                ("year_int", "state_code", "district_code", "stage_normalized", "special_normalized",
                 "runoff_normalized", "candidate_normalized", "party_normalized", "mode_normalized", "writein_normalized")]),
            year=row["year_int"], state_raw=row["state"], state_code_raw=row["state_po"],
            state_code=row["state_code"], state_fips=row["state_fips_normalized"],
            office_raw=row["office"], candidate_raw=row["candidate"],
            candidate_normalized=row["candidate_normalized"], candidate_kind=row["candidate_kind"],
            party_raw=row["party"], party_normalized=row["party_normalized"],
            mode_raw=row["mode"], mode_normalized=row["mode_normalized"], version_raw=row["version"],
            candidate_votes=row["votes_int"], total_votes=row["total_int"],
            party_id=party_ids.get(row["party_normalized"]), raw_json=row["raw_json"], warnings_json=flags(row)))
    return result


def flags(row: dict) -> list[str]:
    values = []
    if row["unopposed_placeholder"]:
        values.append("UNOPPOSED_VOTE_PLACEHOLDER")
    if row["votes_int"] is None or row["total_int"] is None:
        values.append("MISSING_VOTES")
    if row["candidate_normalized"] in NON_VOTES:
        values.append("NON_VOTE_CATEGORY")
    if row["state_code"] in {"AK", "ME"}:
        values.append("SOURCE_REPORTED_RCV_COUNTS")
    return values


def load_details(conn: Connection, release_id: UUID, frame: pl.DataFrame) -> None:
    from app.models.house_returns import HouseReturnDetail
    from app.models.ingestion import ElectionResultObservation as O
    ids = dict(conn.execute(select(O.source_row_number, O.id).where(O.release_id == release_id)).all())
    rows = [dict(observation_id=ids[r["source_row_number"]], district_code=r["district_code"],
                 stage=r["stage_normalized"], flags_json=flags(r),
                 **{f:r[f + "_normalized"] == "TRUE" for f in BOOLEAN_FIELDS}) for r in frame.to_dicts()]
    for chunk in _chunks(rows):
        conn.execute(pg_insert(HouseReturnDetail).values(chunk).on_conflict_do_nothing(index_elements=["observation_id"]))
