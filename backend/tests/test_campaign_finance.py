"""Finance lineage, exact coverage, immutable replay and database invariants."""
from datetime import date, datetime, timezone
from decimal import Decimal
import io
from pathlib import Path
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models.campaign_finance import (
    CommitteeFiling, CommitteeFinanceSnapshot, FecCandidateCommitteeLink,
    FecCommitteeRecord,
)
from app.models.core import Candidacy, Contest, DataSource, Election, Jurisdiction, Person
from app.models.identity import CommitteeRelationship, ExternalIdentifier
from app.models.ingestion import SourceRelease
from app.services.campaign_finance import committee_finance, cycle_for_date, store_finance_record, validate_cycle
from app.services.identity import IdentityConflictError, attach_external_identifier, link_committee, register_organization
from test_identity import identity_engine
from test_identity_migration import migration


MODELS = (FecCommitteeRecord, FecCandidateCommitteeLink, CommitteeFiling, CommitteeFinanceSnapshot)


@pytest.mark.parametrize("value", [1787, 2023, 9999, 10000, True, "2024", 2024.0])
def test_invalid_financial_cycles(value):
    with pytest.raises(ValueError, match="even year"):
        validate_cycle(value)


def test_cycle_dates_and_candidate_election_year_are_distinct():
    assert cycle_for_date(date(2023, 1, 1)) == 2024
    assert cycle_for_date(date(2024, 12, 31)) == 2024
    assert cycle_for_date(date(2025, 1, 1)) == 2026
    validate_cycle(1788)
    validate_cycle(9998)


def test_offline_migration_is_additive_and_reversible():
    for direction in ("upgrade", "downgrade"):
        output = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
        with Operations.context(context):
            getattr(migration("campaign_finance.py"), direction)()
        sql = output.getvalue().lower()
        for model in MODELS:
            assert f"{'create' if direction == 'upgrade' else 'drop'} table {model.__tablename__}" in sql
        if direction == "upgrade":
            assert "fk_committee_finance_filing_scope" in sql
            assert "ck_committee_relationship_two_year_cycle" in sql
            assert "drop table" not in sql and "delete from" not in sql


def release(session, source, token="a"):
    row = SourceRelease(source_id=source.id, version="2024", sha256=token * 64,
        filename="fixture.json", file_id=0, download_url="https://www.fec.gov/data/",
        raw_path=f"fixture/{token}.json", retrieved_at=datetime(2026, 11, 16, tzinfo=timezone.utc), metadata_json={})
    session.add(row)
    session.flush()
    return row


def seed(session):
    source = DataSource(name="fec_finance_fixture", url="https://www.fec.gov")
    session.add(source)
    session.flush()
    pinned = release(session, source)
    committee = attach_external_identifier(session, namespace="fec", identifier_type="committee",
        value="C00000001", source_id=source.id, release_id=pinned.id)
    candidate = attach_external_identifier(session, namespace="fec", identifier_type="candidate",
        value="S0NY00001", source_id=source.id, release_id=pinned.id)
    return source, pinned, committee, candidate


def snapshot(pinned, committee, **changes):
    values = dict(release_id=pinned.id, source_record_key="cycle:2024", committee_identifier_id=committee.id,
        cycle=2024, period_kind="cycle", coverage_start=date(2023, 1, 1), coverage_end=date(2024, 12, 31),
        receipts=Decimal("100.00"), disbursements=Decimal("80.00"), raw_json={"receipts": "100.00"})
    return CommitteeFinanceSnapshot(**(values | changes))


def filing(pinned, committee, **changes):
    values = dict(release_id=pinned.id, source_record_key="filing:1", committee_identifier_id=committee.id,
        cycle=2024, file_number=1, form_type="F3", report_type="Q1", amendment_indicator="N",
        is_amended=False, coverage_start=date(2023, 1, 1), coverage_end=date(2023, 3, 31), raw_json={})
    return CommitteeFiling(**(values | changes))


def selected(session, pinned, committee, **changes):
    values = dict(release_id=pinned.id, committee_identifier_id=committee.id, cycle=2024,
        coverage_start=date(2023, 1, 1), coverage_end=date(2024, 12, 31))
    return committee_finance(session, **(values | changes))


@pytest.mark.integration
def test_committee_and_linkage_replay_preserves_unresolved_and_overlapping_cycles(identity_engine):
    with Session(identity_engine) as session, session.begin():
        _, pinned, committee, candidate = seed(session)
        for cycle in (2022, 2024):
            values = dict(release_id=pinned.id, identifier_id=committee.id, cycle=cycle,
                          name="Example campaign", designation="P", committee_type="S", raw_json={})
            first, inserted = store_finance_record(session, FecCommitteeRecord(**values))
            second, repeated = store_finance_record(session, FecCommitteeRecord(**values))
            assert inserted and not repeated and second.id == first.id
            link = dict(release_id=pinned.id, linkage_id=cycle, candidate_identifier_id=candidate.id,
                committee_identifier_id=committee.id, cycle=cycle, election_year=2026, designation="P", raw_json={})
            stored, inserted = store_finance_record(session, FecCandidateCommitteeLink(**link))
            replay, repeated = store_finance_record(session, FecCandidateCommitteeLink(**link))
            assert inserted and not repeated and stored.id == replay.id
            assert stored.election_year != stored.cycle
        missing, _ = store_finance_record(session, FecCandidateCommitteeLink(release_id=pinned.id, linkage_id=99,
            candidate_identifier_id=candidate.id, cycle=2024, election_year=2025, raw_json={}))
        assert missing.committee_identifier_id is None
        assert session.get(ExternalIdentifier, candidate.id).person_id is None
        assert session.scalar(select(func.count()).select_from(CommitteeRelationship)) == 0
        assert session.scalar(select(func.count()).select_from(FecCommitteeRecord)) == 2
        with pytest.raises(IdentityConflictError, match="different payload"):
            store_finance_record(session, FecCommitteeRecord(**(values | {"name": "Changed name"})))


@pytest.mark.integration
def test_existing_candidacy_links_allow_shared_committee_and_require_even_cycles(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, pinned, _, _ = seed(session)
        organization = register_organization(session, name="Shared campaign", kind="committee", creation_key="fec:C00000001")
        person = Person(full_name="Example candidate")
        jurisdiction = Jurisdiction(name="New York", level="state", state_code="NY")
        session.add_all([person, jurisdiction])
        session.flush()
        for event_date in (date(2024, 6, 1), date(2024, 11, 1), date(2025, 11, 1)):
            event = Election(election_date=event_date, election_type="special", jurisdiction_id=jurisdiction.id)
            session.add(event)
            session.flush()
            contest = Contest(office_name="US Senate", election_id=event.id, jurisdiction_id=jurisdiction.id)
            session.add(contest)
            session.flush()
            candidate = Candidacy(person_id=person.id, contest_id=contest.id)
            session.add(candidate)
            session.flush()
            values = dict(organization_id=organization.id, candidacy_id=candidate.id, person_id=person.id,
                source_id=source.id, release_id=pinned.id, cycle=cycle_for_date(event.election_date), role="principal")
            first = link_committee(session, **values)
            assert link_committee(session, **values).id == first.id
        assert session.scalar(select(func.count()).select_from(CommitteeRelationship)) == 3
        with pytest.raises(ValueError, match="even year"):
            link_committee(session, **(values | {"cycle": 2025}))


@pytest.mark.integration
def test_cycle_snapshots_corrections_and_exact_period_selection(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, pinned, committee, _ = seed(session)
        original, inserted = store_finance_record(session, snapshot(pinned, committee))
        repeated, replay_inserted = store_finance_record(session, snapshot(pinned, committee))
        assert inserted and not replay_inserted and repeated.id == original.id
        newer = release(session, source, "b")
        corrected, _ = store_finance_record(session, snapshot(newer, committee,
            receipts=Decimal("110.00"), supersedes_id=original.id, raw_json={"receipts": "110.00"}))
        assert selected(session, pinned, committee)["total_raised"] == Decimal("100.00")
        result = selected(session, newer, committee)
        assert result["total_raised"] == Decimal("110.00") and result["total_spent"] == Decimal("80.00")
        assert result["snapshot_id"] == corrected.id and result["release_id"] == newer.id
        assert selected(session, pinned, committee, coverage_end=date(2024, 9, 30))["status"] == "missing"
        assert selected(session, pinned, committee, cycle=2022)["status"] == "missing"
        assert selected(session, pinned, committee, period_kind="report")["status"] == "missing"
        assert session.get(CommitteeFinanceSnapshot, original.id).receipts == Decimal("100.00")
        with pytest.raises(IdentityConflictError, match="different payload"):
            store_finance_record(session, snapshot(pinned, committee, receipts=Decimal("999.00")))
        store_finance_record(session, snapshot(newer, committee, source_record_key="conflicting-source-row"))
        result = selected(session, newer, committee)
        assert result["status"] == "ambiguous" and result["total_raised"] is None and result["total_spent"] is None


@pytest.mark.integration
@pytest.mark.parametrize("changed_coverage", [False, True])
def test_report_amendment_replaces_original_without_summing_or_inferred_dates(identity_engine, changed_coverage):
    with Session(identity_engine) as session, session.begin():
        _, pinned, committee, _ = seed(session)
        original, inserted = store_finance_record(session, filing(pinned, committee))
        replay, repeated = store_finance_record(session, filing(pinned, committee))
        assert inserted and not repeated and replay.id == original.id
        old, _ = store_finance_record(session, snapshot(pinned, committee, source_record_key="report:1",
            period_kind="report", filing_id=original.id, coverage_end=original.coverage_end))
        corrected_end = date(2023, 3, 30) if changed_coverage else original.coverage_end
        amended, _ = store_finance_record(session, filing(pinned, committee, source_record_key="filing:2",
            file_number=2, previous_file_number=1, supersedes_id=original.id, amendment_indicator="A", coverage_end=corrected_end))
        store_finance_record(session, snapshot(pinned, committee, source_record_key="report:2", period_kind="report",
            filing_id=amended.id, coverage_end=corrected_end, receipts=Decimal("125.00")))
        result = selected(session, pinned, committee, period_kind="report", coverage_end=corrected_end)
        assert result["total_raised"] == Decimal("125.00") and result["filing_id"] == amended.id
        assert session.get(CommitteeFinanceSnapshot, old.id).receipts == Decimal("100.00")
        if changed_coverage:
            assert selected(session, pinned, committee, period_kind="report", coverage_end=original.coverage_end)["status"] == "missing"
        assert selected(session, pinned, committee)["status"] == "missing"


@pytest.mark.integration
@pytest.mark.parametrize("flag,status", [(None, "unverified"), (True, "missing"), (False, "available")])
def test_paper_filing_without_number_and_explicit_source_amendment_status(identity_engine, flag, status):
    with Session(identity_engine) as session, session.begin():
        _, pinned, committee, _ = seed(session)
        report, _ = store_finance_record(session, filing(pinned, committee, file_number=None, is_amended=flag))
        store_finance_record(session, snapshot(pinned, committee, period_kind="report", filing_id=report.id,
            coverage_end=report.coverage_end))
        result = selected(session, pinned, committee, period_kind="report", coverage_end=report.coverage_end)
        assert result["status"] == status


@pytest.mark.integration
@pytest.mark.parametrize("second_flag,status", [(False, "ambiguous"), (None, "unverified")])
def test_competing_reports_do_not_silently_choose_a_filing(identity_engine, second_flag, status):
    with Session(identity_engine) as session, session.begin():
        _, pinned, committee, _ = seed(session)
        for number, flag in ((1, False), (2, second_flag)):
            report, _ = store_finance_record(session, filing(pinned, committee,
                source_record_key=f"filing:{number}", file_number=number, is_amended=flag))
            store_finance_record(session, snapshot(pinned, committee, source_record_key=f"report:{number}",
                period_kind="report", filing_id=report.id, coverage_end=report.coverage_end))
        result = selected(session, pinned, committee, period_kind="report", coverage_end=report.coverage_end)
        assert result["status"] == status
        assert result["total_raised"] is None and result["total_spent"] is None


@pytest.mark.integration
def test_same_release_correction_replaces_only_its_predecessor(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, pinned, committee, _ = seed(session)
        original, _ = store_finance_record(session, snapshot(pinned, committee))
        replacement, _ = store_finance_record(session, snapshot(pinned, committee, source_record_key="corrected:2024",
            supersedes_id=original.id, receipts=Decimal("125.00")))
        unrelated = attach_external_identifier(session, namespace="fec", identifier_type="committee",
            value="C00000002", source_id=source.id)
        store_finance_record(session, snapshot(pinned, unrelated, source_record_key="unrelated:2024", receipts=Decimal("999.00")))
        result = selected(session, pinned, committee)
        assert result["total_raised"] == Decimal("125.00") and result["snapshot_id"] == replacement.id
        with pytest.raises(ValueError, match="transient record"):
            store_finance_record(session, replacement)


@pytest.mark.integration
def test_database_rejects_duplicate_filing_number_with_different_source_key(identity_engine):
    with Session(identity_engine) as session, session.begin():
        _, pinned, committee, _ = seed(session)
        store_finance_record(session, filing(pinned, committee))
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(filing(pinned, committee, source_record_key="duplicate-file"))
            session.flush()


@pytest.mark.integration
def test_missing_signed_and_zero_amounts_are_not_imputed(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, pinned, committee, _ = seed(session)
        store_finance_record(session, snapshot(pinned, committee, receipts=None, disbursements=Decimal("0.00"),
            cash_on_hand_end=Decimal("-1.25"), debts_owed_by=Decimal("0.00")))
        result = selected(session, pinned, committee)
        assert result["status"] == "partial" and result["total_raised"] is None and result["total_spent"] == 0
        assert result["cash_on_hand_end"] == Decimal("-1.25")
        newer = release(session, source, "b")
        store_finance_record(session, snapshot(newer, committee, receipts=Decimal("-1.25")))
        assert selected(session, newer, committee)["total_raised"] == Decimal("-1.25")


@pytest.mark.integration
@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), Decimal("1.005"), Decimal("1e16"), 1.5])
def test_invalid_amounts_fail_before_database_rounding(identity_engine, amount):
    with Session(identity_engine) as session, session.begin():
        _, pinned, committee, _ = seed(session)
        with pytest.raises(ValueError, match="finite Decimal"):
            store_finance_record(session, snapshot(pinned, committee, receipts=amount))
        assert session.scalar(select(func.count()).select_from(CommitteeFinanceSnapshot)) == 0


@pytest.mark.integration
def test_wrong_identity_scope_and_lineage_are_rejected(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, pinned, committee, candidate = seed(session)
        with pytest.raises(ValueError, match="committee identifier"):
            store_finance_record(session, snapshot(pinned, candidate))
        original, _ = store_finance_record(session, snapshot(pinned, committee))
        with pytest.raises(IdentityConflictError, match="different financial scope"):
            store_finance_record(session, snapshot(pinned, committee, source_record_key="bad-lineage",
                supersedes_id=original.id, coverage_end=date(2024, 9, 30)))
        report, _ = store_finance_record(session, filing(pinned, committee))
        newer = release(session, source, "b")
        with pytest.raises(IdentityConflictError, match="filing scope"):
            store_finance_record(session, snapshot(newer, committee, period_kind="report", filing_id=report.id,
                coverage_end=report.coverage_end))
        with pytest.raises(IdentityConflictError, match="previous_file_number"):
            store_finance_record(session, filing(pinned, committee, source_record_key="bad-predecessor",
                supersedes_id=report.id, previous_file_number=99))


@pytest.mark.integration
@pytest.mark.parametrize("changes", [dict(cycle=2023), dict(coverage_start=date(2022, 1, 1)),
    dict(coverage_end=date(2025, 1, 1)), dict(coverage_start=date(2025, 1, 1)), dict(period_kind="report")])
def test_database_rejects_invalid_snapshot_periods(identity_engine, changes):
    with Session(identity_engine) as session, session.begin():
        _, pinned, committee, _ = seed(session)
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(snapshot(pinned, committee, **changes))
            session.flush()


@pytest.mark.integration
@pytest.mark.parametrize("change", ["release", "committee", "cycle", "coverage"])
def test_database_enforces_report_filing_scope(identity_engine, change):
    with Session(identity_engine) as session, session.begin():
        source, pinned, committee, _ = seed(session)
        report, _ = store_finance_record(session, filing(pinned, committee))
        other = attach_external_identifier(session, namespace="fec", identifier_type="committee", value="C00000002", source_id=source.id)
        changes = {"release": dict(release_id=release(session, source, "b").id),
                   "committee": dict(committee_identifier_id=other.id),
                   "cycle": dict(cycle=2022), "coverage": dict(coverage_end=date(2023, 3, 30))}[change]
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(snapshot(pinned, committee, period_kind="report", filing_id=report.id,
                **(dict(coverage_end=report.coverage_end) | changes)))
            session.flush()


@pytest.mark.integration
def test_batch_transaction_rolls_back(identity_engine):
    with Session(identity_engine) as session, session.begin():
        _, pinned, committee, _ = seed(session)
        ids = pinned.id, committee.id
    with pytest.raises(ValueError), Session(identity_engine) as session, session.begin():
        pinned, committee = session.get(SourceRelease, ids[0]), session.get(ExternalIdentifier, ids[1])
        store_finance_record(session, snapshot(pinned, committee))
        store_finance_record(session, snapshot(pinned, committee, source_record_key="invalid", receipts=Decimal("NaN")))
    with Session(identity_engine) as session:
        assert session.scalar(select(func.count()).select_from(CommitteeFinanceSnapshot)) == 0


@pytest.mark.integration
def test_migration_roundtrip_matches_models_and_preserves_existing_data(identity_engine):
    with identity_engine.begin() as connection:
        for model in reversed(MODELS):
            model.__table__.drop(connection)
        connection.execute(text("ALTER TABLE committee_relationship DROP CONSTRAINT ck_committee_relationship_two_year_cycle"))
        person_id = uuid4()
        connection.execute(text("INSERT INTO person (id, full_name) VALUES (:id, 'Existing person')"), {"id": person_id})
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration("campaign_finance.py").upgrade()
        assert set(model.__tablename__ for model in MODELS) <= set(inspect(connection).get_table_names())
        assert compare_metadata(context, Base.metadata) == []
        with Operations.context(context):
            migration("campaign_finance.py").downgrade()
        assert connection.scalar(text("SELECT full_name FROM person WHERE id=:id"), {"id": person_id}) == "Existing person"
        assert "candidate_finance_summary" in inspect(connection).get_table_names()
        with Operations.context(context):
            migration("campaign_finance.py").upgrade()


@pytest.mark.integration
def test_fresh_database_migration_chain_reaches_current_head(identity_engine):
    # The guarded fixture supplies a disposable database. A second, empty schema
    # exercises historical migration code instead of metadata.create_all.
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "presidential_state_coverage"
    schema = "finance_migrate_" + uuid4().hex
    with identity_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for revision in reversed(list(script.walk_revisions())):
                revision.module.upgrade()
        tables = set(inspect(connection).get_table_names())
        assert {model.__tablename__ for model in MODELS} <= tables
        assert {"person", "committee_relationship", "candidate_finance_summary"} <= tables
        assert compare_metadata(context, Base.metadata) == []
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
