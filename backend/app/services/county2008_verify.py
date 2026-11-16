"""Reproduce county/reporting-unit verification without publishing or allocating.

Run with the research requirements installed. Raw archives are required; all
successful downloads are checked before extraction. Reports are append-only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from ingestion.county2008 import (assess, census_cells, civera_csv, florida,
    california, candidate_csv, colorado, complete_county_coverage, explain_difference, hawaii, idaho, illinois, maryland, massachusetts,
    montana, montana_legislative_accounting, municipal_to_counties, new_jersey, oklahoma, pennsylvania, pennsylvania_counties, south_dakota,
    observation_inventory, stable_town_lookup, tennessee, texas, wyoming)
from ingestion.presidential_returns_2008 import BUCKETS, digest, evidence, exclusion_partition, minnesota_units, provenance, unit_key
from app.services.presidential_returns_reconciliation import load_official, table, write


class Archive:
    def __init__(self, directories):
        self.records, self.paths = {}, {}
        for directory in directories:
            for key, r in evidence(directory).items():
                if key in self.records:
                    raise ValueError(f'Duplicate evidence ID: {key}')
                self.records[key] = r
                if r.get('success'):
                    self.paths[key] = directory / r['file']

    def raw(self, key):
        if key not in self.paths:
            raise ValueError(f'Required official evidence unavailable: {key}')
        return self.paths[key].read_bytes()

    def text(self, key, encoding='utf-8-sig'):
        return self.raw(key).decode(encoding)

    def pages(self, key, numbers=None):
        from pypdf import PdfReader
        import io
        reader=PdfReader(io.BytesIO(self.raw(key)))
        indices = range(1,len(reader.pages)+1) if numbers is None else numbers
        return [dict(page=n, text=reader.pages[n-1].extract_text(extraction_mode='layout') or '',
                     plain_text=reader.pages[n-1].extract_text() or '') for n in indices]

    def sheet(self, key):
        import xlrd
        s = xlrd.open_workbook(file_contents=self.raw(key)).sheet_by_index(0)
        return [s.row_values(n) for n in range(s.nrows)]


def references(archive):
    import xlrd
    return census_cells(xlrd.open_workbook(file_contents=archive.raw('census-ele')),
        archive.sheet('census-metadata'), archive.sheet('census-source'),
        archive.sheet('census-flags'), archive.sheet('census-footnotes'),
        archive.records['census-ele'])


def official_counties(archive, prior, mn_directory, mn_lookup):
    mn_records=evidence(mn_directory)
    if 'mn-2008-county-table' in mn_records:
        records, states, official, _=load_official(prior)
        def mntext(key):
            if not mn_records[key]['success']:
                raise ValueError('Original Minnesota county lookup/export unavailable')
            return (mn_directory/mn_records[key]['file']).read_text(encoding='utf-8-sig')
        official['MN']=minnesota_units(mntext('mn-2008-county-text'),mntext('mn-2008-county-table'),mn_records['mn-2008-county-text'])
        for row in official['MN']:
            row['lookup_source']=provenance(mn_records['mn-2008-county-table'],
                f'Official county-ID table; ID {row["authority_county_id"]}; semicolon layout')
        records.update({k:mn_records[k] for k in ('mn-2008-county-table','mn-2008-county-text','mn-2008-layout')})
    else:
        records, states, official, _ = load_official(prior, mn_directory, mn_lookup)
    r = archive.records
    official.update({
        'CA': california(archive.raw('ca-president'),r['ca-president']),
        'CO': colorado(archive.pages('co-abstract',[93,94,95]),r['co-abstract'],archive.raw('co-abstract')),
        'NY': civera_csv(archive.text('ny-export'), r['ny-export'], state='NY', count=62),
        'FL': florida(archive.text('fl-extract'), r['fl-extract']),
        'PA': pennsylvania_counties(archive.text('pa-2008-president'), archive.text('pa-2008-metadata'),
                                   archive.text('pa-2008-state'),r['pa-2008-president']),
        'SD': south_dakota(archive.text('sd-president'), r['sd-president']),
        'MA': massachusetts(archive.text('ma-president'), r['ma-president']),
        'TX': texas(archive.text('tx-president'), r['tx-president']),
        'OK': oklahoma(archive.pages('ok-president'), r['ok-president']),
        'ID': candidate_csv(archive.text('id-complete-csv'),r['id-complete-csv'],44,documented_ballot_errors=True),
        'IL': illinois(archive.text('il-county-text','cp1252'),archive.text('il-state-control','cp1252'),r['il-county-text']),
        'MD': maryland(archive.text('md-president'),r['md-president']),
        'NJ': new_jersey(archive.pages('nj-canvass'),r['nj-canvass']),
        'TN': tennessee(archive.raw('tn-followup-1'),r['tn-followup-1']),
    })
    hi={'HAWAII':'hi-followup-1','MAUI':'hi-followup-2','KAUAI':'hi-followup-3','HONOLULU':'hi-followup-4'}
    official['HI']=hawaii({name:archive.pages(key,[1]) for name,key in hi.items()},
                           {name:r[key] for name,key in hi.items()})
    import io,zipfile
    def ziptext(key):
        z=zipfile.ZipFile(io.BytesIO(archive.raw(key)))
        return z.read(z.namelist()[0]).decode('cp1252')
    lookup=stable_town_lookup(ziptext('census-cousub2000'),ziptext('census-cousub2010'),'CT')
    ct=civera_csv(archive.text('ct-followup-1'),r['ct-followup-1'],state='CT',count=169,level='City/Town')
    names={'09001':'Fairfield','09003':'Hartford','09005':'Litchfield','09007':'Middlesex',
           '09009':'New Haven','09011':'New London','09013':'Tolland','09015':'Windham'}
    official['CT']=municipal_to_counties(ct,lookup,names,r['ct-followup-1'])
    for row in official['CT']:
        row['crosswalk_sources']=[r[x] for x in ('census-cousub2000','census-cousub2010')]
    reviewed=Path(__file__).resolve().parents[3]/'docs/sources/county_returns_2008_reviewed_transcriptions.json'
    if not reviewed.exists():
        # Backend mounted at /app; repository docs live at /workspace for offline run.
        reviewed=Path('docs/sources/county_returns_2008_reviewed_transcriptions.json')
    for entry in json.loads(reviewed.read_text(encoding='utf-8'))['tables']:
        from ingestion.county_corrections import evidence_path
        path=evidence_path(reviewed.parents[2],'docs/sources/'+entry['file'])
        if sha256(path.read_bytes()).hexdigest()!=entry['sha256'] or r[entry['evidence_id']]['sha256']!=entry['source_sha256']:
            raise ValueError('Reviewed numeric transcription/source checksum differs')
        if entry['state']=='WY':
            official['WY']=wyoming(path.read_text(encoding='utf-8'),r[entry['evidence_id']])
        elif entry['state']=='MT':
            official['MT']=montana(path.read_text(encoding='utf-8'),archive.pages('mt-writeins'),
                                   r[entry['evidence_id']],r['mt-writeins'])
            accounting=montana_legislative_accounting(archive.raw('mt-writeins'),r['mt-writeins'])
            for row in official['MT']:
                row['nonpresidential_accounting']=accounting.get(row['unit_key'],[])
    for key,record in records.items():
        if key in mn_records and key in ('mn-2008-county-table','mn-2008-county-text','mn-2008-layout'):
            record['archive_location']=str(mn_directory/record['file'])
        elif record.get('file'):
            record['archive_location']=str(prior/record['file'])
    return records, states, official


def source_unit(row):
    name = row['county']
    if row['state'] == 'VA' and row['county_fips'] and int(row['county_fips'][2:]) >= 500:
        if not name.endswith(' CITY'):
            name += ' CITY'
    # A reviewed comparison alias does not publish a geographic decision.
    if row['state'] == 'MN' and name == 'SAINT LOUIS':
        name = 'ST LOUIS'
    return unit_key(name)


def verify(snapshot, handoff, archive, prior, mn_directory, mn_lookup, output):
    output.mkdir(parents=True, exist_ok=False)
    observations = snapshot['observations']
    if len(observations) != 9474 or len({r['observation_id'] for r in observations}) != 9474:
        raise ValueError('Unexpected 2008 baseline observation inventory')
    observation_inventory(observations)
    exclusion_partition(handoff, observations)
    reference, descriptions = references(archive)
    records, fec, official = official_counties(archive, prior, mn_directory, mn_lookup)
    # Retain the earlier official precinct extract as a conflicting/partial
    # source, not an alternative 2008 election or a full candidate-group total.
    precincts=pennsylvania(archive.text('pa-followup-2'),archive.text('pa-followup-1'),archive.records['pa-followup-2'])
    write(output/'pa-official-precinct-crosscheck.json',precincts)
    indexed = {}
    for st, rows in official.items():
        indexed[st] = {r['unit_key']: r for r in rows}
        if len(indexed[st]) != len(rows):
            raise ValueError('Duplicate official reporting unit')
    primary_controls={st:{b:sum(r['totals'][b] for r in rows)==fec[st]['totals'][b]
                          for b in BUCKETS} for st,rows in official.items()}
    comparisons, corrections, differences, inventory = [], [], [], defaultdict(list)
    for row in observations:
        fips, st, key = row['county_fips'], row['state'], source_unit(row)
        county_reference = reference.get(fips)
        is_county = county_reference is not None and st != 'AK'
        cell = county_reference['cells'][row['candidate']] if is_county else None
        primary = indexed.get(st, {}).get(key)
        segment = st == 'MO' and key in ('JACKSON','KANSASCITY')
        coverage = ('election_authority_segment' if segment else 'district' if st == 'AK'
                    else 'county' if is_county else 'unclassified_special_unit')
        # Matching numbers on a segment are useful but cannot prove a county total.
        result = assess(row, cell, primary,
                        state_control_matches=primary_controls.get(st,{}).get(row['candidate'],False))
        result.update(**explain_difference(row,primary),
            observation_id=row['observation_id'], row_sha256=row['row_sha256'],
            source_row_number=row['source_row_number'], source_release_id=row['release_id'],
            source_sha256=snapshot['source']['sha256'], state=st, source_unit=row['county'],
            source_fips=fips, candidate_bucket=row['candidate'], reporting_level=coverage,
            election_year=2008, election_stage='general', vote_mode='TOTAL',
            canonical_stored_accepted=row['stored_accepted'], canonical_preview_accepted=row['preview_accepted'],
            canonical_preview_reason=row['preview_reason'], geography_status=row['geography']['status'],
            reference_flag=cell['flag'] if cell else None,
            reference_source=cell or {}, official_source={k: primary[k] for k in
                ('evidence_id','source_url','source_sha256','retrieved_at','source_locator',
                 'supplement_source','lookup_source','crosswalk_sources','grouping_note','internal_ballot_difference') if k in primary} if primary else {},
            county_candidate_value_verified=is_county and not segment and result['disposition'].startswith('AUTHORITY_EXACT'),
            coverage_note=('Jackson and Kansas City are separately reported authority segments; do not add or label full Jackson County without historical boundary evidence.' if segment else
                'District totals cannot establish county returns.' if st == 'AK' else
                'Numeric agreement cannot establish this special unit’s meaning.' if not is_county else
                'Comparison alias is not geographic publication authorization.' if st == 'MN' and row['county'] == 'SAINT LOUIS' else ''))
        comparisons.append(result)
        inventory[st].append(result)
        if primary and result['official_difference'] not in (None,0):
            difference={**result,
                'vote_adjustment': primary['totals'][row['candidate']]-row['votes'],
                'publication_blocker': 'Source observations are immutable. This is a verification proposal, not an executable canonical publication; county-source ingestion and separate publication authorization are required.'}
            differences.append(difference)
            if result['disposition'].startswith('AUTHORITY_CORRECTION'):
                corrections.append(difference)
    table(output/'observation-comparisons.csv', comparisons)
    write(output/'official-unit-components.json', official)
    write(output/'census-reference.json', reference)
    table(output/'correction-preview.csv', corrections)
    table(output/'authority-differences.csv', differences)
    table(output/'discrepancy-566-dispositions.csv', [r for r in comparisons if r['reference_difference'] not in (None,0)])
    table(output/'unresolved-observations.csv',[r for r in comparisons if not r['disposition'].startswith('AUTHORITY_')])
    unit_inventory=defaultdict(list)
    for row in comparisons:
        unit_inventory[(row['state'],row['source_unit'],row['source_fips'])].append(row)
    unit_rows=[]
    for (st,name,fips),values in sorted(unit_inventory.items(),key=lambda p:repr(p[0])):
        unit_rows.append(dict(state=st,source_unit=name,source_fips=fips,
            reporting_level=values[0]['reporting_level'],observation_count=len(values),
            observed_votes=sum(r['observed_votes'] for r in values),
            stored_accepted_rows=sum(r['canonical_stored_accepted'] for r in values),
            preview_accepted_rows=sum(r['canonical_preview_accepted'] for r in values),
            dispositions=dict(Counter(r['disposition'] for r in values)),
            all_candidate_values_verified=all(r['county_candidate_value_verified'] for r in values),
            source_lineage=[r['observation_id'] for r in values],
            county_completeness_claim=False if values[0]['reporting_level']!='county' else None))
    table(output/'reporting-unit-coverage.csv',unit_rows)
    originals = {r['observation_id']: r for r in comparisons}
    dispositions = [{**h, **originals[h['observation_id']]} for h in handoff]
    table(output/'original-144-dispositions.csv', dispositions)
    state_comparisons = []
    for st, source in sorted(inventory.items()):
        state_fips=next((r['source_fips'][:2] for r in source if r['source_fips']),None)
        expected_counties={f for f,r in reference.items() if f[:2]==state_fips and not f.endswith('000')
                           and r['cells']['BARACK OBAMA']['votes'] is not None}
        complete=complete_county_coverage(source,expected_counties,fec[st]['totals'])
        for b in BUCKETS:
            candidates = [x for x in source if x['candidate_bucket'] == b]
            county = [x for x in candidates if x['reporting_level'] == 'county']
            available = [v for f, v in reference.items() if f[:2] == state_fips
                         and not f.endswith('000') and v['cells'][b]['votes'] is not None]
            # State matching is bookkeeping, never evidence assigning residual votes.
            primary = official.get(st)
            official_sum = sum(r['totals'][b] for r in primary) if primary and st!='MO' else None
            ref_sum = sum(r['cells'][b]['votes'] for r in available) if available else None
            state_comparisons.append(dict(state=st,candidate_bucket=b,
                fec_votes=fec[st]['totals'][b], all_source_votes=sum(x['observed_votes'] for x in candidates),
                stored_county_votes=sum(x['observed_votes'] for x in candidates if x['canonical_stored_accepted']),
                preview_county_votes=sum(x['observed_votes'] for x in candidates if x['canonical_preview_accepted']),
                independent_reference_county_votes=ref_sum if st!='MO' else None,
                reference_reporting_unit_bookkeeping_votes=ref_sum,
                official_reporting_unit_votes=official_sum,
                official_aggregation_disposition='WITHHELD_UNVERIFIED_SEGMENT_OVERLAP' if st=='MO' else 'REPORTED_UNITS_ONLY',
                reference_minus_fec=None if ref_sum is None or st=='MO' else ref_sum-fec[st]['totals'][b],
                official_minus_fec=None if official_sum is None else official_sum-fec[st]['totals'][b],
                official_reporting_unit_count=len(primary) if primary else 0,
                county_source_observations=len(county),
                authority_exact=sum(x['disposition'].startswith('AUTHORITY_EXACT') for x in candidates),
                authority_differences=sum(x['official_difference'] not in (None,0) for x in candidates),
                reference_differences=sum(x['reference_difference'] not in (None,0) for x in candidates),
                unresolved_authority=sum(not x['official_source'] for x in candidates),
                excluded_rows=sum(not x['canonical_stored_accepted'] for x in candidates),
                excluded_votes=sum(x['observed_votes'] for x in candidates if not x['canonical_stored_accepted']),
                full_county_coverage_verified=complete,
                fec_source=fec[st]['source_url'],
                note='Residuals are unallocated; overlapping authority segments, missing county evidence and discrepant sources are not proof of a full county/state rollup.'))
    table(output/'state-coverage.csv', state_comparisons)
    census_internal = [{k: r[k] for k in ('fips','name','component_difference')}
                       for r in reference.values() if r['component_difference'] not in (None,0)]
    write(output/'reference-internal-differences.json', census_internal)
    hierarchy=[]
    for fips,parent in sorted(reference.items()):
        if not fips.endswith('000'):
            continue
        children=[r for f,r in reference.items() if (f.endswith('000') and f!='00000')]
        level='US_TO_STATES'
        if fips!='00000':
            children=[r for f,r in reference.items() if f[:2]==fips[:2] and not f.endswith('000')]
            level='STATE_TO_COUNTY_LABELS'
        for b in ('total',*BUCKETS):
            eligible=[r for r in children if r['cells'][b]['flag']!=5]
            values=[r['cells'][b]['votes'] for r in eligible if r['cells'][b]['votes'] is not None]
            parent_votes=parent['cells'][b]['votes']
            child_votes=sum(values) if values else None
            hierarchy.append(dict(fips=fips,name=parent['name'],level=level,bucket=b,
                reported_votes=parent_votes,reported_child_votes=child_votes,
                available_child_units=len(values),missing_child_units=len(eligible)-len(values),
                bookkeeping_difference=None if child_votes is None or parent_votes is None else child_votes-parent_votes,
                parent_cell=parent['cells'][b],
                note='Reference internal accounting only. Footnotes, missing values and unverified authority-segment coverage prohibit inferring complete county returns.'))
    table(output/'reference-hierarchy.csv',hierarchy)
    unresolved_states=[]
    for st,values in sorted(inventory.items()):
        missing=[r for r in values if r['disposition']=='REFERENCE_DIFFERENCE_AUTHORITY_UNAVAILABLE']
        if missing:
            unresolved_states.append(dict(state=st,county_candidate_discrepancies=len(missing),
                affected_reporting_units=len({r['source_unit'] for r in missing}),
                source_votes=sum(r['observed_votes'] for r in missing),
                reference_votes=sum(r['reference_votes'] for r in missing),
                signed_reference_adjustment=sum(r['reference_votes']-r['observed_votes'] for r in missing),
                owner=f'{st} election authority records custodian; DATA-005 maintainer',
                required_evidence='Original certified 2008 county presidential candidate and write-in totals with comparable reporting coverage; no allocation from FEC state totals.'))
    table(output/'authority-evidence-requests.csv',unresolved_states)
    primary_ids={r['evidence_id'] for rows in official.values() for r in rows}
    primary_ids|={'mt-writeins'}
    control_ids={'il-state-control','pa-2008-metadata','pa-2008-state','pa-followup-1',
                 'mn-2008-county-table','mn-2008-layout','census-cousub2000','census-cousub2010'}
    reference_ids={'census-ele','census-metadata','census-source','census-flags','census-footnotes'}
    requests = [{**r, 'archive_location':str(archive.paths[k]) if k in archive.paths else r.get('archive_location'),
                 'comparison_usage':'PRIMARY_RESULT' if k in primary_ids else 'CONTROL_OR_CROSSWALK' if k in control_ids else
                     'INDEPENDENT_PUBLISHED_REFERENCE' if k in reference_ids else 'FEC_STATE_AUTHORITY' if k=='fec-2008-president' else
                     'ALTERNATIVE_PARTIAL_EXTRACT' if k=='pa-followup-2' else 'RESEARCH_ONLY_NOT_NUMERIC_VERIFICATION'}
                for k,r in sorted({**records,**archive.records}.items())]
    write(output/'source-inventory.json', requests)
    write(output/'correction-manifest.json', dict(format='data005-county-correction-preview-v1',
        source_release=snapshot['source'], current_county_batch=snapshot['stored_batch'],
        current_canonical_preview=snapshot['preview'], publication_authorized=False,
        original_observations_unchanged=True, changes=corrections,
        sha256=digest(corrections), review_issues=[r for r in differences if not r['disposition'].startswith('AUTHORITY_CORRECTION')],
        current_canonical_preview_after_value_proposals=dict(accepted_rows=snapshot['preview']['accepted_rows'],
            excluded_rows=snapshot['preview']['excluded_rows'],status='PARTIAL',
            canonical_votes=snapshot['preview']['canonical_votes']+sum(r['vote_adjustment'] for r in corrections if r['canonical_preview_accepted']),
            executable_publication=False,
            note='Arithmetic scenario only. Existing canonical ingestion has not been changed to accept source replacements.')))
    summary = dict(format='data005-county-verification-v1', generated_at=datetime.now(timezone.utc).isoformat(),
        baseline=snapshot['stored_batch'], source=snapshot['source'],
        observation_count=len(comparisons), original_exclusions=len(dispositions),
        source_reporting_units=len(unit_rows),
        county_labelled_observations=sum(x['source_fips'] in reference and x['state']!='AK' for x in comparisons),
        county_reporting_observations=sum(x['reporting_level']=='county' for x in comparisons),
        reference_comparable=sum(x['reference_votes'] is not None for x in comparisons),
        reference_exact=sum(x['reference_difference']==0 for x in comparisons),
        reference_differences=sum(x['reference_difference'] not in (None,0) for x in comparisons),
        official_comparable=sum(x['official_votes'] is not None for x in comparisons),
        official_exact=sum(x['official_difference']==0 for x in comparisons),
        official_differences=len(differences),
        evidenced_value_corrections=len(corrections),
        proposed_vote_adjustment=sum(r['vote_adjustment'] for r in corrections),
        dispositions=dict(Counter(x['disposition'] for x in comparisons)),
        independently_compiled_reference_source='Census USA Counties 2011; CQ Press/SAGE; not an election authority or MEDSL-derived verification',
        reference_items=descriptions, source_count=len(requests),
        election_authority_states=sorted(official),
        authority_missing_discrepancies=sum(r['county_candidate_discrepancies'] for r in unresolved_states),
        authority_missing_discrepancy_states=[r['state'] for r in unresolved_states],
        stored_full_county_coverage_verified_states=sorted({r['state'] for r in state_comparisons if r['full_county_coverage_verified']}),
        county_complete=False, county_derived_state_rollup_complete=False, national_county_complete=False,
        publication_status='PREVIEW_ONLY', database_mutations=0,
        observation_comparison_sha256=digest(comparisons), correction_sha256=digest(corrections))
    write(output/'summary.json', summary)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--archives', type=Path, nargs='+', required=True)
    p.add_argument('--prior-evidence', type=Path, required=True)
    p.add_argument('--mn-evidence', type=Path, required=True)
    p.add_argument('--mn-lookup', type=Path)
    p.add_argument('--handoff', type=Path, default=Path('data/geo001/data005-144-handoff.csv'))
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--require-complete',action='store_true',help='Exit 2 if full county verification remains incomplete')
    args = p.parse_args()
    with args.handoff.open(encoding='utf-8-sig', newline='') as stream:
        handoff = list(csv.DictReader(stream))
    summary = verify(json.loads(args.snapshot.read_text(encoding='utf-8')), handoff,
        Archive(args.archives), args.prior_evidence, args.mn_evidence, args.mn_lookup, args.output_dir)
    print(json.dumps(summary, indent=2))
    if args.require_complete and not summary['national_county_complete']:
        p.exit(2,'County verification is PARTIAL; see the discrepancy, source and coverage ledgers.\n')


if __name__ == '__main__':
    main()
