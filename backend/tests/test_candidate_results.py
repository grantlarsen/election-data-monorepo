"""The profile reuses published candidate totals, pagination and provenance."""
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Candidacy
from test_election_api import api_engine, client, populated
from test_data004_postgres import pg, migration


@pytest.fixture(autouse=True)
def candidate_tables(api_engine):
    with api_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration("candidate_identity_review.py").upgrade()


@pytest.mark.integration
def test_profile_exposes_only_selected_candidacy_published_returns(client, populated, api_engine):
    with Session(api_engine) as session:
        candidate = session.scalar(select(Candidacy).where(Candidacy.source_label == "ALICE"))
        candidate_id = candidate.id
    response = client.get(f"/api/v1/candidates/{candidate_id}")
    assert response.status_code == 200, response.text
    profile = response.json()
    assert profile["id"] == str(candidate_id)
    assert profile["identity_status"] == "unresolved"
    assert profile["finance"]["status"] == "identity_unresolved"
    assert profile["finance"]["total_raised"] is None
    assert profile["finance"]["total_spent"] is None
    assert profile["results"]["total"] == 1
    result = profile["results"]["items"][0]
    assert result["candidacy_id"] == str(candidate_id)
    assert result["votes"] == 100
    assert result["publication"]["batch_id"] == str(populated["batch"])
    assert result["publication"]["source"]["sha256"]
    assert client.get(f"/api/v1/candidates/{candidate_id}?offset=100").json()["results"]["items"] == []
    assert client.get(f"/api/v1/candidates/{candidate_id}?reporting_level=precinct").json()["results"]["total"] == 0
