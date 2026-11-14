"""Read-only DATA-004 inventory, preservation fingerprints and exception export.

Run: python -m app.services.data004_audit --output /app/data/data004/before.json
Fingerprints select columns by name so adding nullable columns does not conceal
changes to the original records. Reuse --baseline after migration.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import polars as pl
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import engine

TABLES = (
    'source_release', 'source_active_year', 'election_result_observation',
    'jurisdiction', 'jurisdiction_identifier', 'jurisdiction_relationship',
    'geographic_reference', 'geographic_resolution', 'geographic_alias',
    'geographic_change', 'geographic_identity_link', 'geographic_reporting_unit',
    'jurisdiction_boundary_vintage', 'geographic_resolution_context',
    'person', 'person_name', 'organization', 'external_identifier',
    'identity_assignment_event', 'committee_relationship',
    'election', 'contest', 'candidacy', 'political_party', 'office', 'office_term',
    'ballot_line', 'canonical_result_batch', 'canonical_publication',
    'canonical_vote_return', 'canonical_materialization_issue',
)


def audit(baseline: dict | None = None) -> dict:
    with engine.connect() as conn, conn.begin():
        conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        inspector = inspect(conn)
        quote = conn.dialect.identifier_preparer.quote
        result = {'generated_at': datetime.now(timezone.utc).isoformat(),
                  'postgresql': conn.scalar(text('SELECT version()')),
                  'alembic_revision': conn.scalar(text('SELECT version_num FROM alembic_version')),
                  'extensions': [dict(x) for x in conn.execute(text(
                      'SELECT extname, extversion FROM pg_extension ORDER BY extname')).mappings()],
                  'fingerprints': {}, 'schema': {}}
        for table in TABLES:
            if not inspector.has_table(table):
                continue
            cols = [c['name'] for c in inspector.get_columns(table)]
            original = baseline['fingerprints'].get(table) if baseline else None
            selected = original['columns'] if original else cols
            projection = ', '.join(quote(c) for c in selected)
            # Hash every original column, with row ordering independent of plans.
            row = conn.execute(text(f"""SELECT count(*) AS rows,
                md5(coalesce(string_agg(row_hash, '' ORDER BY row_hash), '')) AS md5
                FROM (SELECT md5(row_to_json(r)::text) AS row_hash
                      FROM (SELECT {projection} FROM {quote(table)}) r) h""")).mappings().one()
            result['fingerprints'][table] = {**dict(row), 'columns': selected}
            result['schema'][table] = {'columns': cols,
                'checks': inspector.get_check_constraints(table),
                'unique': inspector.get_unique_constraints(table),
                'foreign_keys': inspector.get_foreign_keys(table)}
        result['resolution_counts'] = [dict(x) for x in conn.execute(text('''
            SELECT status, ruleset_version, count(*) AS observations
            FROM geographic_resolution GROUP BY 1,2 ORDER BY 1,2''')).mappings()]
        result['reference_releases'] = [dict(x) for x in conn.execute(text('''
            SELECT s.name AS source, r.id, r.version, r.sha256, r.metadata_json,
                   g.kind, count(*) AS records
            FROM geographic_reference g JOIN source_release r ON r.id=g.release_id
            JOIN data_source s ON s.id=r.source_id
            GROUP BY s.name,r.id,g.kind ORDER BY s.name,r.version,g.kind''')).mappings()]
        result['canonical_publications'] = [dict(x) for x in conn.execute(text('''
            SELECT b.election_year,b.id,b.fingerprint,b.accepted_rows,b.excluded_rows,
                   b.canonical_votes,p.published_at
            FROM canonical_publication p JOIN canonical_result_batch b ON b.id=p.batch_id
            ORDER BY b.election_year''')).mappings()]
        result['exceptions'] = [dict(x) for x in conn.execute(text('''
            SELECT o.id AS observation_id, o.release_id AS observation_release_id,
                   o.source_row_number, o.row_sha256, o.year, o.state_code,
                   o.county_raw, o.county_fips_raw, o.county_fips,
                   g.id AS resolution_id, g.reference_release_id, g.status,
                   g.method, g.reason, g.evidence_json, g.ruleset_version,
                   o.candidate_votes, o.total_votes
            FROM geographic_resolution g
            JOIN election_result_observation o ON o.id=g.observation_id
            WHERE g.status NOT IN ('RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS',
                                    'NON_COUNTY_CLASSIFIED')
              AND NOT EXISTS (SELECT 1 FROM geographic_resolution child
                              WHERE child.supersedes_id=g.id)
            ORDER BY o.year,o.state_code,o.county_raw,o.source_row_number
            ''')).mappings()]
        result['integrity'] = {}
        queries = {
            'identifier_identity_mismatches': '''SELECT count(*) FROM jurisdiction_identifier i
                JOIN geographic_reference r ON r.id=i.reference_id
                WHERE i.jurisdiction_id<>r.jurisdiction_id''',
            'relationship_child_mismatches': '''SELECT count(*) FROM jurisdiction_relationship j
                JOIN geographic_reference r ON r.id=j.reference_id
                WHERE j.child_id<>r.jurisdiction_id OR j.child_id=j.parent_id''',
            'dated_identifiers': 'SELECT count(*) FROM jurisdiction_identifier WHERE valid_from IS NOT NULL OR valid_until IS NOT NULL',
            'resolution_identity_mismatches': '''SELECT count(*) FROM geographic_resolution g
                JOIN geographic_reference r ON r.id=g.reference_id
                WHERE g.jurisdiction_id IS NOT NULL AND g.jurisdiction_id<>r.jurisdiction_id''',
            'cross_release_resolution_evidence': '''SELECT count(*) FROM geographic_resolution g
                JOIN geographic_reference r ON r.id=g.reference_id
                WHERE g.reference_release_id<>r.release_id''',
        }
        for key, sql in queries.items():
            result['integrity'][key] = conn.scalar(text(sql))
        if baseline:
            result['preservation'] = {t: result['fingerprints'].get(t) == f
                for t, f in baseline['fingerprints'].items()}
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--canonical-replay', action='store_true', help='Recompute published DATA-003 fingerprints without writes')
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding='utf-8')) if args.baseline else None
    result = audit(baseline)
    if args.canonical_replay:
        from app.services.canonical_results import materialize_medsl_year
        result['canonical_replay'] = []
        for published in result['canonical_publications']:
            with Session(engine) as session, session.begin():
                session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
                preview = materialize_medsl_year(session, year=published['election_year'])
            matches = (preview['fingerprint'] == published['fingerprint']
                and preview['accepted_rows'] == published['accepted_rows']
                and preview['excluded_rows'] == published['excluded_rows']
                and preview['eligible_canonical_votes'] == published['canonical_votes'])
            result['canonical_replay'].append({**preview, 'matches_publication':matches})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + '\n', encoding='utf-8')
    rows = [{**r, 'evidence_json': json.dumps(r['evidence_json'], default=str)}
            for r in json.loads(json.dumps(result['exceptions'], default=str))]
    if rows:
        frame = pl.DataFrame(rows, infer_schema_length=None)
        frame.write_csv(args.output.with_suffix('.exceptions.csv'))
        groups = frame.group_by(['year', 'state_code', 'county_raw', 'county_fips',
                                 'status', 'method', 'reason']).agg(
            pl.len().alias('observations'),
            pl.col('candidate_votes').sum().alias('raw_candidate_votes_not_reconciled'))
        groups.sort(['year', 'state_code', 'county_raw']).write_csv(
            args.output.with_suffix('.groups.csv'))
    print(json.dumps({k: result[k] for k in ('alembic_revision','resolution_counts',
                                            'integrity','preservation') if k in result}, indent=2))
    if baseline and not all(result['preservation'].values()):
        raise SystemExit('Preservation check failed')
    if not all(r['matches_publication'] for r in result.get('canonical_replay', [])):
        raise SystemExit('Canonical replay check failed')


if __name__ == '__main__':
    main()
