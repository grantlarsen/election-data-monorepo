"""Offline request validation, health compatibility and failure contracts."""
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import OperationalError

from app.main import app
from app.api import elections


@pytest.fixture
def client():
    app.dependency_overrides[elections.get_read_session] = lambda: None
    try:
        with TestClient(app) as http:
            yield http
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('endpoint', ['elections', 'contests', 'results', 'state-results'])
@pytest.mark.parametrize('params', [
    {'limit': 0}, {'limit': 201}, {'offset': -1}, {'year': 0}, {'year': 9999},
    {'office_id': 'invalid'}, {'party_id': 'invalid'}, {'jurisdiction_id': 'invalid'},
    {'stage': 'unknown'}, {'state_code': 'ZZ'}, {'office': '   '}, {'unexpected': 'value'},
])
def test_invalid_queries_are_rejected(client, endpoint, params):
    assert client.get('/api/v1/' + endpoint, params=params).status_code == 422


def test_health_and_openapi_contract(client):
    assert client.get('/health').json() == {'status': 'ok', 'service': 'electoral-api'}
    schema = client.get('/openapi.json').json()
    for endpoint in ('elections', 'contests', 'results', 'state-results'):
        operation = schema['paths']['/api/v1/' + endpoint]['get']
        assert '200' in operation['responses']
    assert client.get('/api/v1/results', params={'reporting_level': 'state'}).status_code == 422
    assert client.get('/api/v1/state-results', params={'party_id': str(uuid4())}).status_code == 422


def test_database_errors_are_sanitized(monkeypatch):
    def unavailable():
        raise OperationalError('sensitive SQL', {}, RuntimeError('password=private'))
    monkeypatch.setattr(elections, 'SessionLocal', unavailable)
    with TestClient(app) as http:
        response = http.get('/api/v1/contests')
    assert response.status_code == 503 and response.json() == {'detail': 'Database unavailable'}
