"""Small geographic fixtures, plus opt-in PostgreSQL test DB integration."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
pl = pytest.importorskip("polars")
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.database import Base
import app.models
from app.models.core import Jurisdiction
from app.models.geography import GeographicReference, GeographicResolution
from app.models.ingestion import ElectionResultObservation
from ingestion.adapters.census_state_county_georef import (Job, name_key, parse_reference, validate_reference)
from ingestion.geography.load import load_reference
from ingestion.geography.resolve import assess_observation, resolve_medsl
from ingestion.loader import load, register_run
from ingestion.medsl import normalize, parse_csv
from ingestion.source import AcquiredFile, SourceInfo

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_reference():
    return parse_reference(FIXTURES / "census_georef_small.txt")


def test_parse_old_and_new_layouts_and_leading_zeroes():
    first = fixture_reference()
    second = parse_reference(FIXTURES / "census_nes_small.txt")
    assert first.get_column("geoid").to_list() == ["01001", "01003", "01999", "11001"]
    assert second.get_column("geoid").to_list() == ["01001", "01003", "11001"]
    assert validate_reference(first, require_complete=False)["county_rows"] == 3
    assert name_key("AUTAUGA") == name_key("Autauga County, AL")
    assert name_key("Miami-Dade County, FL") != name_key("Dade County, FL")


def test_duplicate_geography_hard_failure():
    f = fixture_reference()
    with pytest.raises(ValueError, match="duplicate"):
        validate_reference(pl.concat([f, f.head(1)]), require_complete=False)


def test_malformed_fips_hard_failure():
    f = fixture_reference().with_columns(pl.when(pl.col("geoid") == "01001")
                                       .then(pl.lit(None)).otherwise(pl.col("county_code"))
                                       .alias("county_code"))
    with pytest.raises(ValueError, match="malformed"):
        validate_reference(f, require_complete=False)


def sample_observation(**overrides):
    obj = {"year": 2000, "state_code": "AL", "state_fips": "01",
           "county_raw": "AUTAUGA", "county_fips_raw": "01001", "county_fips": "01001"}
    obj.update(overrides)
    return obj


def sample_refs():
    jid, rid = uuid4(), uuid4()
    ref = {"id": rid, "jurisdiction_id": jid, "geoid": "01001",
           "state_fips": "01", "name_raw": "Autauga County, AL", "name_key": "AUTAUGA"}
    return {"01001": ref}, {("01", "AUTAUGA"): [ref]}


def test_exact_fips_and_name_only():
    by_code, by_name = sample_refs()
    rid = uuid4()
    resolved = assess_observation(sample_observation(), by_code, by_name, {}, rid, 1996, 2001)
    assert resolved["status"] == "RESOLVED"
    assert resolved["jurisdiction_id"] == by_code["01001"]["jurisdiction_id"]
    ambiguous = assess_observation(sample_observation(county_raw="OTHER"), by_code, by_name, {}, rid, 1996, 2001)
    assert ambiguous["status"] == "AMBIGUOUS" and ambiguous["jurisdiction_id"] is None
    no_fips = assess_observation(sample_observation(county_fips_raw=None, county_fips=None),
                                 by_code, by_name, {}, rid, 1996, 2001)
    assert no_fips["status"] == "UNRESOLVED" and no_fips["method"] == "NAME_CANDIDATE_REVIEW"


def test_historical_boundary_and_code_safety():
    by_code, by_name = sample_refs()
    rid = uuid4()
    latest = {"01003": (2024, "BALDWIN")}
    old_code = assess_observation(sample_observation(), by_code, by_name, latest, rid, 1996, 2001)
    assert old_code["status"] == "RESOLVED_HISTORICAL"
    outside = assess_observation(sample_observation(year=2024), by_code, by_name, {}, rid, 1996, 2001)
    assert outside["status"] == "OUT_OF_VINTAGE"
    conflict = assess_observation(sample_observation(county_fips=None, county_fips_raw="02001"),
                                  by_code, by_name, {}, rid, 1996, 2001)
    assert conflict["status"] == "INVALID"
    special = assess_observation(sample_observation(county_fips="01999", county_fips_raw="01999"),
                                 by_code, by_name, {}, rid, 1996, 2001)
    assert special["status"] == "UNRESOLVED"


@pytest.fixture
def geo_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not configured")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must point to a disposable *_test database")
    schema = "geo_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def ref_asset() -> AcquiredFile:
    info = SourceInfo("census_state_county_georef", "Census CBP geography", "cbp-1996-2001", 1996,
                      "georef96_01.txt", "https://example.invalid/georef96_01.txt", None,
                      None, {"vintage_start": 1996, "vintage_end": 2001})
    return AcquiredFile(info, FIXTURES / "census_georef_small.txt", "b" * 64, datetime.now(timezone.utc))


def medsl_asset() -> AcquiredFile:
    info = SourceInfo("medsl_presidential_county", "test", "20.0", 13573089,
                      "medsl_small.csv", "https://example.invalid/test.csv", None, None, {})
    return AcquiredFile(info, FIXTURES / "medsl_small.csv", "a" * 64, datetime.now(timezone.utc))


@pytest.mark.integration
def test_geography_idempotence_and_medsl_resolution(geo_db):
    f = fixture_reference()
    first_run = uuid4()
    first_id = register_run(geo_db, first_run, "census_state_county_georef", Job.source_url,
                            datetime.now(timezone.utc), {})
    inserted = load_reference(geo_db, first_id, first_run, ref_asset(), f,
                              validate_reference(f, require_complete=False))
    assert inserted["records_inserted"] == 5  # AL and DC state + 3 county reference rows
    second_run = uuid4()
    second_id = register_run(geo_db, second_run, "census_state_county_georef", Job.source_url,
                             datetime.now(timezone.utc), {})
    reused = load_reference(geo_db, second_id, second_run, ref_asset(), f,
                            validate_reference(f, require_complete=False))
    assert reused["records_inserted"] == 0
    assert second_id == first_id
    df = normalize(parse_csv(str(FIXTURES / "medsl_small.csv"))).filter(pl.col("year_int") == 2000)
    medsl_run = uuid4()
    medsl_id = register_run(geo_db, medsl_run, "medsl_presidential_county", "test",
                             datetime.now(timezone.utc), {})
    load(geo_db, medsl_id, medsl_run, medsl_asset(), df, {2000}, [],
         datetime.now(timezone.utc), datetime.now(timezone.utc), 0)
    first, review = resolve_medsl(geo_db, vintage=2000, actor='pytest')
    assert first["status_counts"] == {"RESOLVED": 6} and not review
    assert first["records_inserted"] == 6
    again, _ = resolve_medsl(geo_db, vintage=2000, actor='pytest')
    assert again["records_inserted"] == 0
    with geo_db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(GeographicResolution)) == 6
        assert conn.scalar(select(func.count()).select_from(ElectionResultObservation)
                           .where(ElectionResultObservation.jurisdiction_id.is_not(None))) == 0


@pytest.mark.integration
def test_geography_rollback_does_not_partial_load(geo_db, monkeypatch):
    from ingestion.geography import load as geo_load
    frame = fixture_reference()
    run_id = uuid4()
    src_id = register_run(geo_db, run_id, "census_state_county_georef", Job.source_url,
                          datetime.now(timezone.utc), {})
    real_chunks = geo_load._chunks
    calls = 0

    def injected_failure(items, size=500):
        nonlocal calls
        calls += 1
        if calls == 2:  # After INSERT of states but before INSERT of counties.
            raise RuntimeError("injected transactional failure")
        yield from real_chunks(items, size)

    monkeypatch.setattr(geo_load, "_chunks", injected_failure)
    with pytest.raises(RuntimeError, match="injected"):
        load_reference(geo_db, src_id, run_id, ref_asset(), frame,
                       validate_reference(frame, require_complete=False))
    with geo_db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Jurisdiction)) == 0
        assert conn.scalar(select(func.count()).select_from(GeographicReference)) == 0

@pytest.mark.integration
def test_step61_supersession_is_append_only_and_requires_approval(geo_db, monkeypatch):
    """No original result changes; old decisions remain readable after publication."""
    from ingestion.geography import resolve as resolution_module
    from ingestion.geography.resolution_v2 import current_resolution_rows
    from sqlalchemy import select
    f=fixture_reference()
    run=uuid4()
    sid=register_run(geo_db,run,'census_state_county_georef',Job.source_url,datetime.now(timezone.utc),{})
    load_reference(geo_db,sid,run,ref_asset(),f,validate_reference(f,require_complete=False))
    df=normalize(parse_csv(str(FIXTURES/'medsl_small.csv'))).filter(pl.col('year_int')==2000)
    run=uuid4()
    sid=register_run(geo_db,run,'medsl_presidential_county','test',datetime.now(timezone.utc),{})
    load(geo_db,sid,run,medsl_asset(),df,{2000},[],datetime.now(timezone.utc),datetime.now(timezone.utc),0)
    first,_=resolve_medsl(geo_db,vintage=2000,actor='pytest')
    assert first['records_inserted']==6
    before=geo_db.connect()
    with before:
        votes=before.execute(select(ElectionResultObservation.id,ElectionResultObservation.candidate_votes,
                                    ElectionResultObservation.county_raw)).all()
    original=resolution_module.assess_observation
    def altered(*args,**kwargs):
        proposed=original(*args,**kwargs)
        proposed['status']='AMBIGUOUS'
        proposed['method']='SIMULATED_REVIEW'
        proposed['jurisdiction_id']=None
        proposed['reason']='Simulated for rollback/supersession test'
        return proposed
    monkeypatch.setattr(resolution_module,'assess_observation',altered)
    with pytest.raises(ValueError,match='--approve-changes'):
        resolve_medsl(geo_db,vintage=2000,actor='pytest')
    with geo_db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(GeographicResolution))==6
    preview,_=resolve_medsl(geo_db,vintage=2000,dry_run=True,publish=False)
    with pytest.raises(ValueError,match='expected-proposal-sha256'):
        resolve_medsl(geo_db,vintage=2000,approve_changes=True,actor='pytest')
    with pytest.raises(ValueError,match='allow-downgrades'):
        resolve_medsl(geo_db,vintage=2000,approve_changes=True,actor='pytest',
            expected_proposal_sha256=preview['proposal_sha256'])
    second,_=resolve_medsl(geo_db,vintage=2000,approve_changes=True,actor='pytest',
        expected_proposal_sha256=preview['proposal_sha256'],allow_downgrades=True)
    assert second['records_inserted']==6
    assert second['changed_decisions']==6
    again,_=resolve_medsl(geo_db,vintage=2000,approve_changes=True,actor='pytest')
    assert again['records_inserted']==0
    with geo_db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(GeographicResolution))==12
        leaves=current_resolution_rows(conn,UUID(first['reference_release_id']))
        assert len(leaves)==6
        assert all(row['status']=='AMBIGUOUS' and row['supersedes_id'] is not None
                   for row in leaves.values())
        saved=conn.execute(select(ElectionResultObservation.id,ElectionResultObservation.candidate_votes,
                                  ElectionResultObservation.county_raw)).all()
        assert sorted(votes,key=lambda r:str(r[0]))==sorted(saved,key=lambda r:str(r[0]))
