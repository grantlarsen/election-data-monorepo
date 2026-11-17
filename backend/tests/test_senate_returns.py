"""Source fidelity, exact counts and evidence-backed Senate race scope."""
from pathlib import Path
from uuid import uuid4

import polars as pl
import pytest

from ingestion.adapters.medsl_senate import Job
from ingestion import senate_returns as senate
from ingestion.medsl import STATE_FIPS

FIXTURE = Path(__file__).parent / "fixtures/senate_small.csv"


def selected(years=None):
    job = Job()
    return job.select(job.normalize(job.parse(FIXTURE)), years or {2008, 2021})


def test_source_retention_decimal_votes_and_selection():
    frame = selected()
    assert frame.height == 13
    assert senate.validate(frame, {2008, 2021}).ok
    first = frame.row(0, named=True)
    assert first["raw_json"]["candidatevotes"] == "80.0" and first["votes_int"] == 80
    unnamed = frame.filter(pl.col("candidate").is_null()).row(0, named=True)
    assert unnamed["candidate_kind"] == "write_in"
    assert senate.records(frame.head(1), uuid4(), {})[0].get("county_fips") is None


@pytest.mark.parametrize("field,value", [
    ("candidatevotes", "-1.0"), ("candidatevotes", "2.5"), ("candidatevotes", "NaN"),
    ("candidatevotes", "9223372036854775808.0"), ("candidatevotes", "garbled"),
    ("totalvotes", "-1"), ("year", "2025"), ("year", "unknown"), ("state", "WRONG"),
    ("state_fips", "13"), ("office", "US HOUSE"), ("district", "01"), ("special", "maybe"),
    ("writein", "maybe"), ("unofficial", "maybe"),
])
def test_malformed_counts_and_scope_fail_before_load(field, value):
    raw = Job().parse(FIXTURE).head(1).with_columns(pl.lit(value).alias(field))
    frame = senate.select_years(senate.normalize(raw), {2008})
    outcome = senate.validate(frame, {2008})
    assert frame.height == 1 and not outcome.ok and len(outcome.rejections) == 1


@pytest.mark.parametrize("marker", [None, "", "NA", "NULL", "N/A"])
def test_missing_votes_preserved(marker):
    raw = Job().parse(FIXTURE).head(1).with_columns(pl.lit(marker, dtype=pl.String).alias("candidatevotes"))
    frame = senate.normalize(raw)
    assert frame["votes_int"][0] is None and senate.validate(frame, {2008}).ok


def test_official_class_structure_and_special_classes():
    assert [len(senate.CLASS_STATES[n]) for n in (1,2,3)] == [33,33,34]
    assert set.union(*(set(s) for s in senate.CLASS_STATES.values())) == set(STATE_FIPS) - {"DC"}
    assert all(sum(st in states for states in senate.CLASS_STATES.values()) == 2 for st in STATE_FIPS if st != "DC")
    for (year, st), seat_class in senate.SPECIAL_CLASSES.items():
        assert senate.scope_rule(year, st, "RUNOFF" if year == 2021 else "GEN", True)["seat_class"] == seat_class
    assert senate.scope_rule(2024, "TX", "GEN", True)["issue"] == "UNKNOWN_SEAT_CLASS"


@pytest.mark.parametrize("year,state,stage,special,expected_date,expected_stage,seat_class,cycle", [
    (2008,"GA","PRE",False,"2008-11-04","general",2,2008),
    (2008,"GA","GEN",False,"2008-12-02","runoff",2,2008),
    (2018,"MS","GEN",True,"2018-11-27","special_runoff",2,2018),
    (2021,"GA","RUNOFF",False,"2021-01-05","runoff",2,2020),
    (2021,"GA","RUNOFF",True,"2021-01-05","special_runoff",3,2020),
    (2022,"GA","GEN RUNOFF",False,"2022-12-06","runoff",3,2022),
    (2024,"CA","GEN",False,"2024-11-05","general",1,2024),
    (2024,"CA","GEN",True,"2024-11-05","special",1,2024),
])
def test_dates_stages_cycles_and_same_seat_different_terms(year,state,stage,special,expected_date,expected_stage,seat_class,cycle):
    rule = senate.scope_rule(year,state,stage,special)
    assert (rule["election_date"],rule["stage"],rule["seat_class"],rule["cycle"]) == (expected_date,expected_stage,seat_class,cycle)
    assert rule["evidence"] and rule["issue"] is None


@pytest.mark.parametrize("year", [2002,2014,2016])
def test_mixed_rounds_have_no_invented_date(year):
    rule = senate.scope_rule(year,"LA","GEN",False)
    assert rule["issue"] == "MIXED_ELECTION_ROUNDS" and rule["election_date"] is None


def test_schema_tsv_and_unsupported_stage(tmp_path):
    raw = Job().parse(FIXTURE).drop("source_row_number")
    path = tmp_path / "source.tab"
    raw.write_csv(path, separator="\t")
    assert Job().parse(path).height == raw.height
    raw.drop("special").write_csv(path)
    with pytest.raises(ValueError, match="missing required"):
        Job().parse(path)
    assert senate.scope_rule(2024,"NY","UNKNOWN",False)["issue"] == "UNSUPPORTED_ELECTION_SCOPE"


def test_mislabeled_illinois_full_term_counts_cannot_become_special_votes():
    rule = senate.scope_rule(2010, "IL", "GEN", True)
    assert rule["issue"] == "CONFLICTING_ELECTION_TYPE"
    assert rule["election_date"] is None and rule["seat_class"] == 3
    assert any("2010senate.pdf" in url for url in rule["evidence"])


@pytest.mark.parametrize("label,kind", [
    ("BLANK VOTE", "aggregate"), ("OVER VOTE", "aggregate"), ("VOID VOTE", "aggregate"),
    ("BLANK VOTE/SCATTERING", "aggregate"), ("BLANK VOTE/VOID VOTE/SCATTERING", "aggregate"),
    ("NONE OF THESE CANDIDATES", "aggregate"), ("NONE OF THESE, CANDIDATES", "aggregate"),
    ("NONE OF THE ABOVE", "aggregate"), ("OTHER CANDIDATES", "aggregate"), ("SCATTER", "write_in"),
])
def test_administrative_and_unnamed_labels_never_create_named_candidates(label, kind):
    assert senate.candidate_kind(label, False) == kind
