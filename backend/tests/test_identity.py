"""DATA-002 PostgreSQL integration scenarios; never run against production."""
from datetime import date, datetime, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Production dependencies are installed in the Docker API image.
pytest.importorskip("psycopg")
from app.database import Base
import app.models  # noqa: F401
import app.models.ingestion  # noqa: F401
from app.models.core import Candidacy, Contest, DataSource, Election, Jurisdiction, Person, PoliticalParty
from app.models.identity import (
    CommitteeRelationship, ExternalIdentifier, IdentityAssignmentEvent,
    Organization, PersonName,
)
from app.models.ingestion import ElectionResultObservation, SourceRelease
from app.services.identity import (
    IdentityConflictError, add_person_name, attach_external_identifier,
    create_person, get_person_identity, link_committee, lookup_canonical,
    lookup_identifier, register_organization, resolve_external_identifier,
)


@pytest.fixture
def identity_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires TEST_DATABASE_URL ending _test")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("refusing to modify database not ending _test")
    schema = "identity_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed(session):
    source = DataSource(name="fec_test", url="https://www.fec.gov")
    medsl = DataSource(name="medsl_test", url="https://example.invalid/medsl")
    party = PoliticalParty(name="DEMOCRATIC")
    session.add_all((source, medsl, party))
    session.flush()
    return source, medsl, party


@pytest.mark.integration
def test_multiple_ids_idempotence_and_identical_names(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, _, _ = seed(session)
        state_source = DataSource(name="state_ny_test", url="https://elections.ny.gov")
        session.add(state_source)
        session.flush()
        a = create_person(session, full_name="Alex Smith", creation_key="manual:alex-1")
        b = create_person(session, full_name="Alex Smith", creation_key="manual:alex-2")
        assert a.id != b.id
        assert create_person(session, full_name="Alex Smith", creation_key="manual:alex-1").id == a.id
        assert session.scalar(select(func.count()).select_from(Person)) == 2
        for namespace, value in (("fec", "H8ZZ00001"), ("state:ny:boe", "CAND-100")):
            kwargs = dict(namespace=namespace, identifier_type="candidate", value=value,
                          source_id=source.id if namespace == "fec" else state_source.id,
                          target_type="person", target_id=a.id,
                          actor="fixture", evidence="verified registration match")
            original = attach_external_identifier(session, **kwargs)
            assert attach_external_identifier(session, **kwargs).id == original.id
            assert lookup_canonical(session, namespace=namespace,
                                    identifier_type="candidate", value=value).id == a.id
        assert len(get_person_identity(session, a.id)["identifiers"]) == 2
        assert len(get_person_identity(session, b.id)["identifiers"]) == 0
        assert session.scalar(select(func.count()).select_from(IdentityAssignmentEvent)) == 2
        with pytest.raises(IdentityConflictError):
            attach_external_identifier(session, namespace="fec", identifier_type="candidate",
                                       value="H8ZZ00001", source_id=source.id,
                                       target_type="person", target_id=b.id,
                                       actor="fixture", evidence="ambiguous duplicate")
        assert lookup_canonical(session, namespace="fec", identifier_type="candidate",
                                value="H8ZZ00001").id == a.id
        with pytest.raises(IdentityConflictError):
            create_person(session, full_name="Different Person", creation_key="manual:alex-1")
    with Session(identity_engine) as session:
        assert session.scalar(select(func.count()).select_from(Person)) == 2
        assert session.scalar(select(func.count()).select_from(ExternalIdentifier)) == 2


@pytest.mark.integration
def test_alias_history_and_source_attribution(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, _, _ = seed(session)
        person = create_person(session, full_name="Jordan Rivera", creation_key="manual:jordan")
        prior = add_person_name(session, person_id=person.id, name_raw="Jordan Brown",
                                kind="former", valid_until=date(2017, 12, 31),
                                source_id=source.id, source_record_key="evidence:1")
        assert add_person_name(session, person_id=person.id, name_raw="Jordan Brown",
                               kind="former", valid_until=date(2017, 12, 31),
                               source_id=source.id, source_record_key="evidence:1").id == prior.id
        alias = add_person_name(session, person_id=person.id, name_raw="J. Rivera", kind="source_reported",
                                source_id=source.id, source_record_key="evidence:2", evidence="Original field")
        assert alias.source_id == source.id
        assert {n.name_raw for n in get_person_identity(session, person.id)["names"]} == {"Jordan Brown", "J. Rivera"}
        with pytest.raises(ValueError):
            add_person_name(session, person_id=person.id, name_raw="Name", kind="source_reported")
        with pytest.raises(ValueError):
            add_person_name(session, person_id=person.id, name_raw="Wrong date", kind="alias",
                            valid_from=date(2025, 1, 1), valid_until=date(2020, 1, 1))


@pytest.mark.integration
def test_organizations_party_committee_cycles_and_unresolved(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, medsl, party = seed(session)
        person = create_person(session, full_name="Taylor Lee", creation_key="manual:taylor")
        orgs = [register_organization(session, name=f"Taylor Committee {cycle}",
                                      kind="committee", creation_key=f"committee:{cycle}", party_id=party.id)
                for cycle in (2024, 2026)]
        assert register_organization(session, name="Taylor Committee 2024", kind="committee",
                                     creation_key="committee:2024", party_id=party.id).id == orgs[0].id
        with pytest.raises(IdentityConflictError):
            register_organization(session, name="Changed Committee", kind="committee",
                                  creation_key="committee:2024", party_id=party.id)
        assert orgs[0].party_id == party.id
        for index, org in enumerate(orgs):
            linked = attach_external_identifier(session, namespace="fec", identifier_type="committee",
                         value=f"C0099000{index}", source_id=source.id,
                         target_type="organization", target_id=org.id,
                         actor="fixture", evidence="Committee master test fixture")
            assert lookup_canonical(session, namespace="fec", identifier_type="committee",
                                    value=f"C0099000{index}").id == org.id
            assert linked.organization_id == org.id
        with pytest.raises(ValueError):
            attach_external_identifier(session, namespace="fec", identifier_type="committee",
                         value="C00999999", source_id=source.id,
                         target_type="person", target_id=person.id,
                         actor="fixture", evidence="Invalid target")
        loc = Jurisdiction(name="Test", level="state", state_code="NY")
        session.add(loc)
        session.flush()
        election = Election(election_date=date(2024, 11, 5), election_type="general", jurisdiction_id=loc.id)
        session.add(election)
        session.flush()
        contest = Contest(office_name="U.S. House", election_id=election.id, jurisdiction_id=loc.id)
        session.add(contest)
        session.flush()
        candidacy = Candidacy(person_id=person.id, contest_id=contest.id, party_id=party.id)
        session.add(candidacy)
        session.flush()
        attach_external_identifier(session, namespace="fec", identifier_type="candidate",
                  value="H8ZZ42424", source_id=source.id, target_type="candidacy",
                  target_id=candidacy.id, actor="fixture", evidence="Candidacy-specific ID")
        assert lookup_canonical(session, namespace="fec", identifier_type="candidate",
                                value="H8ZZ42424").id == candidacy.id
        rels = [link_committee(session, organization_id=o.id, source_id=source.id,
                               role="authorized", person_id=person.id,
                               candidacy_id=candidacy.id if cycle == 2024 else None,
                               cycle=cycle, valid_from=date(cycle - 1, 1, 1),
                               source_record_key=f"fec-link-{cycle}", evidence="FEC linkage")
                for o, cycle in zip(orgs, (2024, 2026))]
        assert link_committee(session, organization_id=orgs[0].id, source_id=source.id,
                              role="authorized", person_id=person.id,
                              candidacy_id=candidacy.id, cycle=2024,
                              valid_from=date(2023, 1, 1), source_record_key="fec-link-2024",
                              evidence="FEC linkage").id == rels[0].id
        assert {r.cycle for r in get_person_identity(session, person.id)["committees"]} == {2024, 2026}
        assert all(r.source_id == source.id for r in rels)
        unknown = attach_external_identifier(session, namespace="fec", identifier_type="candidate",
                                             value="H8ZZ99999", source_id=source.id,
                                             label_raw="Unknown Candidate", source_record_key="unknown-1")
        assert lookup_canonical(session, namespace="fec", identifier_type="candidate", value="H8ZZ99999") is None
        assert all(getattr(unknown, key) is None for key in ("person_id", "candidacy_id", "organization_id", "party_id"))
        resolved = resolve_external_identifier(session, identifier_id=unknown.id, target_type="person",
                                               target_id=person.id, actor="reviewer", evidence="Verified FEC record")
        assert resolved.person_id == person.id
        assert resolve_external_identifier(session, identifier_id=unknown.id, target_type="person",
                                           target_id=person.id, actor="reviewer", evidence="Verified FEC record").id == unknown.id
        assert session.scalar(select(func.count()).select_from(IdentityAssignmentEvent)) == 4
        other = create_person(session, full_name="Other", creation_key="manual:other")
        with pytest.raises(IdentityConflictError):
            resolve_external_identifier(session, identifier_id=unknown.id, target_type="person",
                                        target_id=other.id, actor="reviewer", evidence="Invalid override")
        assert unknown.person_id == person.id
        # An unlinked MEDSL *label* is not a source identifier and must not be minted as a person.
        release = SourceRelease(source_id=medsl.id, version="fixture", sha256="a" * 64,
                                filename="fixture.csv", file_id=1,
                                download_url="https://example.invalid/test.csv", raw_path="test.csv",
                                retrieved_at=datetime.now(timezone.utc), metadata_json={})
        session.add(release)
        session.flush()
        with pytest.raises(IdentityConflictError):
            attach_external_identifier(session, namespace="state:ny:boe", identifier_type="candidate",
                        value="CAND-INVALID", source_id=source.id, release_id=release.id)
        row = ElectionResultObservation(release_id=release.id, source_row_number=2,
             row_sha256="b" * 64, logical_key="c" * 64, year=2024,
             state_code="NY", state_fips="36", candidate_raw="ALEX SMITH",
             candidate_normalized="ALEX SMITH", candidate_kind="candidate",
             party_raw="DEMOCRAT", raw_json={"candidate": "ALEX SMITH"}, warnings_json=[])
        session.add(row)
        session.flush()
        assert row.candidacy_id is None
        assert session.scalar(select(func.count()).select_from(Person)) == 2
        assert session.scalar(select(func.count()).select_from(CommitteeRelationship)) == 2


@pytest.mark.integration
def test_db_constraints_fk_and_rollback(identity_engine):
    with Session(identity_engine) as session, session.begin():
        source, _, _ = seed(session)
        person = create_person(session, full_name="Distinct", creation_key="manual:distinct")
        registered = attach_external_identifier(session, namespace="fec", identifier_type="candidate",
                              value="H8ZZ11111", source_id=source.id, target_type="person", target_id=person.id,
                              actor="fixture", evidence="proof")
        linked_id = registered.id
        other_id = create_person(session, full_name="Second", creation_key="manual:second").id
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(ExternalIdentifier(namespace="fec", identifier_type="candidate",
                     value="H8ZZ11111", source_id=source.id, person_id=other_id))
                session.flush()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(PersonName(person_id=uuid4(), name_raw="Invalid", kind="alias", dedupe_key="f" * 64))
                session.flush()
        assert session.get(ExternalIdentifier, linked_id).person_id == person.id
    with Session(identity_engine) as session:
        assert session.scalar(select(func.count()).select_from(ExternalIdentifier)) == 1
