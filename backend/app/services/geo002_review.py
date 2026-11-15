"""Prepare exact GEO-002 approval targets from fresh read-only evidence; never publish."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID

import polars as pl
from sqlalchemy import select, text

from app.database import engine
from app.models.ingestion import ElectionResultObservation as O
from app.services.geo001_audit import independent_match, MATCHED
from ingestion.geography import context, selection
from ingestion.geography.resolve import assess_observation, resolve_medsl
from ingestion.geography.resolution_v2 import current_resolution_rows

VINTAGES = (2000, 2004, 2012, 2020, 2024)
ROUTINE_GROUPS = {'TYPED_INDEPENDENT_CITY_METHOD', 'VIRGINIA_COUNTY_LABEL',
    'CENSUS_2000_SUPPLEMENT', 'CT_SPECIAL_REPORTING_CATEGORY', 'ME_SPECIAL_REPORTING_CATEGORY',
    'RI_SPECIAL_REPORTING_CATEGORY', 'MO_KANSAS_CITY_REPORTING_UNIT'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        f.write(json.dumps(obj, indent=2, default=str, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('/app/data/geo002'))
    parser.add_argument('--handoff-dir', type=Path, default=Path('/app/data/geo001'))
    args = parser.parse_args()
    out, handoff = args.output_dir, args.handoff_dir
    if (out / 'approval-manifest.json').exists():
        raise ValueError('Existing approval package must be preserved; choose a fresh output directory')
    baseline = read(out / 'full-before.json')
    if baseline['observation_raw_hash_errors'] or baseline['duplicate_heads']:
        raise ValueError('Unsafe baseline')
    fresh_checks = pl.read_csv(out / 'all-observation-checks.csv', infer_schema_length=0)
    if fresh_checks.height != 94151 or fresh_checks['observation_id'].n_unique() != 94151:
        raise ValueError('Unexpected observation scope; review drift')
    verification = read(out / 'independent-verification.json')
    if not verification['all_comparison_validations_pass']:
        raise ValueError('Independent verification failed')
    source_integrity = read(out / 'source-integrity.json')
    if source_integrity['released_label_mismatches'] or source_integrity['archived_observation_row_errors']:
        raise ValueError('Source integrity failed')
    rows = pl.read_csv(handoff / 'review-ledger.csv', infer_schema_length=0).to_dicts()
    if len(rows) != 1955 or len({r['observation_id'] for r in rows}) != 1955:
        raise ValueError('Unexpected review ledger scope')
    handoff_targets = {x['vintage']: x for x in read(handoff / 'geo002-review-package.json')['corrected_preview_targets']}
    ledger = {r['observation_id']: dict(r) for r in rows}
    routine, bedford = [], []
    independent_digests = []
    compared = set()
    for vintage in VINTAGES:
        report = read(out / 'reproduced' / f'compare-{vintage}.json')
        archived = read(handoff / 'corrected/reproduced' / f'compare-{vintage}.json')
        if report != archived:
            raise ValueError(f'GEO-001 comparison drift: {vintage}')
        manifest = report['context_manifest']
        # Independent JSON/SHA implementation, separate from publication helpers.
        ctx_sha = sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        diff_payload = {'reference_release_id': report['reference_release_id'],
            'ruleset_version': report['ruleset_version'], 'context_sha256': ctx_sha,
            'differences': report['differences']}
        diff_sha = sha256(json.dumps(diff_payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if ctx_sha != handoff_targets[vintage]['context_sha256'] or diff_sha != handoff_targets[vintage]['proposal_sha256']:
            raise ValueError('Independent digest mismatch')
        independent_digests.append({'vintage': vintage, 'context_sha256': ctx_sha,
            'full_proposal_sha256': diff_sha, 'matches_handoff': True})
        release = UUID(report['reference_release_id'])
        by_code, latest, legacy, newer, supplements, aliases, changes = context.indexes(manifest, *report['product_years'])
        refs = {str(r['id']): r for r in manifest['references']}
        changed_ids = {r['observation_id'] for r in report['differences']}
        if not changed_ids <= set(ledger):
            raise ValueError('Changed observations missing from review ledger')
        routine_targets, bedford_targets = [], []
        with engine.connect() as c, c.begin():
            c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            heads = current_resolution_rows(c, release)
            scope_ids = [UUID(r['observation_id']) for r in rows if r['primary_release_id'] == str(release)]
            observations = c.execute(select(O.__table__).where(O.id.in_(scope_ids))).mappings().all()
            for obs in observations:
                oid = str(obs['id']); row = ledger[oid]; old = heads[obs['id']]
                if str(old['id']) != row['decision_id'] or obs['row_sha256'] != row['row_sha256']:
                    raise ValueError('Review predecessor/source drift')
                decision = assess_observation(dict(obs), by_code, {}, latest, release, *report['product_years'],
                    aliases=aliases, legacy_by_code=legacy, verified_changes=changes,
                    cross_release_by_code=newer, supplemental_2000_by_code=supplements)
                if (decision['status'] != row['proposed_status'] or decision['method'] != row['proposed_method']
                        or decision['evidence_json'] != json.loads(row['evidence_json'])):
                    raise ValueError('Review payload drift')
                err = independent_match(dict(obs), refs.get(str(decision['reference_id']))) if decision['status'] in MATCHED else None
                if err != row['independent_match_error']:
                    raise ValueError('Independent match assessment drift')
                group = row['review_group']
                permitted_group = group in ROUTINE_GROUPS or group.endswith('_HOUSE_REPORTING_DISTRICTS')
                supported = row['independent_assessment'] == 'SUPPORTED' and row['publication_disposition'] == 'REVIEW_SUPPORTED_PROPOSAL'
                review = 'HOLD_NO_PUBLICATION'
                if permitted_group and supported and oid in changed_ids:
                    if err:
                        raise ValueError('Unsupported match in routine subset')
                    routine_targets.append(selection.target(obs['id'], old, decision))
                    review = 'REQUEST_ROUTINE_APPROVAL'
                elif group == 'BEDFORD_2016_DOWNGRADE':
                    if obs['candidate_votes'] != 0 or decision['status'] != 'PENDING_REVIEW' or decision['jurisdiction_id'] is not None:
                        raise ValueError('Unexpected Bedford downgrade')
                    bedford_targets.append(selection.target(obs['id'], old, decision))
                    review = 'REQUEST_SEPARATE_DOWNGRADE_APPROVAL'
                row.update(geo002_disposition=review, technical_reviewer='Codex GEO-002 independent technical review',
                    approving_actor=None, publication_authorized=False,
                    geo002_independent_match_check='PASS' if not err else err,
                    geo002_manifest_file=None, geo002_publication_sha256=None,
                    geo002_research_note='See docs/geography/GEO002-RESEARCH.md and research/retrievals.json; no evidence approval inferred.')
                compared.add(oid)
        for label, targets, collection, flag in [('routine', routine_targets, routine, False),
                                                ('bedford', bedford_targets, bedford, True)]:
            if not targets:
                continue
            subset = selection.manifest(release, report['ruleset_version'], ctx_sha, targets)
            selection.validate(subset, release, report['ruleset_version'], ctx_sha)
            subset_sha = context.digest(subset)
            filename = f'approvals/{label}-{vintage}.json'
            write(out / filename, {'manifest': subset, 'publication_sha256': subset_sha})
            preview, _ = resolve_medsl(engine, vintage=vintage, publish=False,
                context_manifest=manifest, publication_manifest=subset)
            if preview['publication_pending_count'] != len(targets) or preview['records_inserted']:
                raise ValueError('Subset preview did not match reviewed targets')
            write(out / f'subset-preview/{label}-{vintage}.json', preview)
            collection.append({'vintage': vintage, 'manifest_file': filename,
                'context_file': f'reproduced/compare-{vintage}.json', 'reference_release_id': str(release),
                'context_sha256': ctx_sha, 'publication_sha256': subset_sha,
                'target_count': len(targets), 'allow_downgrades_required': flag,
                'jurisdiction_reassignments': preview['publication_reassignments'],
                'full_vintage_proposal_is_not_approved': diff_sha})
            for t in targets:
                ledger[t['observation_id']].update(geo002_manifest_file=filename, geo002_publication_sha256=subset_sha)
    if compared != set(ledger):
        raise ValueError('Incomplete observation review')
    frame = pl.DataFrame(list(ledger.values()), infer_schema_length=None)
    frame.write_csv(out / 'review-ledger.csv')
    frame.filter(pl.col('geo002_disposition') == 'HOLD_NO_PUBLICATION').write_csv(out / 'hold-ledger.csv')
    frame.group_by(['review_group', 'geo002_disposition', 'owner', 'rationale', 'research_remaining']).agg(
        pl.len().alias('observations')).sort(['geo002_disposition', 'review_group']).write_csv(out / 'review-groups.csv')
    dispositions = dict(Counter(r['geo002_disposition'] for r in ledger.values()))
    package = {'task': 'GEO-002', 'ruleset': 'step6.2.1', 'publication_authorized': False,
        'approving_actor': None, 'canonical_supersession_authorized': False,
        'jurisdiction_reassignment_authorized': False, 'routine': routine, 'bedford_separate': bedford,
        'reviewed_observations': len(ledger), 'dispositions': dispositions,
        'cross_release_eligibility_unchanged': 47,
        'approval_request': 'Approve the listed exact routine SHA-256 targets and name an accountable actor. '
            'Separately approve or decline the Bedford SHA-256 and explicit downgrades. '
            'Neither approval permits held changes, alias/change verification, identity/reference repair or canonical supersession.'}
    write(out / 'approval-manifest.json', package)
    write(out / 'independent-digest-checks.json', independent_digests)
    write(out / 'bedford-impact.json', {'observations': [r for r in ledger.values() if r['review_group'] == 'BEDFORD_2016_DOWNGRADE'],
        'votes': 0, 'canonical_batch_unchanged': '4b122026-b9c1-4b0e-9529-3ee3f8eb753c',
        'conditional_future_2016_counts': {'accepted_before': 9327, 'accepted_after_downgrade_only': 9324,
            'excluded_before': 147, 'excluded_after_downgrade_only': 150, 'votes': 135881227},
        'canonical_supersession_authorized': False, 'successor_remap_authorized': False})
    write(out / 'publication-audit.json', {'status': 'AWAITING_EXPLICIT_APPROVAL', 'live_publish_attempts': 0,
        'live_decisions_added': 0, 'approving_actor': None,
        'live_publication_idempotence': 'PENDING_APPROVAL; isolated PostgreSQL integration tests exercise publication/replay',
        'approval_manifest': 'approval-manifest.json'})
    print(json.dumps({'reviewed': len(ledger), 'dispositions': dispositions,
        'routine_targets': sum(x['target_count'] for x in routine), 'bedford_targets': sum(x['target_count'] for x in bedford),
        'publication_authorized': False}))


if __name__ == '__main__':
    main()
