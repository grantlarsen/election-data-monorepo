"""Regression tests for MEDSL V20.0 nullable/non-integer vote markers."""
from pathlib import Path

import pytest

from ingestion.medsl import normalize, parse_csv
from ingestion.validation import validate

FIXTURE = Path(__file__).parent / "fixtures" / "medsl_small.csv"


def case(tmp_path: Path, replacement: str):
    text = FIXTURE.read_text(encoding="utf-8").replace(",40,100,", replacement, 1)
    path = tmp_path / "case.csv"
    path.write_text(text, encoding="utf-8")
    frame = normalize(parse_csv(str(path)))
    return frame, validate(frame, {2000, 2004})


@pytest.mark.parametrize("marker", ["NA", "N/A", "NULL", "", " na "])
def test_missing_marker_is_warning_and_preserved(tmp_path: Path, marker: str):
    frame, checked = case(tmp_path, f",{marker},100,")
    assert checked.ok
    assert len(checked.rejections) == 0
    assert frame["votes_int"][0] is None
    assert frame["raw_json"][0]["candidatevotes"] == (marker or None)
    assert any(i["code"] == "MISSING_VOTE_COMPONENT" for i in checked.issues)


@pytest.mark.parametrize("bad", ["5O", "1,000", "?", "-5"])
def test_bad_count_still_fatal(tmp_path: Path, bad: str):
    # Commas require CSV quoting; otherwise this creates an invalid row length.
    value = f'"{bad}"' if "," in bad else bad
    frame, checked = case(tmp_path, f",{value},100,")
    assert not checked.ok
    assert len(checked.rejections) == 1
    assert checked.rejections[0]["source_row_number"] == 2
    assert "INVALID_CANDIDATE_VOTES" in checked.rejections[0]["reasons_json"]


def test_missing_total_is_warning(tmp_path: Path):
    frame, checked = case(tmp_path, ",40,NA,")
    assert checked.ok
    assert frame["total_int"][0] is None
    assert any(i["code"] == "MISSING_TOTAL" for i in checked.issues)
