from pathlib import Path

import polars as pl
import pytest

from ingestion.adapters.medsl_house import Job
from ingestion import house_returns as house
from ingestion.source import AcquisitionError

FIXTURE = Path(__file__).parent / "fixtures/house_small.csv"


def selected():
    job = Job()
    return job.select(job.normalize(job.parse(FIXTURE)), {2024})


def test_source_selection_retention_and_missing_sentinel():
    frame = selected()
    assert frame.height == 13
    assert house.validate(frame, {2024}).ok
    placeholder = frame.filter(pl.col("state_code") == "FL").to_dicts()[0]
    assert placeholder["votes_int"] is None and placeholder["total_int"] is None
    assert placeholder["raw_json"]["candidatevotes"] == "1"
    assert placeholder["raw_json"]["totalvotes"] == "-1"
    assert house.flags(placeholder) == ["UNOPPOSED_VOTE_PLACEHOLDER", "MISSING_VOTES"]
    scatter = frame.filter(pl.col("candidate") == "SCATTERING").to_dicts()[0]
    named = frame.filter(pl.col("candidate") == "NAMED WRITEIN").to_dicts()[0]
    assert scatter["candidate_kind"] == "write_in"
    assert named["candidate_kind"] == "candidate" and named["writein_normalized"] == "TRUE"
    assert named["raw_json"]["party"] == "NA"
    assert house.records(frame.head(1), __import__('uuid').uuid4(), {})[0].get("county_fips") is None


@pytest.mark.parametrize("field,value", [
    ("candidatevotes", "-1"), ("candidatevotes", "broken"), ("candidatevotes", "9223372036854775808"),
    ("totalvotes", "-1"), ("state_fips", "12"), ("state", "WRONG"), ("district", "1.0"),
    ("office", "US SENATE"), ("writein", "maybe"), ("stage", "UNKNOWN"), ("special", "unknown"),
    ("runoff", "unknown"), ("year", "2025"), ("year", "unknown"),
])
def test_malformed_source_rows_cannot_disappear_from_selection(field, value):
    raw = Job().parse(FIXTURE).head(1).with_columns(pl.lit(value).alias(field))
    frame = house.select_regular(house.normalize(raw), {2024})
    assert frame.height == 1
    outcome = house.validate(frame, {2024})
    assert not outcome.ok and len(outcome.rejections) == 1


@pytest.mark.parametrize("marker", [None, "NA", "N/A", "NULL", ""])
def test_missing_numeric_values_remain_missing(marker):
    raw = Job().parse(FIXTURE).head(1).with_columns(pl.lit(marker, dtype=pl.String).alias("candidatevotes"))
    frame = house.normalize(raw)
    assert frame["votes_int"][0] is None
    assert house.validate(frame, {2024}).ok


def test_tsv_original_and_missing_schema(tmp_path):
    raw = Job().parse(FIXTURE).drop("source_row_number")
    path = tmp_path / "original.tsv"
    raw.write_csv(path, separator="\t")
    assert Job().parse(path).height == raw.height
    raw.drop("district").write_csv(path)
    with pytest.raises(ValueError, match="missing required"):
        Job().parse(path)


def test_official_house_release_discovery(monkeypatch):
    import json
    from ingestion import source
    payload = dict(status="OK", data=dict(id=1, guestbookId=458, latestVersion=dict(
        versionState="RELEASED", versionNumber=15, versionMinorNumber=0, releaseTime="2026-03-09T17:49:25Z",
        files=[dict(dataFile=dict(id=13592823, originalFileName="1976-2024-house.tab", originalFileSize=4156562))])))
    monkeypatch.setattr(source, "_request", lambda url:json.dumps(payload).encode())
    info = Job().describe()
    assert info.version == "15.0" and info.guestbook_id == 458
    assert info.download_url.endswith("13592823?format=original")
    assert info.doi == "doi:10.7910/DVN/IG0UN2"
    payload["data"]["latestVersion"]["versionState"] = "DRAFT"
    with pytest.raises(AcquisitionError, match="not released"):
        Job().describe()


@pytest.mark.parametrize("correct_hash", [True, False])
def test_pinned_offline_cli_and_checksum_gate(tmp_path, monkeypatch, correct_hash):
    import json
    from datetime import datetime, timezone
    from ingestion.__main__ import main
    from ingestion.source import sha256_file
    from ingestion import source
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(source, "_request", lambda *a, **kw:pytest.fail("Pinned replay must not access the network"))
    folder = tmp_path / "raw/medsl_house/15.0"
    folder.mkdir(parents=True)
    path = folder / "fixture.tab"
    path.write_bytes(FIXTURE.read_bytes())
    sha = sha256_file(path)
    (folder / "file_1.json").write_text(json.dumps(dict(local_filename=path.name,
        sha256=sha, retrieved_at=datetime.now(timezone.utc).isoformat())))
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(dict(status="OK", data=dict(id=1, latestVersion=dict(
        versionState="RELEASED", versionNumber=15, versionMinorNumber=0,
        files=[dict(dataFile=dict(id=1, originalFileName="1976-2024-house.tab", originalFileSize=path.stat().st_size))])))))
    code = main(["run", "medsl_house", "--validate-only", "--source-metadata-file", str(metadata),
                 "--expected-sha256", sha if correct_hash else "0"*64])
    assert code == (0 if correct_hash else 1)
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    if correct_hash:
        assert report["records_selected"] == 13 and report["records_excluded"] == 2
        assert report["status"] == "VALIDATED"
    else:
        assert "SHA-256 differs" in report["error"]


def test_census_zip_layout_and_invalid_identifiers(tmp_path):
    from zipfile import ZipFile
    from ingestion.adapters.census_congressional_districts import Job as Census
    path = tmp_path / "districts.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("2024_Gaz_119CDs_national.txt", "USPS\tGEOID\tALAND\nNY\t3601\t1\nDC\t1198\t1\n")
    job = Census(2024)
    frame = job.parse(path)
    assert frame["geoid"].to_list() == ["3601", "1198"]
    with pytest.raises(ValueError, match="Expected 435"):
        job.validate(frame)
    with pytest.raises(ValueError, match="Malformed"):
        job.validate(frame.with_columns(pl.lit("wrong").alias("geoid")))
