"""Lossless MEDSL Senate observations and evidence-backed contest scope rules."""
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import polars as pl
from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ingestion.house_returns import NON_VOTES as HOUSE_NON_VOTES, UNNAMED_WRITE_INS, upper
from ingestion.loader import _chunks, _hash
from ingestion.medsl import MISSING_NUMERIC_MARKERS, PARTY_MAP, STATE_FIPS, STATE_NAMES
from ingestion.validation import ValidationOutcome

RULESET = "medsl-senate-v1"
NON_VOTES = HOUSE_NON_VOTES | {"BLANK VOTE", "VOID VOTE", "OVER VOTE", "UNDER VOTE",
    "BLANK VOTE/SCATTERING", "BLANK VOTE/VOID VOTE/SCATTERING"}
AGGREGATES = {"OTHER", "OTHERS", "ALL OTHERS", "MISCELLANEOUS", "OTHER CANDIDATES",
    "NONE OF THE ABOVE", "NONE OF THESE CANDIDATES", "NONE OF THESE, CANDIDATES"}
WRITE_INS = UNNAMED_WRITE_INS | {"SCATTER"}
YEARS = frozenset(range(2000, 2025, 2)) | {2021}
BOOLEAN_FIELDS = ("special", "writein", "unofficial")
REQUIRED = {"year", "state", "state_po", "state_fips", "office", "district", "stage",
            "candidate", "party_detailed", "party_simplified", "mode", "candidatevotes",
            "totalvotes", "version", *BOOLEAN_FIELDS}
CLASS_STATES = {
    1: frozenset("AZ CA CT DE FL HI IN MA MD ME MI MN MO MS MT ND NE NJ NM NV NY OH PA RI TN TX UT VA VT WA WI WV WY".split()),
    2: frozenset("AK AL AR CO DE GA IA ID IL KS KY LA MA ME MI MN MS MT NC NE NH NJ NM OK OR RI SC SD TN TX VA WV WY".split()),
    3: frozenset("AK AL AR AZ CA CO CT FL GA HI IA ID IL IN KS KY LA MD MO NC ND NH NV NY OH OK OR PA SC SD UT VT WA WI".split()),
}
CLASS_URLS = {n: f"https://www.senate.gov/senators/Class_{roman}.htm"
              for n, roman in ((1, "I"), (2, "II"), (3, "III"))}
# Each special fills a particular state/class seat; never infer from the regular class.
# Historical seat succession evidence: https://www.senate.gov/states/{STATE}/senators.htm
SPECIAL_CLASSES = {
    (2000, "GA"): 3, (2002, "MO"): 1, (2008, "MS"): 1, (2008, "WY"): 1,
    (2010, "DE"): 2, (2010, "IL"): 3, (2010, "NY"): 1, (2010, "WV"): 1,
    (2014, "HI"): 3, (2014, "OK"): 3, (2014, "SC"): 3,
    (2018, "MN"): 2, (2018, "MS"): 2, (2020, "AZ"): 3, (2020, "GA"): 3,
    (2021, "GA"): 3, (2022, "CA"): 3, (2022, "OK"): 2,
    (2024, "CA"): 1, (2024, "NE"): 2,
}
CLERK = "https://history.house.gov/Institution/Election-Statistics/"
# Source sums combine rounds, even when their candidate labels differ. Do not
# assign those counts to a single election date or infer fusion from them.
MIXED_ROUNDS = {(2002, "LA"), (2014, "LA"), (2016, "LA")}


def regular_class(year: int) -> int:
    return {0: 3, 2: 1, 4: 2}[year % 6]


def candidate_kind(label: str, writein: bool) -> str:
    """Canonical categories are rules, not person identities or source hints."""
    if label in NON_VOTES | AGGREGATES:
        return "aggregate"
    if label in WRITE_INS or (not label and writein):
        return "write_in"
    if label in {"", "NA", "N/A", "NULL"}:
        return "unresolved"
    return "candidate"


def scope_rule(year: int, state: str, stage: str, special: bool) -> dict:
    """Return source-to-canonical scope; unknown conventions fail closed."""
    cycle = 2020 if year == 2021 else year
    seat_class = SPECIAL_CLASSES.get((year, state)) if special else regular_class(cycle)
    evidence = [CLASS_URLS[seat_class]] if seat_class else []
    if special:
        evidence.append(f"https://www.senate.gov/states/{state}/senators.htm")
    if seat_class is None or state not in CLASS_STATES.get(seat_class, ()):
        return dict(seat_class=None, election_date=None, stage=None, cycle=cycle,
                    issue="UNKNOWN_SEAT_CLASS", evidence=evidence)
    first = date(year, 11, 1)
    election_date = first + timedelta(days=(0-first.weekday()) % 7 + 1)
    canonical_stage = "special" if special else "general"
    issue = None
    if (year, state) in MIXED_ROUNDS:
        issue = "MIXED_ELECTION_ROUNDS"
    elif year == 2010 and state == "IL" and special:
        # MEDSL marks these full-term vote counts as a special election. The
        # official FEC report distinguishes the full and unexpired term ballots.
        # Retain the source flag, but do not publish it as the wrong contest.
        issue = "CONFLICTING_ELECTION_TYPE"
        evidence.append("https://www.fec.gov/resources/cms-content/documents/2010senate.pdf")
    elif year == 2008 and state == "GA" and not special and stage in {"PRE", "GEN"}:
        if stage == "GEN":
            election_date, canonical_stage = date(2008, 12, 2), "runoff"
        evidence.append("https://clerk.house.gov/member_info/electionInfo/2008/2008Stat.htm")
    elif year == 2018 and state == "MS" and special and stage == "GEN":
        election_date, canonical_stage = date(2018, 11, 27), "special_runoff"
        evidence.append("https://www.fec.gov/updates/mississippi-special-election-reporting-senate-2018/")
    elif year == 2021 and state == "GA" and stage == "RUNOFF":
        election_date = date(2021, 1, 5)
        canonical_stage = "special_runoff" if special else "runoff"
        evidence.append("https://www.fec.gov/help-candidates-and-committees/dates-and-deadlines/2020-reporting-dates/congressional-pre-election-reporting-dates-2020/")
    elif year == 2022 and state == "GA" and stage == "GEN RUNOFF" and not special:
        election_date, canonical_stage = date(2022, 12, 6), "runoff"
        evidence.append("https://www.fec.gov/help-candidates-and-committees/dates-and-deadlines/2022-reporting-dates/congressional-pre-election-reporting-dates-2022/")
    elif stage != "GEN" or year % 2:
        issue = "UNSUPPORTED_ELECTION_SCOPE"
    evidence.append(CLERK)
    return dict(seat_class=seat_class, election_date=None if issue else election_date.isoformat(),
                stage=None if issue else canonical_stage, cycle=cycle, issue=issue, evidence=evidence)


def parse(path: Path) -> pl.DataFrame:
    with path.open(encoding="utf-8-sig") as stream:
        header = stream.readline()
    frame = pl.read_csv(path, separator="\t" if "\t" in header else ",", infer_schema_length=0)
    if missing := REQUIRED - set(frame.columns):
        raise ValueError(f"MEDSL Senate missing required columns: {sorted(missing)}")
    if not frame.height:
        raise ValueError("MEDSL Senate file is empty")
    return frame.with_row_index("source_row_number", offset=2)


def normalize(frame: pl.DataFrame) -> pl.DataFrame:
    frame = frame.with_columns(pl.struct(pl.exclude("source_row_number")).alias("raw_json"))
    frame = frame.with_columns(
        upper("year").cast(pl.Int32, strict=False).alias("year_int"),
        upper("state_po").alias("state_code"),
        upper("candidate").alias("candidate_normalized"),
        upper("party_detailed").replace(PARTY_MAP).alias("party_normalized"),
        upper("mode").alias("mode_normalized"), upper("stage").alias("stage_normalized"),
        upper("candidatevotes").alias("votes_text"), upper("totalvotes").alias("total_text"),
        *(upper(f).alias(f + "_normalized") for f in BOOLEAN_FIELDS),
    ).with_columns(
        pl.col("state_code").replace_strict(STATE_FIPS, default=None).alias("state_fips_normalized"),
        # The official original uses integral decimal strings (e.g. 123.0).
        # Strip only an all-zero fractional suffix; never truncate 123.5.
        *(pl.col(f + "_text").str.replace(r"\.0+$", "").cast(pl.Int64, strict=False)
          .alias(f + "_int") for f in ("votes", "total")),
    ).with_columns(
        pl.struct("candidate_normalized", "writein_normalized").map_elements(
            lambda r: candidate_kind(r["candidate_normalized"], r["writein_normalized"] == "TRUE"),
            return_dtype=pl.String).alias("candidate_kind"),
    )
    return frame


def select_years(frame: pl.DataFrame, years: set[int]) -> pl.DataFrame:
    # Invalid source years stay visible as validation errors.
    return frame.filter(pl.col("year_int").is_null() | ~pl.col("year_int").is_between(1976, 2024) |
                        pl.col("year_int").is_in(sorted(years)))


def validate(frame: pl.DataFrame, years: set[int]) -> ValidationOutcome:
    result = ValidationOutcome()
    checks = {
        "INVALID_YEAR": ~pl.col("year_int").is_in(sorted(years)),
        "INVALID_STATE": pl.col("state_fips_normalized").is_null() | (pl.col("state_code") == "DC") |
            (upper("state") != pl.col("state_code").replace_strict(STATE_NAMES, default="")) |
            (upper("state_fips").str.pad_start(2, "0") != pl.col("state_fips_normalized")),
        "INVALID_OFFICE": upper("office") != "US SENATE",
        "INVALID_DISTRICT": upper("district") != "STATEWIDE",
    }
    for f in BOOLEAN_FIELDS:
        checks["INVALID_" + f.upper()] = ~pl.col(f + "_normalized").is_in(["TRUE", "FALSE"])
    for f in ("votes", "total"):
        checks["INVALID_" + f.upper()] = ((pl.col(f + "_int").is_null() &
            ~pl.col(f + "_text").is_in(list(MISSING_NUMERIC_MARKERS))) | (pl.col(f + "_int") < 0)).fill_null(False)
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
               "Missing votes are retained as NULL")
    result.add("UNOFFICIAL_RESULT", "WARNING", frame.filter(pl.col("unofficial_normalized") == "TRUE"),
               "Unofficial contests are withheld from canonical vote publication")
    return result


def records(frame: pl.DataFrame, release_id: UUID, party_ids: dict[str, UUID]) -> list[dict]:
    rows = []
    for r in frame.to_dicts():
        key = [r[k] for k in ("year_int", "state_code", "stage_normalized", "special_normalized",
                             "candidate_normalized", "party_normalized", "mode_normalized", "writein_normalized")]
        if r["candidate_kind"] != "candidate":
            key.append(_hash(r["raw_json"]))
        rows.append(dict(id=uuid4(), release_id=release_id, source_row_number=r["source_row_number"],
            row_sha256=_hash(r["raw_json"]), logical_key=_hash(key), year=r["year_int"],
            state_raw=r["state"], state_code_raw=r["state_po"], state_code=r["state_code"],
            state_fips=r["state_fips_normalized"], office_raw=r["office"], candidate_raw=r["candidate"],
            candidate_normalized=r["candidate_normalized"], candidate_kind=r["candidate_kind"],
            party_raw=r["party_detailed"], party_normalized=r["party_normalized"],
            mode_raw=r["mode"], mode_normalized=r["mode_normalized"], version_raw=r["version"],
            candidate_votes=r["votes_int"], total_votes=r["total_int"], party_id=party_ids.get(r["party_normalized"]),
            raw_json=r["raw_json"], warnings_json=[]))
    return rows


def load_details(conn: Connection, release_id: UUID, frame: pl.DataFrame) -> None:
    from app.models.ingestion import ElectionResultObservation as O
    from app.models.senate_returns import SenateReturnDetail
    ids = dict(conn.execute(select(O.source_row_number, O.id).where(O.release_id == release_id)).all())
    rows = [dict(observation_id=ids[r["source_row_number"]], stage=r["stage_normalized"],
                 **{f: r[f + "_normalized"] == "TRUE" for f in BOOLEAN_FIELDS}) for r in frame.to_dicts()]
    for chunk in _chunks(rows):
        conn.execute(pg_insert(SenateReturnDetail).values(chunk).on_conflict_do_nothing(index_elements=["observation_id"]))
