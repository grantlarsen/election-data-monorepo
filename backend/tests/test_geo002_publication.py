"""Selective approval, stale heads, rollback and immutable canonical pointers on PostgreSQL."""
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, inspect, select, text
from sqlalchemy.orm import Session

from test_data004_postgres import pg, medsl_fixture, fingerprint
from app.models.geography import GeographicReference, GeographicResolution as R
from app.models.ingestion import ElectionResultObservation as O
from app.services.canonical_results import materialize_medsl_year
from ingestion.geography import context, selection
from ingestion.geography.resolve import resolve_medsl
from ingestion.geography.resolution_v2 import current_resolution_rows

pytestmark = pytest.mark.integration


def setup(pg, *, reassigned=False):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from test_data004_postgres import migration
    with pg.begin() as c,Operations.context(MigrationContext.configure(c)):
        migration('d005fec2008a_authoritative_state_results.py').upgrade()
        migration('d005county01_reviewed_county_corrections.py').upgrade()
    medsl_fixture(pg)
    with Session(pg) as s, s.begin():
        obs = list(s.scalars(select(O).order_by(O.source_row_number)))
        refs = {r.geoid: r for r in s.scalars(select(GeographicReference).where(GeographicReference.kind == 'county'))}
        obs[0].county_raw = 'WRONG LABEL'  # Matched legacy head must be downgraded separately.
        for n, label in [(1, 'DISTRICT 1'), (2, 'DISTRICT 99')]:
            obs[n].state_code = 'AK'
            obs[n].state_fips = '02'
            obs[n].county_raw = label
            obs[n].county_fips_raw = '2001' if n == 1 else '2099'
            obs[n].county_fips = '02001' if n == 1 else '02099'
        s.flush()
        for n, o in enumerate(obs):
            ref = refs.get(o.county_fips)
            if reassigned and n == 3:
                ref = refs['01001']  # Synthetic wrong legacy county, requiring explicit reassignment.
            s.add(R(observation_id=o.id, reference_release_id=next(iter(refs.values())).release_id,
                reference_id=ref.id if ref else None, jurisdiction_id=ref.jurisdiction_id if ref else None,
                status='RESOLVED' if ref else 'UNRESOLVED', method='LEGACY_FIXTURE',
                reason='Synthetic legacy decision', evidence_json={}, ruleset_version='step6-v1'))
        ids = [o.id for o in obs]
    preview, _ = resolve_medsl(pg, vintage=2000, publish=False)
    with Session(pg) as s, s.begin():
        s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        materialize_medsl_year(s, year=2000, dry_run=False, allow_partial=True)
    return preview, ids


def selected(pg, preview, ids):
    from ingestion.geography.resolve import assess_observation
    indexes = context.indexes(preview['context_manifest'], *preview['product_years'])
    by_code, latest, legacy, newer, supplements, aliases, changes = indexes
    release = UUID(preview['reference_release_id'])
    targets = []
    with pg.connect() as c:
        heads = current_resolution_rows(c, release)
        for row in c.execute(select(O.__table__).where(O.id.in_(ids))).mappings():
            decision = assess_observation(dict(row), by_code, {}, latest, release, *preview['product_years'],
                aliases=aliases, legacy_by_code=legacy, verified_changes=changes,
                cross_release_by_code=newer, supplemental_2000_by_code=supplements)
            targets.append(selection.target(row['id'], heads.get(row['id']), decision))
    return selection.manifest(release, preview['ruleset_version'], preview['context_sha256'], targets)


def call(pg, preview, manifest, **kwargs):
    return resolve_medsl(pg, vintage=2000, context_manifest=preview['context_manifest'],
        publication_manifest=manifest, **kwargs)[0]


def approved(pg, preview, manifest, **kwargs):
    return call(pg, preview, manifest, actor='geo002-test-reviewer', approve_changes=True,
        expected_proposal_sha256=context.digest(manifest), **kwargs)


def snapshot(pg):
    with pg.connect() as c:
        i = inspect(c)
        return fingerprint(c, {t: [x['name'] for x in i.get_columns(t)] for t in i.get_table_names()})


def test_exact_subset_audit_replay_and_canonical_preservation(pg):
    preview, ids = setup(pg)
    m = selected(pg, preview, [ids[1], ids[3]])
    before = snapshot(pg)
    read = call(pg, preview, m, publish=False)
    assert read['publication_target_count'] == 2 and snapshot(pg) == before
    made = approved(pg, preview, m)
    assert made['records_inserted'] == 2 and made['unselected_difference_count'] == 4
    assert made['publication_downgrades'] == made['publication_reassignments'] == 0
    after = snapshot(pg)
    assert {k for k in before if before[k] != after[k]} == {
        'geographic_resolution', 'geographic_reporting_unit', 'geographic_resolution_context'}
    with pg.connect() as c:
        heads = current_resolution_rows(c, UUID(preview['reference_release_id']))
        for oid in [ids[1], ids[3]]:
            assert heads[oid]['published_by'] == 'geo002-test-reviewer'
            assert heads[oid]['context_sha256'] == preview['context_sha256']
            assert heads[oid]['evidence_json']['publication_audit']['publication_sha256'] == context.digest(m)
        for oid in [ids[0], ids[2], ids[4], ids[5]]:
            assert heads[oid]['ruleset_version'] == 'step6-v1'
        assert c.scalar(text('SELECT count(*) FROM geographic_reporting_unit')) == 1
    replay = approved(pg, preview, m)
    assert replay['records_inserted'] == 0 and replay['publication_replayed_count'] == 2
    assert replay['publication_sha256'] == made['publication_sha256'] and snapshot(pg) == after
    with pytest.raises(ValueError, match='Stale or changed'):
        call(pg, preview, m, actor='different-actor', approve_changes=True,
            expected_proposal_sha256=context.digest(m))
    assert snapshot(pg) == after


def test_gate_rejects_before_any_mutation(pg):
    preview, ids = setup(pg)
    m = selected(pg, preview, [ids[1]])
    before = snapshot(pg)
    mutations = []
    def capture(conn, cursor, statement, params, ctx, many):
        if statement.lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
            mutations.append(statement)
    event.listen(pg, 'before_cursor_execute', capture)
    try:
        for kwargs, message in [({}, '--actor'),
                ({'actor': 'reviewer'}, 'approve-changes'),
                ({'actor': 'reviewer', 'approve_changes': True}, 'expected-proposal'),
                ({'actor': 'reviewer', 'approve_changes': True,
                  'expected_proposal_sha256': preview['proposal_sha256']}, 'expected-proposal')]:
            with pytest.raises(ValueError, match=message):
                call(pg, preview, m, **kwargs)
        for field in ['reason', 'reference_id', 'method', 'evidence_json']:
            bad = deepcopy(m)
            bad['targets'][0]['decision'][field] = {} if field == 'evidence_json' else 'changed'
            with pytest.raises(ValueError, match='Stale or changed'):
                approved(pg, preview, bad)
        for field in ['context_sha256', 'reference_release_id', 'ruleset_version']:
            bad = deepcopy(m); bad[field] = 'changed'
            with pytest.raises(ValueError, match='manifest'):
                approved(pg, preview, bad)
        bad = deepcopy(m); bad['targets'].append(deepcopy(bad['targets'][0]))
        with pytest.raises(ValueError, match='Duplicate'):
            approved(pg, preview, bad)
        bad = deepcopy(m); bad['targets'][0]['observation_id'] = str(uuid4())
        with pytest.raises(ValueError, match='outside the frozen scope'):
            approved(pg, preview, bad)
    finally:
        event.remove(pg, 'before_cursor_execute', capture)
    assert not mutations and snapshot(pg) == before


def test_downgrade_separate_authorization_and_later_head_rejection(pg):
    preview, ids = setup(pg)
    m = selected(pg, preview, [ids[0]])
    before = snapshot(pg)
    with pytest.raises(ValueError, match='allow-downgrades'):
        approved(pg, preview, m)
    assert snapshot(pg) == before
    made = approved(pg, preview, m, allow_downgrades=True)
    assert made['records_inserted'] == 1 and made['publication_downgrades'] == 1
    with pytest.raises(ValueError, match='allow-downgrades'):
        approved(pg, preview, m)
    with pg.begin() as c:
        head = dict(c.execute(select(R.__table__).where(R.supersedes_id.is_not(None))).mappings().one())
        c.execute(R.__table__.insert().values({**head, 'id': uuid4(), 'supersedes_id': head['id']}))
    with pytest.raises(ValueError, match='Stale or changed'):
        approved(pg, preview, m, allow_downgrades=True)


def test_insert_failure_rolls_back_decisions_reporting_units_and_context(pg):
    preview, ids = setup(pg)
    m = selected(pg, preview, [ids[1], ids[3]])
    before = snapshot(pg)
    reached_insert = []
    def fail(conn, cursor, statement, params, ctx, many):
        if statement.startswith('INSERT INTO geographic_resolution '):
            reached_insert.append(True)
            raise RuntimeError('injected late decision insert failure')
    event.listen(pg, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='injected late'):
            approved(pg, preview, m)
    finally:
        event.remove(pg, 'before_cursor_execute', fail)
    assert reached_insert and snapshot(pg) == before


def test_selected_new_decisions_also_require_exact_approval(pg):
    medsl_fixture(pg)
    preview, _ = resolve_medsl(pg, vintage=2000, publish=False)
    with pg.connect() as c:
        oid = c.scalar(select(O.id).limit(1))
    m = selected(pg, preview, [oid])
    before = snapshot(pg)
    with pytest.raises(ValueError, match='approve-changes'):
        call(pg, preview, m, actor='reviewer')
    assert snapshot(pg) == before
    made = approved(pg, preview, m)
    assert made['records_inserted'] == 1 and made['publication_target_count'] == 1
    assert approved(pg, preview, m)['records_inserted'] == 0


def test_jurisdiction_reassignment_requires_separate_flag(pg):
    preview, ids = setup(pg, reassigned=True)
    m = selected(pg, preview, [ids[3]])
    before = snapshot(pg)
    with pytest.raises(ValueError, match='allow-jurisdiction-reassignment'):
        approved(pg, preview, m)
    assert snapshot(pg) == before
    made = approved(pg, preview, m, allow_jurisdiction_reassignment=True)
    assert made['records_inserted'] == 1 and made['publication_reassignments'] == 1


def test_changed_observation_input_rejected_before_publication(pg):
    preview, ids = setup(pg)
    m = selected(pg, preview, [ids[1]])
    with pg.begin() as c:
        c.execute(O.__table__.update().where(O.id == ids[1]).values(county_raw='DISTRICT 2'))
    before = snapshot(pg)
    with pytest.raises(ValueError, match='observation inputs changed'):
        approved(pg, preview, m)
    assert snapshot(pg) == before


def test_manifest_envelope_rejects_corrupt_payload(tmp_path):
    path = tmp_path / 'subset.json'
    m = {'targets': [{'decision': 'original'}]}
    path.write_text(__import__('json').dumps({'manifest': m, 'publication_sha256': context.digest(m)}))
    assert selection.read(path) == m
    path.write_text(__import__('json').dumps({'manifest': {'targets': []}, 'publication_sha256': context.digest(m)}))
    with pytest.raises(ValueError, match='corrupt publication'):
        selection.read(path)
