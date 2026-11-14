"""Build the GEO-001 review ledger and DATA-005/GEO-002 handoffs.

Assessment policy is explicit below. It does not approve evidence or publish.
Requires both the original and corrected independent verification exports.
"""
from collections import Counter
import argparse
import json
from pathlib import Path
import re

import polars as pl
from sqlalchemy import text

from app.database import engine
from app.services.geo001_audit import dump, ROOT, stable_sha

CODE_URL = 'https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt'
CHANGE_URL = 'https://www.census.gov/programs-surveys/geography/technical-documentation/county-changes.2010.html'
NM_URL = 'https://www.census.gov/programs-surveys/geography/technical-documentation/county-changes.2000.html'
CT_URL = 'https://www.census.gov/programs-surveys/geography/technical-documentation/county-changes.2020.html'
CITY_URL = 'https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2025/TGRSHP2025_TechDoc_Ch4.pdf'
KC_URL = 'https://kceb.org/absentee/requirements/'


def frame(path):
    return pl.read_csv(path, infer_schema_length=0).with_columns(
        pl.col('year').cast(pl.Int32),pl.col('votes').cast(pl.Int64),
        (pl.col('changed') == 'true'),(pl.col('historical_comparison') == 'true'),
        (pl.col('cross_release_proposal') == 'true'))


def assessment(row):
    st,y,label,code,method = (row[k] for k in ('state','year','raw_label','normalized_code','proposed_method'))
    base = dict(independent_assessment='SUPPORTED', evidence_dates=f'election year {y}; product coverage is not legal validity',
                research_remaining='', owner='GEO-002', county_eligibility='NO_NEW_COUNTY_ELIGIBILITY',
                overlap_assessment='Not established by geographic matching', publication_disposition='REVIEW_SUPPORTED_PROPOSAL')
    def result(group,rationale,urls,**kwargs):
        return {**base,'review_group':group,'rationale':rationale,'evidence_citations':urls,**kwargs}
    if st == 'MO' and code == '29095':
        return result('MO_JACKSON_PARTIAL_REPORTING',
            'County identity agrees with code/name, but the raw Jackson reporting segment must be checked against the separate Kansas City authority. County matching alone does not certify a complete county total.',
            'https://www.sos.mo.gov/cmsimages/BlueBook/2009-2010/7_Elec.pdf;https://jcebmo.org/election-information/jurisdiction/',
            independent_assessment='REQUIRES_RESEARCH',owner='DATA-005;DATA-027;DATA-028',
            research_remaining='Verify each year/candidate/mode against official Jackson and KCEB segments; do not allocate or merge automatically.',
            overlap_assessment='Official 2008 authority rows are separate; determine whether MEDSL Jackson is the segment or whole-county aggregation.',
            publication_disposition='PRESERVE_PUBLISHED_COUNTY_MATCH_FLAG_COVERAGE')
    if st == 'NM' and row['historical_comparison']:
        return result('NM_UNSUPPORTED_HISTORICAL_COMPARISON',
            'Exact intact 35013 county match is supported. The historical flag compares DONA ANA with damaged DO A ANA in the newest reference and cannot independently establish a geographic change or legal date.',
            NM_URL+';source-integrity.json;full-before.json#nm_identities',
            independent_assessment='UNSUPPORTED',owner='GEO-002',
            research_remaining='Review a corrected, separately released reference and explicit identity continuity; preserve both existing UUIDs and released labels.',
            publication_disposition='HOLD_HISTORICAL_INFERENCE_COUNTY_IDENTITY_SUPPORTED')
    if st == 'AK':
        number = int(re.search(r'\d+$',label).group())
        docs = {2000:'ak-2000-hd2',2004:'ak-2004-hd1',2008:'ak-2008-hd8',2012:'ak-2012-hd1',
                2016:'ak-2016-hd1',2020:'ak-2020-hd1',2024:'ak-2024-hd1-corrected'}
        if number <= 40:
            return result(f'AK_{y}_HOUSE_REPORTING_DISTRICTS',
                'The same-year official district/precinct report and MEDSL labels establish state House reporting districts. The number is scoped to this election, not a borough, census area or US House district. No boundary identity or county allocation is established.',
                f'research/{docs[y]}.pdf'+('' if y in {2000,2008} else f';research/ak-{y}-index.html'),
                owner='GEO-002;QA-001',
                research_remaining='2004 raw district candidate sum is 488693 versus official statewide 312598; verify hierarchy/subtotals and source convention. Other years also require compatible candidate/mode totals, not allocation. 2008 is handed to DATA-005.',
                overlap_assessment='District and precinct totals are hierarchical; do not add parent totals to their precincts.')
        assert number == 99
        if y in {2016,2024}:
            return result(f'AK_{y}_99_DOCUMENTED',
                'Year-specific official HD99 report names federal overseas absentee. MEDSL candidate grouping sums to the official 342 (2016) or 401 first-choice votes (2024). Retaining PENDING_REVIEW is conservative; classification-only change can be separately proposed by GEO-002.',
                f'research/ak-{y}-hd99.pdf',research_remaining='Attach this year-specific evidence to a new reviewed classification proposal; never allocate to counties.',
                publication_disposition='KEEP_PENDING_UNTIL_SEPARATE_CLASSIFICATION_REVIEW',
                overlap_assessment='Official HD99 is a separate reporting line; never add it again to an inclusive statewide total.')
        return result(f'AK_{y}_99_RESEARCH',
            'Pending county link is correct. No year-specific meaning was established for early zero-valued rows; 2020 official HD99 is federal overseas absentee but MEDSL sums to 433 against official 438.',
            f'research/ak-{y}-hd99.pdf' if y == 2020 else f'research/retrievals.json#ak-{y}-hd99-attempt',
            independent_assessment='REQUIRES_RESEARCH',owner='GEO-002'+(';DATA-027' if y==2020 else ';DATA-005' if y==2008 else ''),
            research_remaining='2020: reconcile the five-vote gap and modes without filling votes.' if y==2020 else 'Obtain year-specific MEDSL/source documentation: distinguish padded zero rows from actual overseas reporting; another year is insufficient.',
            publication_disposition='KEEP_PENDING_NO_REMAP')
    if st == 'VA' and code == '51515' and y == 2016:
        return result('BEDFORD_2016_DOWNGRADE',
            'Retirement effective 2013-07-01 predates the 2016 election although georef12 still lists 51515. All three source rows are zero-vote legacy identifiers and are in the active 2016 canonical batch. A pending downgrade is supported; neither a successor mapping nor a particular MEDSL padding convention is proven.',
            CHANGE_URL+';full-before.json#bedford_source;source-integrity.json',
            evidence_dates='Bedford independent city retired 2013-07-01; election 2016-11-08',
            research_remaining='GEO-002: obtain MEDSL convention for retained zero legacy rows; separately authorize downgrade. Existing canonical rows/pointer must remain until an explicit canonical workflow.',
            publication_disposition='SUPPORTED_DOWNGRADE_REQUIRES_EXPLICIT_GEO002_AUTHORIZATION')
    if method == 'CENSUS_INDEPENDENT_CITY':
        assert row['old_reference_id'] == row['proposed_reference_id'] and row['old_jurisdiction_id'] == row['proposed_jurisdiction_id']
        return result('TYPED_INDEPENDENT_CITY_METHOD',
            'Method-only change: same reference, same jurisdiction, same matched status. Independent code/entity-type and raw-name comparison supports Census independent-city suffix handling. Historical status is retained as reference comparison, not assigned legal dates.',
            CODE_URL+';'+CITY_URL+';source-integrity.json',county_eligibility='ALREADY_MATCHED_NO_ELIGIBILITY_CHANGE')
    if st == 'VA':
        assert code in {'51036','51095'}
        return result('VIRGINIA_COUNTY_LABEL',
            'Charles City and James City are county names. Exact state and county GEOID agree with archived Census County labels; retaining CITY restores the valid match without changing identities.',
            CODE_URL+';source-integrity.json',county_eligibility='PRIMARY_RELEASE_COUNTY_MATCH_AFTER_GEOGRAPHY_PUBLICATION')
    if method == 'CENSUS_2000_GAZETTEER_SUPPLEMENT':
        return result('CENSUS_2000_SUPPLEMENT',
            'Independent archived fixed-width Census 2000 records identify 11001 District of Columbia and 12086 Miami-Dade; primary CBP lacks county entries. Supplemental release checksum, exact labels/codes and existing identities verify; no reference record is overwritten.',
            'source-integrity.json;https://www.census.gov/programs-surveys/geography/technical-documentation/records-layout/gaz-record-layouts.2000.html',
            evidence_dates='Census 2000 snapshot as of 2000-01-01; not an inferred legal lifetime',
            county_eligibility='BLOCKED_CURRENT_DATA003_CROSS_RELEASE_ELIGIBILITY')
    if method == 'CT_LEGACY_COUNTY':
        return result('CT_2024_LEGACY_COUNTY_REPORTING',
            'All 39 MEDSL observations use the eight legacy county labels/codes and agree with their archived references. New planning-region codes are distinct. The proposed match identifies a legacy reporting area, not a 2024 legal county equivalent or a planning-region conversion.',
            CT_URL+';research/ct-2024-contest.html;research/ct-2024-sov.pdf;source-integrity.json',
            independent_assessment='REQUIRES_RESEARCH',
            evidence_dates='Planning regions recognized effective 2022-06-06; MEDSL reporting year 2024; legacy territory membership unverified',
            county_eligibility='BLOCKED_CURRENT_DATA003_CROSS_RELEASE_ELIGIBILITY',
            research_remaining='Verify MEDSL town-to-legacy-county membership and election-round/mode aggregation against official 2024 town returns before endorsing a historical reporting-area publication.',
            publication_disposition='HOLD_LEGACY_AREA_MATCH_PENDING_SOURCE_COVERAGE')
    if st == 'MO' and label == 'KANSAS CITY':
        if row['proposed_status'] == 'INVALID':
            assert row['raw_code'] == '36000'
            return result('MO_2024_INVALID_CODE',
                'Missouri state 29 conflicts with raw/normalized 36000 prefix 36. A Kansas City label cannot authorize replacing the code with a place or county identifier. INVALID remains correct.',
                'source-integrity.json;research/mo-2008-manual.pdf',independent_assessment='REQUIRES_RESEARCH',
                owner='DATA-028;GEO-002',research_remaining='Obtain a corrected source release or reviewed source convention for each of the four observations.',publication_disposition='KEEP_INVALID_NO_CODE_SUBSTITUTION')
        return result('MO_KANSAS_CITY_REPORTING_UNIT',
            'Non-county classification is supported. The saved CENSUS_PLACE_GEOID/census_place typing was unsupported for vote coverage: an election authority is not the entire Census place. step6.2.1 uses a source/year reporting namespace and a null county target.',
            KC_URL+';https://jcebmo.org/election-information/jurisdiction/;research/mo-2008-manual.pdf',
            research_remaining='For each election/candidate/mode verify Jackson and Kansas City authority segments before county totals; no allocation performed.',
            overlap_assessment='Official 2008 rows distinguish Jackson and Kansas City; MEDSL segment compatibility is separately flagged in the Jackson ledger.')
    if st == 'NM':
        return result('NM_REFERENCE_CORRUPTION',
            'All 21 conflict rows must remain ambiguous. georef17 contains byte B1 (not UTF-8, and CP1252 gives ± rather than ñ); utf8-lossy replaced it. georef2022 contains an actual ASCII space. Two existing UUIDs result from intact versus damaged normalized labels. This is not a demonstrated legitimate source alias.',
            NM_URL+';'+CODE_URL+';source-integrity.json;full-before.json#nm_identities',
            independent_assessment='REQUIRES_RESEARCH',research_remaining='Acquire a separately versioned corrected reference and review existing identity continuity; do not alter released labels or approve an alias to hide damage.',publication_disposition='KEEP_AMBIGUOUS_REFERENCE_AND_IDENTITY_REVIEW')
    if st == 'SD':
        return result('SD_2016_NEW_CODE' if y==2016 else 'SD_2024_RETIRED_CODE',
            'Census dates the 46113 Shannon to 46102 Oglala Lakota name/code change to 2015-05-01. 2016 new code is absent georef12; 2024 retains the retired code. Current unresolved/pending dispositions prevent unapproved continuity or source-code substitution.',
            CHANGE_URL+';source-integrity.json',evidence_dates='Name/code change effective 2015-05-01, independent of 2012-2016 product coverage',
            independent_assessment='REQUIRES_RESEARCH',research_remaining='GEO-002 must review the proposed change evidence and identities for 2016; DATA-028 must establish 2024 source convention. No automatic recode.',owner='GEO-002'+(';DATA-028' if y==2024 else ''),publication_disposition='KEEP_UNRESOLVED_OR_PENDING_NO_AUTOMATIC_RECODE')
    if st in {'MN','LA','IL','MO'}:
        return result('ALIAS_CANDIDATE_'+st,
            'Same-state code identifies a candidate, but SAINT/ST, spacing, and name-correction evidence do not themselves approve a source alias. Retain AMBIGUOUS and existing identities.',
            CODE_URL+(';' + CHANGE_URL if st=='LA' else '')+';source-integrity.json',
            independent_assessment='REQUIRES_RESEARCH',research_remaining='GEO-002: compare contemporaneous source/reference spelling and exact target UUID; approve only a source/year-scoped alias with an accountable actor.',
            evidence_dates='LaSalle spelling correction reported as of 2011-01-01, not a legal boundary event' if st=='LA' else f'Contemporaneous source year {y}; current code list corroborates candidate only',
            county_eligibility='ALIAS_CANDIDATE_ONLY_NOT_ELIGIBLE_UNTIL_APPROVED_AND_PUBLISHED',publication_disposition='KEEP_AMBIGUOUS_PENDING_ALIAS_REVIEW')
    assert method in {'SOURCE_UOCAVA','SOURCE_FEDERAL_PRECINCT','SOURCE_STATEWIDE_WRITEIN'},row
    citations = {'CT':'research/ct-2008-contest.html;research/ct-2008-sov.pdf;research/ct-2024-sov.pdf',
                 'ME':'research/me-2008-president.pdf', 'RI':'research/ri-2008-official.html;research/ri-2008-description.pdf'}
    return result(st+'_SPECIAL_REPORTING_CATEGORY',
        'The literal MEDSL source category is not a county; keeping a null county link is supported. The category label alone does not prove additive, exclusive or comprehensive votes in any year.',
        citations[st]+';source-integrity.json',
        research_remaining='Verify year-specific source category totals and whether county/town returns already include them. The 2008 Maine tabulation supplies county/office totals but no explicit UOCAVA definition; CT 2008 PDF is scanned. RI warns that town/state totals include limited precincts.',
        overlap_assessment='Potential overlap: RI official town/state results include limited precincts; do not equate this with MEDSL federal precinct without source reconciliation.' if st=='RI' else 'Unverified; classification does not authorize adding the category to county or state totals.')


def main(root=ROOT):
    old = frame(root/'all-observation-checks.csv')
    current = frame(root/'corrected'/'all-observation-checks.csv')
    assert old.height == current.height == 94151
    assert old['observation_id'].n_unique() == current['observation_id'].n_unique() == 94151
    fields = ['proposed_status','proposed_method','proposed_reference_id','proposed_jurisdiction_id']
    joined = old.select(['observation_id',*fields]).join(current.select(['observation_id',*fields]),on='observation_id',suffix='_current')
    assert joined.height==94151
    changed_fields = {k:joined.filter(~pl.col(k).eq_missing(pl.col(k+'_current'))).height for k in fields}
    assert changed_fields == {'proposed_status':0,'proposed_method':21,'proposed_reference_id':0,'proposed_jurisdiction_id':0},changed_fields
    # Independently scan documentary retirements beyond the resolver's two
    # hard-coded guards; these event dates are not CBP coverage endpoints.
    retirements = [('VA','51515',2013,'2013-07-01',CHANGE_URL),
                   ('VA','51560',2001,'2001-07-01',NM_URL),
                   ('SD','46113',2015,'2015-05-01',CHANGE_URL),
                   ('AK','02201',2008,'2008-05-19',NM_URL),
                   ('AK','02232',2007,'2007-06-20',NM_URL),
                   ('AK','02280',2008,'2008-06-01',NM_URL),
                   ('AK','02261',2019,'2019-01-02',CHANGE_URL),
                   ('AK','02270',2015,'2015-07-01',CHANGE_URL)]
    scans=[]
    for state,code,year,date,url in retirements:
        affected=old.filter((pl.col('state')==state)&(pl.col('normalized_code')==code)&(pl.col('year')>=year))
        unsafe=affected.filter(pl.col('old_status').is_in(['RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS']))
        scans.append({'state':state,'code':code,'effective_date':date,'citation':url,
                      'post_event_observations':affected.height,'unsafe_published_observation_ids':unsafe['observation_id'].to_list()})
    assert sum(len(r['unsafe_published_observation_ids']) for r in scans)==3
    dump(root/'documentary-retirement-scan.json',scans)
    original_changes = set(old.filter(pl.col('changed'))['observation_id'])
    old_exceptions = set(old.filter(~pl.col('old_status').is_in(['RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS']))['observation_id'])
    rows = current.filter(pl.col('changed') | ~pl.col('old_status').is_in(['RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS'])
         | ((pl.col('state')=='NM') & pl.col('historical_comparison'))
         | ((pl.col('state')=='MO') & (pl.col('normalized_code')=='29095'))).to_dicts()
    old_index = {r['observation_id']:r for r in old.filter(pl.col('observation_id').is_in([r['observation_id'] for r in rows])).to_dicts()}
    with engine.connect() as c,c.begin():
        c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        canonical = {str(r['observation_id']):dict(r) for r in c.execute(text('''SELECT v.id,v.observation_id,
            v.batch_id,v.geographic_resolution_id,v.votes FROM canonical_vote_return v
            JOIN canonical_publication p ON p.batch_id=v.batch_id''')).mappings()}
        dump(root/'pending-evidence-inventory.json', {table:[dict(r) for r in c.execute(text('SELECT * FROM '+table)).mappings()]
             for table in ('geographic_alias','geographic_change','geographic_identity_link')})
    reports = [json.loads((root/'corrected'/'reproduced'/f'compare-{v}.json').read_text()) for v in (2000,2004,2012,2020,2024)]
    digests = []
    for directory in ('reproduced','corrected/reproduced'):
        for v in (2000,2004,2012,2020,2024):
            report = json.loads((root/directory/f'compare-{v}.json').read_text())
            payload = {k:report[k] for k in ('reference_release_id','ruleset_version','context_sha256')}
            payload['differences'] = report['differences']
            checks = {'directory':directory,'vintage':v,
                      'context_sha256_valid':stable_sha(report['context_manifest'])==report['context_sha256'],
                      'proposal_sha256_valid':stable_sha(payload)==report['proposal_sha256']}
            assert checks['context_sha256_valid'] and checks['proposal_sha256_valid']
            digests.append(checks)
    dump(root/'independent-digest-checks.json',digests)
    by_year = {y:r for r in reports for y in r['election_years']}
    ledger = []
    for row in rows:
        oid = row['observation_id']
        prev = old_index[oid]
        note = assessment(row)
        if row['year'] == 2008 and 'DATA-005' not in note['owner']:
            note['owner'] += ';DATA-005'
        pub = canonical.get(oid,{})
        row.update(note)
        row.update(saved_proposed_status=prev['proposed_status'],saved_proposed_method=prev['proposed_method'],
            original_changed_decision=oid in original_changes,original_exception=oid in old_exceptions,
            saved_proposal_assessment='UNSUPPORTED' if prev['proposed_method']=='CENSUS_PLACE_GEOID' else note['independent_assessment'],
            applicable_reference_product_years=json.dumps(by_year[row['year']]['product_years']),
            context_sha256=by_year[row['year']]['context_sha256'],proposal_sha256=by_year[row['year']]['proposal_sha256'],
            proposed_decision_id=None,proposed_decision_key=by_year[row['year']]['context_sha256']+':'+oid,
            active_canonical_return_id=str(pub['id']) if pub else None,
            active_canonical_batch_id=str(pub['batch_id']) if pub else None,
            active_canonical_votes=pub.get('votes'), publication_authorized=False)
        ledger.append(row)
    f = pl.DataFrame(ledger,infer_schema_length=None).sort(['year','state','raw_label','source_row_number'])
    f.write_csv(root/'review-ledger.csv')
    groups = f.group_by(['review_group','independent_assessment','owner','rationale','research_remaining','evidence_citations',
                        'county_eligibility','publication_disposition']).agg(pl.len().alias('observations'),
                        pl.col('votes').sum().alias('raw_votes_not_additive'),
                        pl.col('original_changed_decision').sum().alias('original_changed_decisions'))
    groups.sort('review_group').write_csv(root/'review-groups.csv')
    handoff = f.filter((pl.col('year')==2008) & pl.col('original_exception'))
    partition = []
    for r in handoff.to_dicts():
        group = 'AK_DISTRICTS' if r['state']=='AK' else 'MN_ALIASES' if r['state']=='MN' else 'VA_COUNTY_LABELS' if r['state']=='VA' else 'SPECIAL_UNITS'
        partition.append({**r,'data005_partition':group})
    h = pl.DataFrame(partition,infer_schema_length=None)
    h.write_csv(root/'data005-144-handoff.csv')
    counts = dict(Counter(r['data005_partition'] for r in partition))
    assert counts == {'AK_DISTRICTS':123,'SPECIAL_UNITS':12,'MN_ALIASES':3,'VA_COUNTY_LABELS':6},counts
    assert len(original_changes)==1837 and len(old_exceptions)==1290
    ids = {r['observation_id'] for r in ledger}
    assert original_changes | old_exceptions <= ids
    assert f['observation_id'].n_unique() == f.height
    semantic_changes = []
    for r in current.to_dicts():
        if r['observation_id'] in old_index and r['proposed_method'] != old_index[r['observation_id']]['proposed_method']:
            semantic_changes.append(r['observation_id'])
    assert len(semantic_changes)==21
    current.filter((pl.col('state').is_in(['CT','ME','RI','MO','AK'])) &
       (pl.col('proposed_status').is_in(['NON_COUNTY_CLASSIFIED','PENDING_REVIEW','INVALID']))).group_by(
       ['year','state','raw_label','raw_code','candidate','mode','proposed_status','proposed_method']).agg(
       pl.len().alias('observations'),pl.col('votes').sum().alias('raw_votes')).sort(
       ['year','state','raw_label','candidate','mode']).write_csv(root/'reporting-unit-votes.csv')
    ak = current.filter(pl.col('state')=='AK').group_by(['year','raw_label']).agg(
        pl.len().alias('observations'),pl.col('votes').sum().alias('raw_votes'),pl.col('raw_code').unique().sort().str.join(';').alias('raw_codes'))
    ak.sort(['year','raw_label']).write_csv(root/'alaska-year-unit-inventory.csv')
    summary = {'ledger_observations':f.height,'unique_ledger_observations':f['observation_id'].n_unique(),
        'original_changes_covered':len(original_changes),'original_exceptions_covered':len(old_exceptions),
        'assessments':dict(Counter(r['independent_assessment'] for r in ledger)),
        'original_changed_assessments':dict(Counter(r['saved_proposal_assessment'] for r in ledger if r['original_changed_decision'])),
        'additional_nm_historical_flags':sum(r['review_group']=='NM_UNSUPPORTED_HISTORICAL_COMPARISON' for r in ledger),
        'additional_jackson_coverage_reviews':sum(r['review_group']=='MO_JACKSON_PARTIAL_REPORTING' for r in ledger),
        'corrected_method_differences_from_saved':len(semantic_changes),'corrected_field_differences_from_saved':changed_fields,
        'status_reference_or_identity_reassignments_from_saved':0,
        'data005_partition':counts,'data005_proposed_primary_county_matches':6,
        'data005_alias_candidates_not_yet_eligible':3,'data005_canonical_batch_unchanged':True,
        'publication_authorized':False}
    dump(root/'review-summary.json',summary)
    package = {'task':'GEO-002','publication_authorized':False,'ruleset':'step6.2.1',
        'saved_step620_digests_are_not_current_approval_targets':True,
        'requires_new_individual_review_of_unsupported_or_research_cases':True,
        'full_vintage_digests_cannot_be_taken_as_blanket_approval':True,
        'supported_proposals_ledger':'review-ledger.csv',
        'hold_dispositions':['NM reference/identity repair and historical inference','CT legacy territory coverage',
                             'source-scoped alias approvals','retired SD identifiers','invalid Missouri 36000',
                             'early Alaska District 99 and 2020 vote gap','Jackson county coverage'],
        'canonical_cross_release_matches_still_ineligible':47,
        'downgrade_observation_ids':[r['observation_id'] for r in ledger if r['review_group']=='BEDFORD_2016_DOWNGRADE'],
        'jurisdiction_reassignments':[],
        'corrected_preview_targets':[{k:r[k] for k in ('vintage','reference_release_id','context_sha256','proposal_sha256','changed_decisions','records_examined')} for r in reports],
        'next_workflow':'Review evidence with accountable actor; regenerate exact contexts/proposals after any changed evidence/rules; independently authorize downgrades; publish append-only only under GEO-002; verify idempotence. Canonical supersession requires separate authorization and eligibility work.'}
    dump(root/'geo002-review-package.json',package)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT)
    main(parser.parse_args().output_dir)
