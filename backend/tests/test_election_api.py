"""HTTP contracts on real, migrated PostgreSQL in isolated disposable schemas."""
from datetime import date
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.main import app
from app.api.elections import get_read_session
from app.models.core import Candidacy, Contest, Jurisdiction, PoliticalParty
from app.models.election import BallotLine, CanonicalPublication, CanonicalResultBatch, CanonicalVoteReturn
from app.models.geography import GeographicReference, GeographicResolution
from app.models.ingestion import SourceRelease
from app.services import elections
from app.services.canonical_results import materialize_medsl_year
from app.services.fec_state_results import plan, publish
from test_data003_postgres import _seed, _observe
from test_data004_postgres import pg, migration
from test_fec_state_authority import official_fixture, seed_comparison


@pytest.fixture
def api_engine(pg):
    with pg.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration('authoritative_state_results.py').upgrade()
        migration('reviewed_county_corrections.py').upgrade()
        migration('senate_return_evidence.py').upgrade()
    return pg


@pytest.fixture
def client(api_engine):
    def session_override():
        with Session(api_engine) as session, session.begin():
            session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            yield session
    app.dependency_overrides[get_read_session] = session_override
    try:
        with TestClient(app) as http:
            yield http
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def populated(api_engine):
    with Session(api_engine) as session, session.begin():
        seed = _seed(session)
        for n, (label, votes, kind) in enumerate([
            ('ALICE', 100, 'candidate'), ('BOB', 80, 'candidate'),
            ('OTHER', 5, 'aggregate'), ('WRITEIN', 2, 'write_in'),
        ], 2):
            _observe(session, seed, n, name=label, votes=votes, total=187, kind=kind)
        _observe(session, seed, 6, name='ALICE', votes=9, total=9, mode='PROVISIONAL')
        ids = dict(state=seed['state'].id, county=seed['county'].id, reference=seed['ref'].id)
    with Session(api_engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        report = materialize_medsl_year(session, year=2008, dry_run=False, allow_partial=True)
        party = PoliticalParty(name='Example party')
        session.add(party)
        session.flush()
        alice = session.scalar(select(Candidacy).where(Candidacy.source_label == 'ALICE'))
        alice.party_id = party.id
        contest = session.get(Contest, alice.contest_id)
        ids.update(batch=UUID(report['batch_id']), contest=contest.id,
                   election=contest.election_id, office=contest.office_id, party=party.id)
        # Discovery includes modeled events even before a source is published.
        event = elections.election(session, creation_key='future-house-primary', election_date=date(2024, 6, 1),
                                   election_type='primary', jurisdiction_id=ids['state'], election_cycle=2024)
        office = elections.office(session, creation_key='house', name='U.S. House', office_kind='legislative')
        empty = elections.contest(session, creation_key='empty-house', office_name='U.S. House',
                                  office_id=office.id, election_id=event.id, jurisdiction_id=ids['state'])
        ids.update(empty=empty.id, house=office.id)
    return ids


@pytest.mark.integration
def test_discovery_filters_pagination_and_unpublished_events(client, populated):
    response = client.get('/api/v1/elections', params={'limit': 1}).json()
    assert response['total'] == 2 and response['has_more']
    assert response['items'][0]['election_date'] == '2024-06-01'
    assert response['items'][0]['publications'] == []
    for path in ('elections', 'contests'):
        params = dict(year=2008, office_id=str(populated['office']), stage='general',
                      party_id=str(populated['party']), state_code='ny', jurisdiction_id=str(populated['county']))
        data = client.get('/api/v1/' + path, params=params).json()
        assert data['total'] == 1
        publication = data['items'][0]['publications'][0]
        assert publication['batch_id'] == str(populated['batch'])
        assert publication['status'] == 'PARTIAL' and publication['excluded_rows'] == 1
        assert publication['coverage_scope'] == 'publication'
        assert not publication['county_coverage_verified']
        assert publication['source']['sha256'] == '1' * 64
    data = client.get('/api/v1/contests', params={'office': 'u.s. house', 'stage': 'primary'}).json()
    assert data['total'] == 1 and data['items'][0]['publications'] == []
    assert client.get('/api/v1/contests', params={'office_id': str(populated['house']), 'stage': 'general'}).json()['total'] == 0


@pytest.mark.integration
def test_results_preserve_buckets_lineage_and_partial_coverage(client, populated):
    response = client.get('/api/v1/results', params={'year': 2008})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['total'] == 4 and sum(item['votes'] for item in data['items']) == 187
    assert not data['additive_with_state_results']
    assert data['reporting_level'] == 'county' and data['reporting_mode'] == 'TOTAL'
    buckets = {item['label']: item for item in data['items']}
    assert buckets['OTHER']['candidacy_id'] is None and buckets['OTHER']['basis'] == 'aggregate'
    assert buckets['WRITEIN']['candidacy_id'] is None and buckets['WRITEIN']['basis'] == 'write_in'
    for item in data['items']:
        assert item['person_id'] is None
        assert item['geographic_reference_id'] == str(populated['reference'])
        assert item['reference_vintage_start'] == 2008
        assert len(item['observation_ids']) == 1
        assert item['publication']['status'] == 'PARTIAL'
        assert 'raw_path' not in item['publication']['source']


@pytest.mark.integration
@pytest.mark.parametrize('field,value', [
    ('year', 2004), ('stage', 'runoff'), ('office', 'unavailable office'),
    ('office_id', str(uuid4())), ('party_id', str(uuid4())), ('state_code', 'CA'),
    ('jurisdiction_id', str(uuid4())), ('election_id', str(uuid4())),
    ('contest_id', str(uuid4())), ('reporting_mode', 'PROVISIONAL'), ('reporting_level', 'precinct'),
])
def test_result_filters_do_not_fabricate_zeros(client, populated, field, value):
    response = client.get('/api/v1/results', params={field: value})
    assert response.status_code == 200, response.text
    assert response.json()['items'] == [] and response.json()['total'] == 0
    assert response.json()['availability'] == 'no_matching_published_results'


@pytest.mark.integration
def test_exact_result_geography_and_candidate_party_filters(client, populated):
    params = {k + '_id': str(populated[k]) for k in ('office', 'party', 'election', 'contest')}
    params.update(year=2008, stage='general', state_code='NY', jurisdiction_id=str(populated['county']))
    data = client.get('/api/v1/results', params=params).json()
    assert data['total'] == 1 and data['items'][0]['label'] == 'ALICE'
    assert data['items'][0]['votes'] == 100
    # A state is a discovery scope; it must not silently turn county results into state totals.
    assert client.get('/api/v1/results', params={'jurisdiction_id': str(populated['state'])}).json()['total'] == 0


@pytest.mark.integration
def test_stable_pages_no_duplicate_candidates_and_offset_semantics(client, populated):
    whole = client.get('/api/v1/results').json()
    paged = []
    for offset in range(4):
        response = client.get('/api/v1/results', params={'limit': 1, 'offset': offset}).json()
        assert response['total'] == 4
        assert response['has_more'] == (offset < 3)
        paged.extend(response['items'])
    assert paged == whole['items']
    for endpoint in ('results', 'contests', 'elections'):
        data = client.get('/api/v1/' + endpoint, params={'offset': 9999}).json()
        assert data['items'] == [] and data['total'] > 0
        assert data['availability'] == 'available' and not data['has_more']


@pytest.mark.integration
def test_only_active_publication_is_returned(client, populated, api_engine):
    # Republish identical inputs is a no-op, preserving result ordering and lineage.
    before = client.get('/api/v1/results').json()
    with Session(api_engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        replay = materialize_medsl_year(session, year=2008, dry_run=False, allow_partial=True)
        assert replay['action'] == 'UNCHANGED'
    assert client.get('/api/v1/results').json() == before
    with api_engine.begin() as connection:
        connection.execute(text('DELETE FROM canonical_publication'))
    assert client.get('/api/v1/results').json()['total'] == 0
    discovery = client.get('/api/v1/contests', params={'year': 2008}).json()
    assert discovery['total'] == 1 and discovery['items'][0]['publications'] == []


@pytest.mark.integration
def test_fusion_line_party_matches_whole_candidate_once(client, populated, api_engine):
    # A separate, unpublished batch can carry a vetted ballot-line representation.
    with Session(api_engine) as session, session.begin():
        batch = session.get(CanonicalResultBatch, populated['batch'])
        replacement = CanonicalResultBatch(scope_key=batch.scope_key, fingerprint='e' * 64,
            ruleset_version='fusion-fixture', source_release_id=batch.source_release_id,
            reference_release_id=batch.reference_release_id, election_year=2008, status='PARTIAL',
            input_rows=2, accepted_rows=2, excluded_rows=0, raw_votes_nonadditive=100, canonical_votes=100)
        session.add(replacement)
        session.flush()
        alice = session.scalar(select(Candidacy).where(Candidacy.source_label == 'ALICE'))
        party = PoliticalParty(name='Fusion partner')
        session.add(party)
        session.flush()
        seed = dict(release=session.get(SourceRelease, batch.source_release_id),
                    reference_release=session.get(SourceRelease, batch.reference_release_id),
                    county=session.get(Jurisdiction, populated['county']),
                    ref=session.get(GeographicReference, populated['reference']))
        for index, votes in enumerate((60, 40)):
            line = BallotLine(creation_key=f'fusion:{index}', candidacy_id=alice.id,
                              line_label=f'Party {index}', line_kind='party',
                              party_id=party.id if index else alice.party_id)
            session.add(line)
            session.flush()
            observation = _observe(session, seed, 1000 + index, name='ALICE', votes=votes, total=100)
            resolution = session.scalar(select(GeographicResolution).where(GeographicResolution.observation_id == observation.id))
            session.add(CanonicalVoteReturn(batch_id=replacement.id, observation_id=observation.id,
                contest_id=alice.contest_id, jurisdiction_id=populated['county'],
                geographic_resolution_id=resolution.id, candidacy_id=alice.id,
                ballot_line_id=line.id, source_label=line.line_label, reporting_level='county',
                reporting_mode='TOTAL', vote_kind='ballot_line', votes=votes))
        session.flush()
        session.get(CanonicalPublication, batch.scope_key).batch_id = replacement.id
        party_id = str(party.id)
    data = client.get('/api/v1/results', params={'party_id': party_id, 'limit': 1}).json()
    assert data['total'] == 1 and data['items'][0]['votes'] == 100
    assert len(data['items'][0]['observation_ids']) == 2
    assert data['items'][0]['basis'] == 'ballot_line'
    assert len(data['items'][0]['party_ids']) == 2


@pytest.mark.integration
def test_state_authority_is_separate_paginated_and_manifest_checked(client, api_engine, tmp_path):
    seed_comparison(api_engine, tmp_path)
    evidence = official_fixture(tmp_path / 'official')
    with Session(api_engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        publish(session, evidence, expected_fingerprint=plan(session, evidence)['fingerprint'],
                actor='test', archive_dir=tmp_path / 'archive')
    params = dict(year=2008, state_code='ny', stage='general', office='President of the United States')
    data = client.get('/api/v1/state-results', params=params).json()
    assert data['total'] == 3 and sum(r['votes'] for r in data['items']) == 183
    assert not data['additive_with_county_returns']
    assert all(r['publication']['source']['name'] == 'fec_presidential_official' for r in data['items'])
    assert next(r for r in data['items'] if r['candidate_bucket'] == 'OTHER')['bucket_kind'] == 'aggregate'
    assert client.get('/api/v1/state-results').json()['total'] == 153
    assert client.get('/api/v1/state-results', params={'year': 2004}).json()['total'] == 0
    assert client.get('/api/v1/state-results', params={'party_id': str(uuid4())}).status_code == 422
    county = client.get('/api/v1/results', params={'year': 2008}).json()
    assert sum(r['votes'] for r in county['items']) == 185
    # Published integrity is enforced by database triggers; corrupt the manifest
    # in a transaction-local reader stub to exercise the route's sanitized error.
    from app.services import election_queries
    original = election_queries.state_totals
    def invalid_manifest(*args, **kwargs):
        raise ValueError('secret database details')
    try:
        election_queries.state_totals = invalid_manifest
        response = client.get('/api/v1/state-results')
        assert response.status_code == 503 and 'secret' not in response.text
    finally:
        election_queries.state_totals = original


@pytest.mark.integration
@pytest.mark.parametrize('basis', ['candidate_total', 'ballot_line'])
def test_overlapping_candidate_representations_fail_closed(client, populated, api_engine, basis):
    with Session(api_engine) as session, session.begin():
        batch = session.get(CanonicalResultBatch, populated['batch'])
        candidate = session.scalar(select(Candidacy).where(Candidacy.source_label == 'ALICE'))
        seed = dict(release=session.get(SourceRelease, batch.source_release_id),
                    reference_release=session.get(SourceRelease, batch.reference_release_id),
                    county=session.get(Jurisdiction, populated['county']),
                    ref=session.get(GeographicReference, populated['reference']))
        observation = _observe(session, seed, 999, name='ALICE', votes=100, total=100)
        resolution = session.scalar(select(GeographicResolution).where(GeographicResolution.observation_id == observation.id))
        line_id = None
        if basis == 'ballot_line':
            line = BallotLine(creation_key='overlap', candidacy_id=candidate.id, line_label='Overlap', line_kind='party')
            session.add(line)
            session.flush()
            line_id = line.id
        session.add(CanonicalVoteReturn(batch_id=batch.id, observation_id=observation.id,
            contest_id=candidate.contest_id, jurisdiction_id=populated['county'],
            geographic_resolution_id=resolution.id, candidacy_id=candidate.id,
            ballot_line_id=line_id, source_label='ALICE', reporting_level='county',
            reporting_mode='TOTAL', vote_kind=basis, votes=100))
    response = client.get('/api/v1/results')
    assert response.status_code == 503
    assert response.json() == {'detail': 'Published results failed integrity validation'}


@pytest.mark.integration
def test_correction_publication_is_visible_with_source_lineage(client, api_engine, tmp_path):
    from test_county_corrections import fixture_review, apply
    from app.services.county_corrections import prepare
    review = fixture_review(api_engine, tmp_path)
    before = client.get('/api/v1/results').json()
    with Session(api_engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        applied = apply(session, review, tmp_path, prepare(session, review)['fingerprint'])
    data = client.get('/api/v1/results').json()
    assert sum(r['votes'] for r in before['items']) == 185
    assert sum(r['votes'] for r in data['items']) == 186
    assert {r['publication']['batch_id'] for r in data['items']} == {applied['batch_id']}
    corrected = next(r for r in data['items'] if r['correction_ids'])
    assert corrected['votes'] == 101
    assert corrected['publication']['correction_batch_id']
    assert corrected['publication']['correction_source']['sha256']
    assert corrected['publication']['status'] == 'PARTIAL'


@pytest.mark.integration
def test_other_offices_stages_years_and_district_grains_are_generic(client, api_engine):
    # Synthetic canonical adapter output: no claim that a House ingestion exists.
    with Session(api_engine) as session, session.begin():
        seed = _seed(session, year=2024)
        seed['source'].name = 'synthetic_house_returns'
        seed['county'].level = 'congressional_district'
        seed['ref'].kind = 'congressional_district'
        seed['ref'].geoid = '3601'
        office = elections.office(session, creation_key='house-office', name='U.S. House', office_kind='legislative')
        party = PoliticalParty(name='District party')
        session.add(party)
        session.flush()
        batch = CanonicalResultBatch(scope_key='synthetic:house:2024:TOTAL', fingerprint='b' * 64,
            ruleset_version='synthetic', source_release_id=seed['release'].id,
            reference_release_id=seed['reference_release'].id, election_year=2024, status='COMPLETE',
            input_rows=3, accepted_rows=3, excluded_rows=0, raw_votes_nonadditive=90, canonical_votes=90)
        session.add(batch)
        session.flush()
        for n, (stage, votes) in enumerate([('primary', 25), ('runoff', 30), ('special', 35)], 2):
            event = elections.election(session, creation_key=f'district-{stage}', election_date=date(2024, n, 1),
                election_type=stage, jurisdiction_id=seed['county'].id, election_cycle=2026)
            contest = elections.contest(session, creation_key=f'district-contest-{stage}', office_name='U.S. House',
                office_id=office.id, election_id=event.id, jurisdiction_id=seed['county'].id)
            candidate = elections.candidacy(session, creation_key=f'district-candidate-{stage}',
                contest_id=contest.id, source_label='District candidate', party_id=party.id)
            observation = _observe(session, seed, n, name='District candidate', votes=votes, total=votes)
            observation.year = 2024
            observation.office_raw = 'US HOUSE'
            resolution = session.scalar(select(GeographicResolution).where(GeographicResolution.observation_id == observation.id))
            session.add(CanonicalVoteReturn(batch_id=batch.id, observation_id=observation.id, contest_id=contest.id,
                jurisdiction_id=seed['county'].id, geographic_resolution_id=resolution.id, candidacy_id=candidate.id,
                source_label='District candidate', reporting_level='congressional_district', reporting_mode='TOTAL',
                vote_kind='candidate_total', votes=votes))
        session.flush()
        session.add(CanonicalPublication(scope_key=batch.scope_key, batch_id=batch.id))
        party_id, jurisdiction_id = str(party.id), str(seed['county'].id)
    for stage, votes in [('primary', 25), ('runoff', 30), ('special', 35)]:
        params = dict(year=2024, office='u.s. house', stage=stage, party_id=party_id,
                      state_code='ny', jurisdiction_id=jurisdiction_id)
        for endpoint in ('elections', 'contests', 'results'):
            selected = dict(params)
            if endpoint == 'results':
                selected['reporting_level'] = 'congressional_district'
            response = client.get('/api/v1/' + endpoint, params=selected)
            assert response.status_code == 200, response.text
            assert response.json()['total'] == 1
            if endpoint == 'results':
                assert response.json()['items'][0]['votes'] == votes
        assert client.get('/api/v1/results', params={'year': 2026, 'reporting_level': 'congressional_district'}).json()['total'] == 0
