"""Build DATA-005 evidence/coverage reports from a read-only database export.

This command is offline and never publishes decisions or canonical results.
Exit 2 with --require-complete when outstanding evidence/mismatches remain.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from ingestion.data005 import (BUCKETS, FORMAT, alaska_district, compare, digest, evidence,
    exclusion_partition, fec_states, manual_units, sum_observations, unit_key,
    virginia_units, minnesota_units)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')


def table(path, rows):
    if not rows:
        raise ValueError(f'Empty report {path.name}')
    columns = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows({k: json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v
                         for k, v in r.items()} for r in rows)


def selected(rows, scope):
    return [r for r in rows if scope == 'source' or r[f'{scope}_accepted']]


def label(row):
    name = row['county']
    if row['state'] == 'VA' and int(row['county_fips'][2:]) >= 500 and not name.endswith(' CITY'):
        name += ' CITY'
    return unit_key(name)


def load_official(directory, mn_directory=None, mn_lookup=None):
    records = evidence(directory)
    def pages(key):
        r = records[key]
        if not r.get('success'):
            raise ValueError(f'Required official evidence unavailable: {key}')
        return json.loads((directory / r['text_file']).read_text(encoding='utf-8'))
    states = fec_states(pages('fec-2008-president'), records['fec-2008-president'])
    county = {
        'MO': manual_units(pages('mo-2008-manual')[3]['text'],
            ['JOHN MCCAIN', 'BARACK OBAMA'] + ['OTHER'] * 4,
            records['mo-2008-manual'], 'PDF page 4; printed pages 600-601; President', 116),
        'MN': manual_units(pages('mn-2008-manual')[21]['text'],
            ['JOHN MCCAIN', 'BARACK OBAMA'] + ['OTHER'] * 6,
            records['mn-2008-manual'], 'PDF page 22; printed page 494; President', 87),
        'VA': virginia_units((directory / records['va-2008-counties']['file']).read_text(encoding='utf-8-sig'),
            records['va-2008-counties']),
    }
    county['AK'] = []
    for n in range(1,41):
        key = 'ak-2008-district8' if n == 8 else f'ak-2008-district{n:02d}'
        county['AK'].append(alaska_district(pages(key), records[key], n))
    manual_mn = county['MN']
    if mn_directory is not None:
        additional = evidence(mn_directory)
        r = additional['mn-2008-county-text']
        if not r['success']:
            raise ValueError('Minnesota county text evidence unavailable')
        with mn_lookup.open(encoding='utf-8', newline='') as stream:
            lookup = list(csv.DictReader(stream))
        body = (mn_directory / r['file']).read_text(encoding='utf-8')
        table_text = '\n'.join(f"{x['county_id']};{x['county_name']};0" for x in lookup)
        county['MN'] = minnesota_units(body, table_text, r)
        records[r['id']] = r
        records['mn-reviewed-lookup'] = dict(id='mn-reviewed-lookup',
            url='https://electionresults.sos.mn.gov/Results/MediaFile_Archive/Index?erselectionId=63&mediafileid=6',
            sha256=sha256(mn_lookup.read_bytes()).hexdigest(),
            retrieved_at=None,
            extraction='Manual transcription of web tool extraction; not archived original bytes. Direct retrieval returned CAPTCHA.')
    return records, states, county, manual_mn


def geography_audit(observations, geo_directory):
    """Verify actual stored direct successors, not a stale approval-status file."""
    targets = {}
    for path in sorted((geo_directory / 'approvals').glob('*.json')):
        envelope = json.loads(path.read_text(encoding='utf-8'))
        manifest = envelope['manifest']
        if digest(manifest) != envelope['publication_sha256']:
            raise ValueError('Geography manifest checksum differs')
        for target in manifest['targets']:
            key = target['observation_id']
            if key in targets:
                raise ValueError('Overlapping geographic authorization targets')
            targets[key] = (target, manifest, envelope['publication_sha256'])
    results = []
    for row in observations:
        head = row['geography']
        if head['supersedes_id'] is None:
            continue
        key = row['observation_id']
        if key not in targets or not (head['published_by'] or '').strip():
            raise ValueError('Published head missing exact manifest or actor')
        target, manifest, sha = targets[key]
        stored_payload = {k: head[k] for k in ('status','method','reference_id','jurisdiction_id','reason')}
        stored_payload['evidence_json'] = {k: v for k,v in head['evidence_json'].items()
                                           if k not in ('ruleset_version','publication_audit')}
        if (stored_payload != target['decision'] or head['supersedes_id'] != target['previous']['id']
                or head['context_sha256'] != manifest['context_sha256']
                or head['evidence_json'].get('publication_audit',{}).get('publication_sha256') != sha):
            raise ValueError('Expected already-published direct successor')
        results.append(dict(observation_id=key, head_id=head['id'],
            supersedes_id=head['supersedes_id'], actor=head['published_by'],
            context_sha256=head['context_sha256'], publication_sha256=sha,
            status=head['status'], exact_manifest_successor=True))
    return results


def build(snapshot, handoff, directory, geo_directory, output, mn_directory=None, mn_lookup=None):
    output.mkdir(parents=True, exist_ok=False)
    rows = snapshot['observations']
    by_id = exclusion_partition(handoff, rows)
    records, official_states, official_units, manual_mn = load_official(directory, mn_directory, mn_lookup)
    geo = geography_audit(rows, geo_directory)
    table(output / 'geography-publication-audit.csv', geo)
    write(output / 'official-state-components.json', official_states)
    write(output / 'official-unit-components.json', official_units)
    official_comparisons = []
    for st, units in official_units.items():
        for b in BUCKETS:
            sums = sum(u['totals'][b] for u in units)
            official_comparisons.append(dict(state=st, candidate_bucket=b,
                **compare(official_states[st]['totals'][b], sums, comparable=True, complete=True),
                expected_source=official_states[st]['source_url'],
                observed_source=units[0]['source_url'], observed_sha256=units[0]['source_sha256'],
                note='Official documents can disagree; neither is silently corrected or substituted.'))
    table(output / 'official-source-comparisons.csv', official_comparisons)
    manual_checks = []
    for manual, current in zip(manual_mn, official_units['MN']):
        if manual['unit_key'] != current['unit_key']:
            raise ValueError('Minnesota county lookup differs from the independently archived manual')
        named_writeins = sum(c['votes'] for c in current['components']
            if isinstance(c, dict) and c['candidate_id'].startswith('99') and c['candidate_id'] != '9901')
        for b in BUCKETS:
            delta = current['totals'][b] - manual['totals'][b]
            if mn_directory and delta != (named_writeins if b == 'OTHER' else 0):
                raise ValueError('Minnesota manual/export difference not explained by named write-ins')
            manual_checks.append(dict(state='MN', unit=manual['unit'], candidate_bucket=b,
                manual_votes=manual['totals'][b], archived_export_votes=current['totals'][b],
                difference=delta, named_writein_votes=named_writeins,
                disposition='EXPLAINED_NAMED_WRITEINS' if delta else 'EXACT',
                manual_locator=manual['source_locator'], export_locator=current['source_locator']))
    table(output / 'minnesota-manual-export-comparisons.csv', manual_checks)
    comparisons, coverage = [], []
    for state, authority in sorted(official_states.items()):
        inputs = [r for r in rows if r['state'] == state]
        raw_totals = sum_observations(inputs)
        for scope in ('source', 'stored', 'preview'):
            included = selected(inputs, scope)
            sums = sum_observations(included)
            missing = [r for r in inputs if r not in included]
            coverage.append(dict(state=state, scope=scope, input_rows=len(inputs),
                accepted_rows=len(included), excluded_rows=len(missing),
                accepted_votes=sum(sums.values()), excluded_votes=sum(r['votes'] for r in missing),
                excluded_reasons=dict(Counter(r['preview_reason'] if scope == 'preview' else
                    'GEOGRAPHY_NOT_RESOLVED_IN_STORED_BATCH' for r in missing)),
                source_votes_nonadditive=sum(raw_totals.values()),
                official_votes=authority['total_votes'],
                county_coverage_verified=False,
                caveat='State numeric agreement does not verify county completeness or additive special-unit semantics.'))
            for b in BUCKETS:
                comparisons.append(dict(state=state, scope=scope, candidate_bucket=b,
                    reporting_level='state', reporting_mode='TOTAL', election_stage='general',
                    complete_source_row_coverage=len(included) == len(inputs),
                    **compare(authority['totals'][b], sums[b], comparable=True,
                              complete=len(included) == len(inputs)),
                    source_url=authority['source_url'], source_sha256=authority['source_sha256'],
                    source_locator=authority['source_locator'],
                    explanation=('Exact grouped state numeric comparison; county coverage separately assessed'
                        if sums[b] == authority['totals'][b] else
                        'Excluded source rows contribute to the gap; remaining source differences require investigation'
                        if missing else 'MEDSL/FEC source-value or category-definition discrepancy; cause unverified')))
    table(output / 'state-comparisons.csv', comparisons)
    table(output / 'state-coverage.csv', coverage)

    unit_comparisons = []
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['state'], label(row))].append(row)
    unit_lookup = {(st, x['unit_key']): x for st, units in official_units.items() for x in units}
    for state, key in sorted(set(grouped) | set(unit_lookup)):
        inputs = grouped.get((state, key), [])
        expected = unit_lookup.get((state, key))
        for scope in ('source', 'stored', 'preview'):
            chosen = selected(inputs, scope)
            sums = sum_observations(chosen)
            for b in BUCKETS:
                unit_comparisons.append(dict(state=state, unit=key, scope=scope, candidate_bucket=b,
                    reporting_level=('state_legislative_reporting_district' if state == 'AK' else
                                     'election_authority_segment' if state == 'MO' and key in ('JACKSON','KANSASCITY')
                                     else 'county_or_independent_city'),
                    reporting_mode='TOTAL', election_stage='general',
                    **compare(expected['totals'][b] if expected else None, sums[b],
                        comparable=True, complete=bool(inputs) and len(chosen) == len(inputs),
                        evidence_available=expected is not None),
                    observation_ids=[r['observation_id'] for r in chosen],
                    source_url=expected['source_url'] if expected else None,
                    source_sha256=expected['source_sha256'] if expected else None,
                    source_locator=expected['source_locator'] if expected else None,
                    coverage_note=('Jackson/Kansas City are separate authority rows; no complete Jackson county claim'
                        if state == 'MO' and key in ('JACKSON','KANSASCITY') else
                        'Source label comparison only; no geographic decision approval implied')))
    table(output / 'unit-comparisons.csv', unit_comparisons)

    dispositions = []
    for h in handoff:
        r = by_id[h['observation_id']]
        st, name = r['state'], r['county']
        expected = unit_lookup.get((st, label(r)))
        if st == 'AK':
            status = 'DISTRICT_99_DEFINITION_UNVERIFIED' if name == 'DISTRICT 99' else 'EXACT_NON_COUNTY_DISTRICT_TOTAL'
            owner = 'GEO-002' if name == 'DISTRICT 99' else 'DATA-005'
            note = 'No county allocation. District 99 zero values do not prove placeholder semantics.'
        elif st == 'MN':
            status, owner = 'OFFICIAL_NUMERIC_CHECK_ALIAS_APPROVAL_REQUIRED', 'GEO-002'
            note = 'Official SAINT LOUIS county row supports vote comparison; alias/identity remains a separate approval.'
        elif st == 'VA':
            status, owner = 'PUBLISHED_GEOGRAPHY_ELIGIBLE_IN_PREVIEW', 'DATA-005'
            note = 'Exact published county decision verified; canonical supersession requires separate authorization.'
        elif st == 'MO':
            status, owner = 'EXACT_SEPARATE_ELECTION_AUTHORITY_SEGMENT', 'DATA-005;QA-001'
            note = 'Kansas City matches official authority row; Jackson accepted row is a separate segment, not full county coverage.'
        else:
            status, owner = 'ZERO_VOTE_SPECIAL_UNIT_SEMANTICS_UNVERIFIED', 'DATA-005'
            note = 'Classification is published. Zero votes do not prove placeholder/additive/overlap semantics.'
        dispositions.append(dict(observation_id=r['observation_id'], source_row_number=r['source_row_number'],
            row_sha256=r['row_sha256'], source_release_id=r['release_id'], state=st,
            unit=name, candidate_bucket=r['candidate'], votes=r['votes'],
            original_reason='GEOGRAPHY_NOT_RESOLVED', current_geographic_status=r['geography']['status'],
            current_decision_id=r['geography']['id'], published_by=r['geography']['published_by'],
            preview_accepted=r['preview_accepted'], preview_reason=r['preview_reason'],
            disposition=status, owner=owner, note=note,
            official_votes=expected['totals'][r['candidate']] if expected else None,
            difference=r['votes']-expected['totals'][r['candidate']] if expected else None,
            evidence_locator=expected['source_locator'] if expected else h['evidence_citations']))
    table(output / 'original-144-dispositions.csv', dispositions)

    changes = [dict(observation_id=r['observation_id'], state=r['state'], unit=r['county'],
        candidate_bucket=r['candidate'], votes=r['votes'],
        before_accepted=r['stored_accepted'], after_accepted=r['preview_accepted'],
        previous_resolution_id=r['stored_resolution_id'], current_resolution_id=r['geography']['id'],
        change=('ADDED' if r['preview_accepted'] and not r['stored_accepted'] else
                'REMOVED' if r['stored_accepted'] and not r['preview_accepted'] else 'LINEAGE_ONLY'))
        for r in rows if r['stored_accepted'] != r['preview_accepted'] or
        (r['preview_accepted'] and r['stored_resolution_id'] != r['geography']['id'])]
    table(output / 'canonical-preview-changes.csv', changes)
    # Bind the review package to source, published decisions, exact projection,
    # canonical predecessor, expected counts/votes and authoritative inputs.
    package = dict(format=FORMAT, source=snapshot['source'], predecessor=snapshot['stored_batch'],
        preview=snapshot['preview'], changes=changes,
        evidence={k: {a: v[a] for a in ('url','sha256','retrieved_at','extraction') if a in v} for k,v in records.items()},
        canonical_supersession_authorized=False, approving_actor=None,
        publication_status='NOT_ATTEMPTED', expected_status='PARTIAL',
        warning='Official mismatches and incomplete county coverage remain; publication does not certify completeness.')
    write(output / 'canonical-publication-review.json', dict(review_sha256=digest(package), review=package))
    source_checks = [r for r in comparisons if r['scope'] == 'source']
    mismatch_states = sorted({r['state'] for r in source_checks if r['disposition'] == 'MISMATCH'})
    summary = dict(format=FORMAT, generated_at=datetime.now(timezone.utc).isoformat(),
        status='PARTIALLY_COMPLETE', input_rows=len(rows), original_exclusions=len(dispositions),
        source_votes_nonadditive=sum(r['votes'] for r in rows),
        stored_batch=snapshot['stored_batch'], preview=snapshot['preview'],
        official_state_total=sum(v['total_votes'] for v in official_states.values()),
        source_states_all_buckets_exact=51-len(mismatch_states), source_mismatch_states=mismatch_states,
        state_comparison_dispositions=dict(Counter(r['disposition'] for r in comparisons)),
        unit_comparison_dispositions=dict(Counter(r['disposition'] for r in unit_comparisons)),
        official_source_discrepancies=[r for r in official_comparisons if r['disposition'] != 'EXACT'],
        independent_unit_sources={st: len(units) for st,units in official_units.items()},
        published_2008_successors_verified=len(geo), published_actors=sorted({r['actor'] for r in geo}),
        preview_changes=dict(Counter(r['change'] for r in changes)),
        original_exclusion_dispositions=dict(Counter(r['disposition'] for r in dispositions)),
        complete_county_coverage=False, complete_state_coverage=False,
        canonical_publication_attempted=False, canonical_publication_review_sha256=digest(package),
        blockers=[f'{len(mismatch_states)} states have at least one source/FEC bucket discrepancy; no source corrections authorized',
            'Independent county evidence is not complete nationwide',
            'Minnesota alias decisions remain unapproved/unpublished',
            'District 99 and zero-vote special-unit semantics remain unverified',
            'Jackson authority segment does not establish complete county coverage',
            'Canonical supersession requires separate approval of the concrete review package'])
    write(output / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--handoff', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--geo-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--require-complete', action='store_true')
    parser.add_argument('--mn-evidence-dir', type=Path)
    parser.add_argument('--mn-lookup', type=Path)
    args = parser.parse_args()
    source = json.loads(args.snapshot.read_text(encoding='utf-8'))
    with args.handoff.open(encoding='utf-8', newline='') as stream:
        handoff = list(csv.DictReader(stream))
    if bool(args.mn_evidence_dir) != bool(args.mn_lookup):
        parser.error('--mn-evidence-dir and --mn-lookup must be supplied together')
    result = build(source, handoff, args.evidence_dir, args.geo_dir, args.output_dir,
                   args.mn_evidence_dir, args.mn_lookup)
    print(json.dumps(result, indent=2))
    if args.require_complete and result['status'] != 'COMPLETE':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
