"""Independent, read-only GEO-001 inventory and observation-level verification.

Run in the API container; all outputs are separate from DATA-004 evidence.
The independent checks below do not call resolver matching/normalization helpers.
Resolver calls are used only to reproduce the proposals being audited.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
from uuid import UUID
from zipfile import ZipFile

import polars as pl
from sqlalchemy import event, inspect, select, text

from app.database import engine
from app.models.ingestion import ElectionResultObservation as O
from ingestion.geography.resolve import assess_observation, resolve_medsl
from ingestion.geography import context

ROOT = Path('/app/data/geo001')
OLD = Path('/app/data/data004')
VINTAGES = (2000, 2004, 2012, 2020, 2024)
MATCHED = {'RESOLVED', 'RESOLVED_HISTORICAL', 'RESOLVED_ALIAS'}


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False) + '\n', encoding='utf-8')


def stable_sha(obj):
    return sha256(json.dumps(obj, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def file_sha(path):
    h = sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def evidence_files():
    return {str(p.relative_to(OLD)): file_sha(p) for p in sorted(OLD.rglob('*')) if p.is_file()}


def all_fingerprints(conn):
    """All public tables, every current column; SHA-256 of sorted row digests."""
    i = inspect(conn)
    quote = conn.dialect.identifier_preparer.quote
    result = {}
    for table in i.get_table_names(schema='public'):
        rows = conn.execute(text(f'SELECT row_to_json(r)::text FROM public.{quote(table)} r'))
        hashes = sorted(sha256(row[0].encode()).hexdigest() for row in rows)
        result[table] = {'rows': len(hashes), 'sha256': sha256(''.join(hashes).encode()).hexdigest(),
                         'columns': [c['name'] for c in i.get_columns(table, schema='public')]}
    return result


def inventory(output, phase):
    with engine.connect() as conn, conn.begin():
        conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        result = {'generated_at': datetime.now(timezone.utc).isoformat(),
                  'transaction_read_only': conn.scalar(text('SHOW transaction_read_only')),
                  'transaction_isolation': conn.scalar(text('SHOW transaction_isolation')),
                  'database': conn.scalar(text('SELECT current_database()')),
                  'fingerprints': all_fingerprints(conn)}
        queries = {
            'source_releases': '''SELECT s.name AS source,r.* FROM source_release r
                JOIN data_source s ON s.id=r.source_id ORDER BY s.name,r.version''',
            'active_years': '''SELECT s.name AS source,a.*,r.version,r.sha256 FROM source_active_year a
                JOIN data_source s ON s.id=a.source_id JOIN source_release r ON r.id=a.release_id
                ORDER BY s.name,a.year''',
            'chain_counts': '''SELECT count(*) AS decisions,count(*) FILTER(WHERE supersedes_id IS NULL) AS roots,
                count(*) FILTER(WHERE NOT EXISTS(SELECT 1 FROM geographic_resolution c WHERE c.supersedes_id=g.id)) AS heads
                FROM geographic_resolution g''',
            'duplicate_heads': '''SELECT observation_id,reference_release_id,count(*) FROM geographic_resolution g
                WHERE NOT EXISTS(SELECT 1 FROM geographic_resolution c WHERE c.supersedes_id=g.id)
                GROUP BY 1,2 HAVING count(*)<>1''',
            'observation_chain_coverage': '''SELECT count(*) AS observations,
                count(*) FILTER(WHERE n=1) AS exactly_one_head,
                count(*) FILTER(WHERE n<>1) AS bad FROM (SELECT o.id,count(g.id) AS n
                FROM election_result_observation o LEFT JOIN geographic_resolution g ON g.observation_id=o.id
                AND NOT EXISTS(SELECT 1 FROM geographic_resolution c WHERE c.supersedes_id=g.id)
                GROUP BY o.id) q''',
            'triggers': '''SELECT event_object_table,trigger_name,event_manipulation,action_statement
                FROM information_schema.triggers WHERE trigger_schema='public'
                ORDER BY 1,2,3''',
            'indexes': "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2",
            'bedford_source': '''SELECT o.id,o.release_id,o.source_row_number,o.row_sha256,o.year,o.county_raw,
                o.county_fips_raw,o.candidate_raw,o.candidate_votes,o.total_votes,o.raw_json,
                g.id AS resolution_id,g.status,g.reference_id,g.jurisdiction_id,
                c.batch_id,c.votes,c.geographic_resolution_id FROM election_result_observation o
                JOIN geographic_resolution g ON g.observation_id=o.id
                LEFT JOIN canonical_vote_return c ON c.observation_id=o.id
                WHERE o.county_fips='51515' ORDER BY o.year,o.source_row_number''',
            'retired_2012_vintage': '''SELECT o.year,o.state_code,o.county_raw,o.county_fips,g.status,g.method,
                count(*) AS observations,sum(o.candidate_votes) AS raw_votes FROM election_result_observation o
                JOIN geographic_resolution g ON g.observation_id=o.id
                WHERE o.year IN (2012,2016) AND o.county_fips IN ('51515','46113','46102')
                GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,4''',
            'nm_identities': '''SELECT g.*,j.name AS jurisdiction_name FROM geographic_reference g
                JOIN jurisdiction j ON j.id=g.jurisdiction_id WHERE g.geoid='35013'
                ORDER BY g.vintage_start,g.release_id''',
            'review_tables': '''SELECT 'aliases' AS kind,status,count(*) AS records FROM geographic_alias GROUP BY status
                UNION ALL SELECT 'changes',status,count(*) FROM geographic_change GROUP BY status
                UNION ALL SELECT 'identity_links','RECORDED',count(*) FROM geographic_identity_link''',
            'canonical_publications': '''SELECT b.*,p.published_at FROM canonical_result_batch b
                JOIN canonical_publication p ON p.batch_id=b.id ORDER BY b.election_year''',
        }
        for key, query in queries.items():
            result[key] = [dict(r) for r in conn.execute(text(query)).mappings()]
        result['observation_raw_hash_errors'] = []
        for row in conn.execute(text('SELECT id,row_sha256,raw_json FROM election_result_observation')).mappings():
            h = sha256(json.dumps(row['raw_json'], sort_keys=True, ensure_ascii=False,
                                  separators=(',', ':'), default=str).encode()).hexdigest()
            if h != row['row_sha256']:
                result['observation_raw_hash_errors'].append(str(row['id']))
        result['data004_file_sha256'] = evidence_files()
    dump(output / f'full-{phase}.json', result)
    print(json.dumps({'phase': phase, 'public_tables': len(result['fingerprints']),
                      'chains': result['chain_counts'], 'coverage': result['observation_chain_coverage'],
                      'raw_hash_errors': len(result['observation_raw_hash_errors'])}))
    if phase == 'after':
        before = json.loads((output / 'full-before.json').read_text(encoding='utf-8'))
        checks = {t: f == result['fingerprints'].get(t) for t, f in before['fingerprints'].items()}
        dump(output / 'full-preservation.json', {'tables': checks, 'all_tables_unchanged': all(checks.values()),
             'same_table_set': set(before['fingerprints']) == set(result['fingerprints']),
             'data004_files_unchanged': before['data004_file_sha256'] == result['data004_file_sha256']})
        assert all(checks.values()) and before['data004_file_sha256'] == result['data004_file_sha256']


def independent_tokens(value):
    """Independent typed comparison, not the resolver's name_key function."""
    value = unicodedata.normalize('NFKD', (value or '').split(',')[0]).casefold()
    value = ''.join(c for c in value if not unicodedata.combining(c))
    tokens = re.findall('[a-z0-9]+', value)
    if tokens and tokens[-1] in {'county', 'parish', 'borough', 'municipality'}:
        tokens.pop()
    if tokens[-2:] == ['census', 'area']:
        tokens = tokens[:-2]
    return tokens


def independent_match(obs, ref):
    if ref is None:
        return 'matched_without_reference'
    if obs['county_fips'] != ref['geoid'] or obs['state_fips'] != ref['state_fips']:
        return 'code_or_state_mismatch'
    if obs['state_code'] == 'VA' and obs['county_fips'] == '51515' and obs['year'] > 2013:
        return 'retired_bedford'
    if obs['state_code'] == 'SD' and obs['county_fips'] == '46113' and obs['year'] > 2015:
        return 'retired_shannon'
    if obs['state_code'] == 'AK' and re.fullmatch(r'DISTRICT\s+\d+', obs['county_raw'] or ''):
        return 'alaska_reporting_district_is_not_county'
    a, b = independent_tokens(obs['county_raw']), independent_tokens(ref['name_raw'])
    if a == b and a:
        return None
    city = ((obs['state_code'] == 'VA' and int(ref['geoid'][2:]) >= 500)
            or ref['geoid'] in {'24510', '29510', '32510'})
    if city and b[-1:] == ['city'] and a == b[:-1] and a:
        return None
    return 'independent_name_or_entity_type_conflict'


def sources(output):
    inventory_data = json.loads((output / 'full-before.json').read_text(encoding='utf-8'))
    releases = inventory_data['source_releases']
    result = []
    raw_refs = {}
    for r in releases:
        path = Path(r['raw_path'])
        if not path.is_absolute():
            path = Path('/app') / path
        item = {**r, 'archive_present': path.is_file()}
        if path.is_file():
            item['actual_sha256'] = file_sha(path)
            item['checksum_matches'] = item['actual_sha256'] == r['sha256']
            if r['source'] == 'census_state_county_georef':
                data = path.read_bytes()
                try:
                    data.decode('utf-8')
                    item['strict_utf8_valid'] = True
                except UnicodeDecodeError as exc:
                    item['strict_utf8_valid'] = False
                    item['first_utf8_error'] = str(exc)
                # Decode only for comparison with immutable loaded labels. No repair.
                rows = list(csv.DictReader(data.decode('utf-8', errors='replace').splitlines()))
                name_field = 'ctyname' if 'ctyname' in rows[0] else 'county_name'
                sf = 'fipstate' if 'fipstate' in rows[0] else 'st'
                cf = 'fipscty' if 'fipscty' in rows[0] else 'cty'
                raw_refs[r['id']] = {x[sf].strip().zfill(2) + x[cf].strip().zfill(3): x[name_field].strip() for x in rows}
                item['dona_ana_source_records'] = [
                    {'line_number': n, 'hex': data.splitlines()[n-1].hex(),
                     'utf8_lossy': data.splitlines()[n-1].decode('utf-8', errors='replace'),
                     'cp1252': data.splitlines()[n-1].decode('cp1252', errors='replace')}
                    for n, x in enumerate(rows, 2)
                    if x[sf].strip().zfill(2) + x[cf].strip().zfill(3) == '35013']
            elif r['source'] == 'census_2000_counties_gazetteer':
                with ZipFile(path) as z:
                    member = [n for n in z.namelist() if not n.endswith('/')][0]
                    body = z.read(member)
                item['member'] = member
                item['member_sha256'] = sha256(body).hexdigest()
                raw_refs[r['id']] = {s[2:7]: s[7:71].strip() for s in body.decode('latin-1').splitlines() if s.strip()}
                item['dc_miami_dade_records'] = [s for s in body.decode('latin-1').splitlines() if s[2:7] in {'11001','12086'}]
        result.append(item)
    with engine.connect() as conn, conn.begin():
        conn.execute(text('SET TRANSACTION READ ONLY'))
        errors = []
        count = 0
        for ref in conn.execute(text("SELECT * FROM geographic_reference WHERE kind='county'")).mappings():
            count += 1
            raw = raw_refs.get(str(ref['release_id']), {}).get(ref['geoid'])
            if raw != ref['name_raw']:
                errors.append({'reference_id': ref['id'], 'geoid': ref['geoid'], 'archived_name': raw, 'loaded_name': ref['name_raw']})
        medsl = next(r for r in releases if r['source'] == 'medsl_presidential_county')
        path = Path(medsl['raw_path'])
        path = path if path.is_absolute() else Path('/app') / path
        archived_hashes = {}
        for n, row in enumerate(pl.read_csv(path, infer_schema_length=0).iter_rows(named=True), 2):
            archived_hashes[n] = sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                                 separators=(',', ':'), default=str).encode()).hexdigest()
        raw_row_errors = []
        raw_row_count = 0
        for row in conn.execute(text('SELECT id,release_id,source_row_number,row_sha256 FROM election_result_observation')).mappings():
            raw_row_count += 1
            if str(row['release_id']) != medsl['id'] or archived_hashes.get(row['source_row_number']) != row['row_sha256']:
                raw_row_errors.append(str(row['id']))
    dump(output / 'source-integrity.json', {'releases': result, 'county_records_checked': count,
         'released_label_mismatches': errors, 'medsl_archived_rows': len(archived_hashes),
         'observation_rows_checked_against_archive': raw_row_count, 'archived_observation_row_errors': raw_row_errors})
    assert all(r.get('checksum_matches') for r in result), 'Missing or corrupt source archive'
    assert not errors, 'Released labels differ from archived source records'
    assert not raw_row_errors, 'Observations differ from archived CSV rows'
    print(json.dumps({'source_checksums_verified': len(result), 'county_records_verified': count}))


def verify(output, archive_dir):
    reports = []
    validation = []
    outcomes = []
    sql_log = []

    def capture_sql(conn, cursor, statement, parameters, execution_context, executemany):
        sql_log.append(statement)
        if not re.match(r'^\s*(SELECT|SET|SHOW|WITH)\b', statement, re.I):
            raise AssertionError('Unexpected statement during preview: ' + statement[:80])
    event.listen(engine, 'before_cursor_execute', capture_sql)
    try:
        for vintage in VINTAGES:
            saved = json.loads((archive_dir / f'compare-{vintage}.json').read_text(encoding='utf-8'))
            fresh = json.loads((output / 'reproduced' / f'compare-{vintage}.json').read_text(encoding='utf-8'))
            manifest = saved['context_manifest']
            assert stable_sha(manifest) == saved['context_sha256']
            replay, _ = resolve_medsl(engine, vintage=vintage, publish=False, context_manifest=manifest)
            reports.append(fresh)
            check = {'vintage': vintage, 'saved_equals_fresh': saved == fresh,
                     'archive_context_digest_valid': True,
                     'archived_replay_equals_fresh': replay == fresh,
                     'context_sha256': fresh['context_sha256'], 'proposal_sha256': fresh['proposal_sha256']}
            with engine.connect() as conn, conn.begin():
                conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
                refs = {str(r['id']): dict(r) for r in conn.execute(text("SELECT * FROM geographic_reference WHERE kind='county'")).mappings()}
                check['archived_reference_rows_equal_live'] = all(
                    all(str(refs[r['id']][k]) == str(v) for k,v in r.items() if k not in {'source_name','release_sha256'})
                    for r in manifest['references'])
                hashes = {str(r.id): r.sha256 for r in conn.execute(text('SELECT id,sha256 FROM source_release'))}
                check['archived_reference_release_hashes_equal_live'] = all(hashes[r['release_id']] == r['release_sha256'] for r in manifest['references'])
                check['observation_source_hashes_equal_live'] = all(hashes[r['release_id']] == r['sha256'] for r in manifest['observation_scope'])
                scope = {(r['release_id'], r['year']) for r in manifest['observation_scope']}
                obs_rows = [dict(r) for r in conn.execute(select(O.__table__).where(O.year.in_(fresh['election_years']))
                            .order_by(O.year,O.state_code,O.source_row_number)).mappings()
                            if (str(r['release_id']),r['year']) in scope]
                heads = {str(r['observation_id']): dict(r) for r in conn.execute(text('''SELECT * FROM geographic_resolution g
                    WHERE reference_release_id=:release AND NOT EXISTS(SELECT 1 FROM geographic_resolution c WHERE c.supersedes_id=g.id)'''),
                    {'release': UUID(fresh['reference_release_id'])}).mappings()}
            by_code, latest, legacy, newer, supplements, aliases, changes = context.indexes(manifest, *fresh['product_years'])
            by_name = defaultdict(list)
            for r in by_code.values():
                by_name[(r['state_fips'], independent_tokens(r['name_raw']).__repr__())].append(r)
            # by_name is used only to suggest missing-FIPS candidates; it never
            # establishes a match. Use an empty map to avoid sharing normalization.
            status_counts = Counter()
            changed_ids = set()
            for obs in obs_rows:
                decision = assess_observation(obs, by_code, {}, latest, UUID(fresh['reference_release_id']),
                    *fresh['product_years'], aliases=aliases, legacy_by_code=legacy,
                    verified_changes=changes, cross_release_by_code=newer, supplemental_2000_by_code=supplements)
                oid = str(obs['id'])
                old = heads[oid]
                ref = refs.get(str(decision['reference_id']))
                old_ref = refs.get(str(old['reference_id']))
                err = independent_match(obs, ref) if decision['status'] in MATCHED else None
                old_err = independent_match(obs, old_ref) if old['status'] in MATCHED else None
                changed = tuple(old[k] for k in ('status','method','reference_id','jurisdiction_id')) != tuple(decision[k] for k in ('status','method','reference_id','jurisdiction_id'))
                if changed:
                    changed_ids.add(oid)
                status_counts[decision['status']] += 1
                outcomes.append({
                    'observation_id': oid, 'decision_id': str(old['id']), 'observation_release_id': str(obs['release_id']),
                    'source_row_number': obs['source_row_number'], 'row_sha256': obs['row_sha256'],
                    'year': obs['year'], 'state': obs['state_code'], 'state_fips': obs['state_fips'],
                    'raw_label': obs['county_raw'], 'raw_code': obs['county_fips_raw'], 'normalized_code': obs['county_fips'],
                    'candidate': obs['candidate_raw'], 'mode': obs['mode_raw'], 'votes': obs['candidate_votes'],
                    'source_total_votes': obs['total_votes'], 'primary_release_id': fresh['reference_release_id'],
                    'old_status': old['status'], 'proposed_status': decision['status'], 'old_method': old['method'],
                    'proposed_method': decision['method'], 'old_reference_id': str(old['reference_id']) if old['reference_id'] else None,
                    'proposed_reference_id': str(decision['reference_id']) if decision['reference_id'] else None,
                    'old_jurisdiction_id': str(old['jurisdiction_id']) if old['jurisdiction_id'] else None,
                    'proposed_jurisdiction_id': str(decision['jurisdiction_id']) if decision['jurisdiction_id'] else None,
                    'old_reference_label': old_ref['name_raw'] if old_ref else None,
                    'proposed_reference_label': ref['name_raw'] if ref else None,
                    'proposed_reference_release_id': str(ref['release_id']) if ref else None,
                    'cross_release_proposal': bool(ref and str(ref['release_id']) != fresh['reference_release_id'] and decision['status'] in MATCHED),
                    'changed': changed, 'independent_match_error': err, 'published_match_error': old_err,
                    'historical_comparison': bool(decision['evidence_json'].get('historical_comparison')),
                    'evidence_json': json.dumps(decision['evidence_json'], default=str, ensure_ascii=False),
                })
            check['independent_scope_count'] = len(obs_rows)
            check['observation_set_matches_report_differences'] = changed_ids == {r['observation_id'] for r in fresh['differences']}
            check['status_counts_equal'] = dict(status_counts) == fresh['status_counts']
            validation.append(check)
            print(json.dumps(check))
    finally:
        event.remove(engine, 'before_cursor_execute', capture_sql)
    frame = pl.DataFrame(outcomes, infer_schema_length=None)
    frame.write_csv(output / 'all-observation-checks.csv')
    independent_votes = frame.group_by(['year','state']).agg(pl.col('votes').sum().alias('candidate_votes_total')).sort(['year','state']).to_dicts()
    expected_votes = sorted([x for r in reports for x in r['vote_totals_by_year_state']], key=lambda x:(x['year'],x['state']))
    validations = [value for row in validation for k,value in row.items() if k.endswith(('_live','_fresh','_valid','_differences','_equal'))]
    result = {'comparisons': validation, 'observations': frame.height,
        'unique_observations': frame['observation_id'].n_unique(),
        'all_observations_accounted_once': frame.height == frame['observation_id'].n_unique() == 94151,
        'independent_vote_sums_equal_reports': independent_votes == expected_votes,
        'independent_vote_totals_by_year_state': independent_votes,
        'independent_proposed_match_errors': frame.filter(pl.col('independent_match_error').is_not_null()).select(['observation_id','independent_match_error']).to_dicts(),
        'unsafe_published_matches': frame.filter(pl.col('published_match_error').is_not_null()).select(['observation_id','published_match_error']).to_dicts(),
        'cross_release_matched': frame.filter(pl.col('cross_release_proposal')).height,
        'statement_count': len(sql_log), 'database_mutating_statements': 0,
        'read_only_transactions': sum('READ ONLY' in s for s in sql_log),
        'all_comparison_validations_pass': all(validations)}
    dump(output / 'independent-verification.json', result)
    dump(output / 'preview-sql-statements.json', sql_log)
    assert result['all_observations_accounted_once'] and result['independent_vote_sums_equal_reports'] and all(validations)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['before','sources','verify','after'])
    p.add_argument('--output-dir', type=Path, default=ROOT)
    p.add_argument('--archive-dir', type=Path, default=OLD)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.phase in {'before','after'}:
        inventory(args.output_dir,args.phase)
    elif args.phase == 'sources':
        sources(args.output_dir)
    else:
        verify(args.output_dir, args.archive_dir)


if __name__ == '__main__':
    main()
