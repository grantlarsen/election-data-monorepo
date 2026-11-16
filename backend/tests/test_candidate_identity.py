"""Offline contracts and disposable PostgreSQL identity/profile regression coverage."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import candidates, elections
from app.main import app
from app.models.candidate_identity import CandidateFinanceSummary, CandidateIdentityReview, FecCandidateRecord
from app.models.core import Candidacy, Contest, DataSource, Election, Jurisdiction, Person
from app.models.identity import CommitteeRelationship, ExternalIdentifier
from app.models.ingestion import IngestionRun, SourceRelease
from app.services.candidate_matching import comparable_name, decide_match, match_candidate, propose_match, same_scope
from app.services.candidate_profiles import candidate_profile, finance_values
from app.services.identity import IdentityConflictError, attach_external_identifier, create_person
from ingestion.fec_candidates import MASTER, SUMMARY, load, money, parse
from ingestion.source import sha256_file
from test_identity import identity_engine  # Shared isolated-schema fixture, guarded _test database.


def archive(tmp_path, *, kind="master", records=None):
    fields = MASTER if kind == "master" else SUMMARY
    if records is None:
        records = [dict(CAND_ID="P00000001", CAND_NAME="SMITH, ALEX", CAND_ELECTION_YR="2024",
            CAND_OFFICE="P", CAND_OFFICE_ST="US", CAND_OFFICE_DISTRICT="00", CAND_PCC="C00000001")]
    path = tmp_path / f"{kind}.zip"
    with ZipFile(path, "w") as output:
        output.writestr("cn.txt" if kind == "master" else "weball.txt",
            "\n".join("|".join(record.get(field, "") for field in fields) for record in records) + "\n")
    return path


@pytest.mark.parametrize("a,b", [("SMITH, ALEX", "Alex Smith"), ("José O'Neil", "JOSE O NEIL")])
def test_name_comparison(a, b):
    assert comparable_name(a) == comparable_name(b)
    assert comparable_name("A Smith") != comparable_name("Alex Smith")
    assert comparable_name("Alex Smith Jr") != comparable_name("Alex Smith")


def test_pinned_parser_rejects_duplicate_ids_and_bad_scope(tmp_path):
    row = dict(CAND_ID="H00000001", CAND_NAME="SMITH, ALEX", CAND_ELECTION_YR="2024",
               CAND_OFFICE="H", CAND_OFFICE_ST="NY", CAND_OFFICE_DISTRICT="01")
    assert parse(archive(tmp_path, records=[row]), "master")[0]["CAND_NAME"] == "SMITH, ALEX"
    with pytest.raises(ValueError, match="Duplicate"):
        parse(archive(tmp_path, records=[row, row]), "master")
    with pytest.raises(ValueError, match="scope"):
        parse(archive(tmp_path, records=[{**row, "CAND_OFFICE": "X"}]), "master")
    # Source contradictions are retained, not repaired by guessing an office.
    assert parse(archive(tmp_path, records=[{**row, "CAND_OFFICE": "S"}]), "master")[0]["CAND_OFFICE"] == "S"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1.005", "garbage", "10000000000000000"])
def test_money_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        money(value)


def test_money_preserves_zero_missing_and_negative_adjustments():
    assert money("") is None
    assert money("0.00") == Decimal("0.00")
    assert money("-1.25") == Decimal("-1.25")


def test_missing_or_contradictory_scope_cannot_match():
    context = dict(year=2024, office="H", state_code="NY", district=None)
    record = FecCandidateRecord(cycle=2024, election_year=2024, office="H", state_code="NY", district=None, raw_json={})
    assert not same_scope(record, context)
    record.district, context["district"] = "01", "01"
    assert same_scope(record, context)
    record.raw_json = {"CAND_ID": "S00000001"}
    assert not same_scope(record, context)


def test_summary_cycle_member_must_agree(tmp_path):
    path = tmp_path / "wrong-cycle.zip"
    with ZipFile(path, "w") as output:
        output.writestr("weball26.txt", "unused")
    with pytest.raises(ValueError, match="cycle"):
        parse(path, "summary", cycle=2024)


def test_finance_transfer_definition_and_missing_values():
    row = CandidateFinanceSummary(receipts=Decimal("100.00"), disbursements=Decimal("80.00"),
        transfers_from_authorized=Decimal("10.00"), transfers_to_authorized=Decimal("10.00"))
    result = finance_values(row)
    assert result["total_raised"] == Decimal("90.00")
    assert result["total_spent"] == Decimal("70.00")
    assert result["reported_receipts"] == Decimal("100.00")
    assert result["definition"] == "reported_totals_less_authorized_transfers"
    row.transfers_to_authorized = None
    assert finance_values(row)["status"] == "partial"
    assert finance_values(row)["total_raised"] is None
    row.transfers_to_authorized = Decimal("0")
    assert finance_values(row)["total_raised"] == Decimal("100.00")


def seed(session, *, names=("SMITH, ALEX",)):
    source = DataSource(name="fec_candidate_master", url="https://www.fec.gov")
    geography = Jurisdiction(name="United States", level="country")
    session.add_all([source, geography])
    session.flush()
    release = SourceRelease(source_id=source.id, version="2024", sha256="a" * 64,
        filename="cn24.zip", file_id=0, download_url="https://www.fec.gov/files/bulk-downloads/2024/cn24.zip",
        raw_path="fixture", retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), metadata_json={})
    election = Election(election_date=date(2024, 11, 5), election_type="general", election_cycle=2024,
        jurisdiction_id=geography.id)
    session.add_all([release, election])
    session.flush()
    contest = Contest(office_name="U.S. President", election_id=election.id, jurisdiction_id=geography.id)
    session.add(contest)
    session.flush()
    candidate = Candidacy(contest_id=contest.id, source_label="Alex Smith", candidate_kind="candidate")
    session.add(candidate)
    records = []
    for index, name in enumerate(names):
        identifier = attach_external_identifier(session, namespace="fec", identifier_type="candidate",
            value=f"P0000000{index + 1}", source_id=source.id, release_id=release.id)
        record = FecCandidateRecord(release_id=release.id, identifier_id=identifier.id, cycle=2024,
            election_year=2024, name=name, office="P", state_code="US", district="00",
            principal_committee="C00000001", raw_json={})
        session.add(record)
        records.append(record)
    session.flush()
    return candidate, release, records


@pytest.mark.integration
def test_ambiguous_names_never_merge_and_rejection_survives_release(identity_engine):
    with Session(identity_engine) as session, session.begin():
        candidate, release, records = seed(session, names=("SMITH, ALEX", "SMITH, ALEX"))
        assert match_candidate(session, candidacy_id=candidate.id, release_id=release.id) == {"pending": 2}
        assert candidate.person_id is None
        assert session.scalar(select(func.count()).select_from(Person)) == 0
        reviews = session.scalars(select(CandidateIdentityReview).order_by(CandidateIdentityReview.record_id)).all()
        decide_match(session, review_id=reviews[0].id, accept=False, actor="researcher", evidence="Distinct individual; official ballot citation")
        assert match_candidate(session, candidacy_id=candidate.id, release_id=release.id) == {"unchanged": 2}
        newer = SourceRelease(source_id=release.source_id, version="2024", sha256="b" * 64,
            filename="cn24.zip", file_id=0, download_url=release.download_url, raw_path="fixture",
            retrieved_at=datetime(2026, 2, 1, tzinfo=timezone.utc), metadata_json={})
        session.add(newer)
        session.flush()
        for record in records:
            session.add(FecCandidateRecord(release_id=newer.id, identifier_id=record.identifier_id, cycle=2024,
                election_year=2024, name=record.name, office="P", state_code="US", district="00", raw_json={}))
        session.flush()
        assert match_candidate(session, candidacy_id=candidate.id, release_id=newer.id) == {"unchanged": 1, "pending": 1}
        decide_match(session, review_id=reviews[1].id, accept=True, actor="researcher", evidence="Official candidate registration and ballot agree")
        assert candidate.person_id is not None
        assert session.scalar(select(func.count()).select_from(Person)) == 1
        assert session.scalar(select(func.count()).select_from(CommitteeRelationship)) == 1
        newer_pending = session.scalar(select(CandidateIdentityReview).where(
            CandidateIdentityReview.release_id == newer.id, CandidateIdentityReview.status == "pending"))
        with pytest.raises(IdentityConflictError, match="accepted identifier"):
            decide_match(session, review_id=newer_pending.id, accept=False, actor="researcher", evidence="Contradictory assertion")
        assert decide_match(session, review_id=reviews[1].id, accept=True, actor="researcher", evidence="Replay").id == reviews[1].id
        with pytest.raises(IdentityConflictError):
            decide_match(session, review_id=reviews[0].id, accept=True, actor="researcher", evidence="Attempt overwrite")


@pytest.mark.integration
def test_official_id_precedence_and_conflicting_scope(identity_engine):
    with Session(identity_engine) as session, session.begin():
        candidate, release, records = seed(session, names=("UNRELATED, NAME", "SMITH, ALEX"))
        identifier = session.get(ExternalIdentifier, records[0].identifier_id)
        from app.services.identity import resolve_external_identifier
        resolve_external_identifier(session, identifier_id=identifier.id, target_type="candidacy", target_id=candidate.id,
            actor="fixture", evidence="Official ballot candidate ID")
        assert match_candidate(session, candidacy_id=candidate.id, release_id=release.id) == {"accepted": 1}
        assert candidate.person_id is not None
        assert match_candidate(session, candidacy_id=candidate.id, release_id=release.id) == {"unchanged": 1}
        profile = candidate_profile(session, candidate.id)
        assert profile["identity_status"] == "resolved"
        assert profile["identity_evidence"][0]["fec_candidate_id"] == "P00000001"
        assert profile["identity_evidence"][0]["source"]["sha256"] == release.sha256
        assert profile["committees"][0]["cycle"] == 2024
        assert profile["results"]["total"] == 0


@pytest.mark.integration
def test_latest_election_uses_verified_person_and_excludes_future_events(identity_engine):
    with Session(identity_engine) as session, session.begin():
        candidate, release, records = seed(session)
        person = create_person(session, full_name="Alex Smith", creation_key="curated:latest")
        candidate.person_id = person.id
        original = session.get(Contest, candidate.contest_id)
        latest_id = None
        for year in (2025, 2099):
            event = Election(election_date=date(year, 1, 1), election_type="special", election_cycle=year,
                jurisdiction_id=original.jurisdiction_id)
            session.add(event)
            session.flush()
            contest = Contest(office_name="U.S. Senate", election_id=event.id, jurisdiction_id=original.jurisdiction_id)
            session.add(contest)
            session.flush()
            candidacy = Candidacy(contest_id=contest.id, person_id=person.id, source_label="Alex Smith")
            session.add(candidacy)
            session.flush()
            if year == 2025:
                latest_id = candidacy.id
        profile = candidate_profile(session, candidate.id)
        assert profile["latest_election"]["candidacy_id"] == latest_id
        assert profile["latest_election"]["election_date"] == date(2025, 1, 1)
        candidate.person_id = None
        session.flush()
        assert candidate_profile(session, candidate.id)["latest_election"]["candidacy_id"] == candidate.id


@pytest.mark.integration
def test_scope_mismatch_and_person_conflict_refuse_acceptance(identity_engine):
    with Session(identity_engine) as session, session.begin():
        candidate, release, records = seed(session)
        records[0].election_year = 2022
        session.flush()
        assert match_candidate(session, candidacy_id=candidate.id, release_id=release.id) == {"unmatched": 1}
        with pytest.raises(IdentityConflictError):
            propose_match(session, candidacy_id=candidate.id, record_id=records[0].id, actor="fixture", evidence="Bad scope")
        records[0].election_year = 2024
        session.flush()
        match_candidate(session, candidacy_id=candidate.id, release_id=release.id)
        review = session.scalar(select(CandidateIdentityReview).where(CandidateIdentityReview.status == "pending"))
        first = create_person(session, full_name="First", creation_key="curated:first")
        second = create_person(session, full_name="Second", creation_key="curated:second")
        candidate.person_id = first.id
        identifier = session.get(ExternalIdentifier, records[0].identifier_id)
        from app.services.identity import resolve_external_identifier
        resolve_external_identifier(session, identifier_id=identifier.id, target_type="person", target_id=second.id,
            actor="fixture", evidence="Different person")
        with pytest.raises(IdentityConflictError, match="person assignment"):
            decide_match(session, review_id=review.id, accept=True, actor="fixture", evidence="Cannot merge")
        assert candidate.person_id == first.id


@pytest.mark.integration
def test_fec_import_replay_and_summary_provenance(identity_engine, tmp_path):
    path = archive(tmp_path)
    options = dict(engine=identity_engine, path=path, kind="master", cycle=2024,
        sha256=sha256_file(path), retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), data_dir=tmp_path / "cache")
    first = load(**options)
    second = load(**options)
    assert first["inserted"] == 1 and second["unchanged"] == 1 and second["inserted"] == 0
    assert first["release_id"] == second["release_id"]
    summary = archive(tmp_path, kind="summary", records=[dict(CAND_ID="P00000001", TTL_RECEIPTS="0.00",
        TTL_DISB="12.34", TRANS_FROM_AUTH="0", TRANS_TO_AUTH="0", CVG_END_DT="12/31/2024")])
    assert load(**{**options, "path": summary, "kind": "summary", "sha256": sha256_file(summary)})["inserted"] == 1
    with Session(identity_engine) as session:
        assert session.scalar(select(func.count()).select_from(Person)) == 0
        assert session.scalar(select(func.count()).select_from(IngestionRun)) == 3
        row = session.scalar(select(CandidateFinanceSummary))
        assert row.receipts == 0 and row.disbursements == Decimal("12.34")
        assert row.coverage_end == date(2024, 12, 31)
    with pytest.raises(ValueError, match="SHA-256"):
        load(**{**options, "sha256": "0" * 64})


@pytest.mark.integration
def test_invalid_release_has_rejections_and_no_partial_records(identity_engine, tmp_path):
    from app.models.ingestion import IngestionRejection
    row = dict(CAND_ID="P00000001", CAND_NAME="SMITH, ALEX", CAND_ELECTION_YR="2024",
        CAND_OFFICE="P", CAND_OFFICE_ST="US", CAND_OFFICE_DISTRICT="00")
    path = archive(tmp_path, records=[row, row])
    with pytest.raises(ValueError, match="Duplicate"):
        load(identity_engine, path=path, kind="master", cycle=2024, sha256=sha256_file(path),
            retrieved_at=datetime.now(timezone.utc), data_dir=tmp_path / "cache")
    with Session(identity_engine) as session:
        run = session.scalar(select(IngestionRun))
        assert run.status == "FAILED" and run.records_read == 2 and run.records_rejected == 2
        assert session.scalars(select(IngestionRejection.source_row_number).order_by(IngestionRejection.source_row_number)).all() == [1, 2]
        assert session.scalar(select(func.count()).select_from(FecCandidateRecord)) == 0
        assert session.scalar(select(func.count()).select_from(SourceRelease)) == 0


@pytest.mark.integration
def test_profile_uses_one_matched_id_cycle_and_snapshot(identity_engine):
    with Session(identity_engine) as session, session.begin():
        candidate, release, records = seed(session)
        match_candidate(session, candidacy_id=candidate.id, release_id=release.id)
        review = session.scalar(select(CandidateIdentityReview))
        decide_match(session, review_id=review.id, accept=True, actor="fixture", evidence="Official match")
        for cycle, amount in ((2022, "999"), (2024, "100")):
            session.add(CandidateFinanceSummary(release_id=release.id, identifier_id=records[0].identifier_id,
                cycle=cycle, receipts=Decimal(amount), disbursements=Decimal("0"),
                transfers_from_authorized=Decimal("0"), transfers_to_authorized=Decimal("0"), raw_json={}))
        session.flush()
        profile = candidate_profile(session, candidate.id)
        assert profile["finance"]["total_raised"] == Decimal("100")
        assert profile["finance"]["total_spent"] == 0
        assert profile["finance"]["source"]["sha256"] == release.sha256
        unrelated = attach_external_identifier(session, namespace="fec", identifier_type="candidate", value="H00000001",
            source_id=release.source_id, target_type="person", target_id=candidate.person_id, actor="fixture", evidence="Separate office")
        session.add(CandidateFinanceSummary(release_id=release.id, identifier_id=unrelated.id, cycle=2024,
            receipts=Decimal("1000000"), raw_json={}))
        session.flush()
        assert candidate_profile(session, candidate.id)["finance"]["total_raised"] == Decimal("100")
        newer = SourceRelease(source_id=release.source_id, version="2024", sha256="b" * 64,
            filename="weball24.zip", file_id=0, download_url=release.download_url, raw_path="fixture",
            retrieved_at=datetime(2026, 2, 1, tzinfo=timezone.utc), metadata_json={})
        session.add(newer)
        session.flush()
        session.add(CandidateFinanceSummary(release_id=newer.id, identifier_id=records[0].identifier_id, cycle=2024,
            receipts=Decimal("200"), disbursements=Decimal("0"), transfers_from_authorized=Decimal("0"),
            transfers_to_authorized=Decimal("0"), raw_json={}))
        session.flush()
        assert candidate_profile(session, candidate.id)["finance"]["total_raised"] == Decimal("200")
        # Simultaneous conflicting snapshots fail closed instead of choosing a UUID.
        tied = SourceRelease(source_id=release.source_id, version="2024", sha256="c" * 64,
            filename="weball24.zip", file_id=0, download_url=release.download_url, raw_path="fixture",
            retrieved_at=newer.retrieved_at, metadata_json={})
        session.add(tied)
        session.flush()
        session.add(CandidateFinanceSummary(release_id=tied.id, identifier_id=records[0].identifier_id, cycle=2024,
            receipts=Decimal("300"), raw_json={}))
        session.flush()
        assert candidate_profile(session, candidate.id)["finance"]["status"] == "ambiguous"


def test_candidate_api_validation_not_found_and_integrity(monkeypatch):
    app.dependency_overrides[elections.get_read_session] = lambda: None
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/candidates/not-uuid").status_code == 422
            url = "/api/v1/candidates/" + str(uuid4())
            assert client.get(url + "?limit=201").status_code == 422
            assert client.get(url + "?offset=-1").status_code == 422
            assert client.get(url + "?reporting_level=state").status_code == 422
            monkeypatch.setattr(candidates, "candidate_profile", lambda *a, **kw: None)
            assert client.get(url).status_code == 404
            from app.services.canonical_results import MaterializationError
            def bad(*a, **kw):
                raise MaterializationError("private integrity detail")
            monkeypatch.setattr(candidates, "candidate_profile", bad)
            response = client.get(url)
            assert response.status_code == 503
            assert "private" not in response.text
    finally:
        app.dependency_overrides.clear()
