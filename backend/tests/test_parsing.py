from pathlib import Path
import polars as pl
import pytest

from ingestion.medsl import normalize, parse_csv, SchemaError
from ingestion.validation import validate

FIXTURE = Path(__file__).parent / "fixtures" / "medsl_small.csv"


def test_parse_and_normalize():
    raw = parse_csv(str(FIXTURE))
    frame = normalize(raw)
    assert raw.height == 8
    assert frame.get_column("county_fips_normalized")[0] == "01001"
    assert frame.get_column("state_fips")[0] == "01"
    assert frame.get_column("party_normalized")[0] == "DEMOCRATIC"
    assert frame.get_column("candidate_kind")[2] == "aggregate"
    assert frame.get_column("candidate_kind")[3] == "write_in"
    assert frame.get_column("raw_json")[0]["candidate"] == "AL GORE"
    assert validate(frame, {2000, 2004}).ok


def test_missing_required_column(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("year,state\n2000,ALABAMA\n")
    with pytest.raises(SchemaError, match="missing required columns"):
        parse_csv(str(path))


def test_invalid_vote_no_silent_drop(tmp_path):
    text = FIXTURE.read_text().replace(",40,100,", ",-5,100,", 1)
    path = tmp_path / "invalid.csv"
    path.write_text(text)
    result = validate(normalize(parse_csv(str(path))), {2000, 2004})
    assert not result.ok
    assert len(result.rejections) == 1
    assert "INVALID_CANDIDATE_VOTES" in result.rejections[0]["reasons_json"]


def test_special_or_missing_fips_preserved(tmp_path):
    text = FIXTURE.read_text().replace("BALDWIN,01003", "BALDWIN,", 1)
    path = tmp_path / "missing.csv"
    path.write_text(text)
    df = normalize(parse_csv(str(path)))
    result = validate(df, {2000, 2004})
    assert result.ok
    assert any(i["code"] == "FIPS_UNRESOLVED" for i in result.issues)
    assert df.get_column("county_fips_normalized")[3] is None


def test_duplicates_reported_not_dropped(tmp_path):
    rows = FIXTURE.read_text().splitlines()
    path = tmp_path / "duplicates.csv"
    path.write_text("\n".join(rows + [rows[1]]) + "\n")
    df = normalize(parse_csv(str(path)))
    check = validate(df, {2000, 2004})
    assert df.height == 9
    assert any(i["code"] == "DUPLICATE_LOGICAL_KEY" for i in check.issues)


def test_truncated_or_bad_year(tmp_path):
    text = FIXTURE.read_text().replace("2000,ALABAMA", "bad,ALABAMA", 1)
    path = tmp_path / "year.csv"
    path.write_text(text)
    result = validate(normalize(parse_csv(str(path))), {2000, 2004})
    assert "INVALID_YEAR" in result.rejections[0]["reasons_json"]


def test_party_fusion_and_total_consistency_warn(tmp_path):
    text = FIXTURE.read_text()
    # Same candidate as DEMOCRAT and GREEN: legal in some fusion states, so warning not error.
    addition = "2000,ALABAMA,AL,AUTAUGA,01001,US PRESIDENT,AL GORE,GREEN,1,100,20260225,TOTAL\n"
    path = tmp_path / "fusion.csv"
    path.write_text(text + addition)
    checked = validate(normalize(parse_csv(str(path))), {2000, 2004})
    assert checked.ok
    labels = {i["code"] for i in checked.issues}
    assert "CANDIDATE_MULTIPLE_PARTIES" in labels
    assert "CANDIDATE_SUM_EXCEEDS_TOTAL" in labels


def test_boundary_code_shift_is_warning(tmp_path):
    text = FIXTURE.read_text().replace("2004,ALABAMA,AL,AUTAUGA,01001", "2004,ALABAMA,AL,AUTAUGA,01005")
    path = tmp_path / "shift.csv"
    path.write_text(text)
    checked = validate(normalize(parse_csv(str(path))), {2000, 2004})
    assert checked.ok
    assert "COUNTY_CODE_CHANGED" in {i["code"] for i in checked.issues}


def test_state_label_inconsistency_flagged(tmp_path):
    text = FIXTURE.read_text().replace("2000,ALABAMA,AL", "2000,ARIZONA,AL", 1)
    path = tmp_path / "state.csv"
    path.write_text(text)
    checked = validate(normalize(parse_csv(str(path))), {2000, 2004})
    assert checked.ok
    assert "STATE_NAME_CODE_MISMATCH" in {i["code"] for i in checked.issues}
