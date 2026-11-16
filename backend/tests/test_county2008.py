"""County evidence: missing flags, reporting levels, grouped votes and overlap."""
from copy import deepcopy
import csv
from hashlib import sha256
import io
import json

import pytest

from ingestion.county2008 import (BUCKETS, ITEMS, assess, candidate_csv,
    census_cells, civera_csv, complete_county_coverage, explain_difference, montana,
    municipal_to_counties, observation_inventory, pennsylvania_counties, pdf_word_rows,
    stable_town_lookup, units, wyoming)
from app.services.county2008_verify import Archive


RECORD=dict(id='official',url='https://authority.example/2008',sha256='a'*64,
            retrieved_at='2026-11-15T00:00:00Z')


class Sheet:
    name='Sheet1'
    def __init__(self,rows):
        self.rows=rows
        self.nrows=len(rows)
    def row_values(self,n):
        return self.rows[n]


class Book:
    def __init__(self,rows):
        self.sheet=Sheet(rows)
    def sheets(self):
        return [self.sheet]


def reference_fixture():
    header=['Areaname','STCOU']
    values=['Missing, AK',2013]
    for item in ITEMS.values():
        header += [item+'F',item,item+'N1',item+'N2']
        values += [3,0,'','']
    meta=[[i,'Vote cast for president 2008','ABS','0',0,'CQ Press',''] for i in ITEMS.values()]
    return Book([header,values]),meta,[['CQ Press','SAGE','https://example']],[[3,'Not available'],[5,'Not applicable']],[['6529','ELE','State total includes overseas ballots.']]


def test_missing_census_values_are_not_zero_or_county_allocations():
    args=reference_fixture()
    cells,_=census_cells(*args,RECORD)
    assert cells['02013']['cells']['OTHER']['votes'] is None
    assert cells['02013']['cells']['OTHER']['flag']==3
    assert cells['02013']['component_difference'] is None
    assert 'R2C' in cells['02013']['cells']['OTHER']['source_locator']


@pytest.mark.parametrize('mutation', ['year','unit','source','duplicate_item','unknown_flag','fraction','missing_column'])
def test_reference_schema_and_semantics_are_required(mutation):
    book,meta,sources,flags,notes=reference_fixture()
    if mutation=='year':meta[0][1]='Vote cast for president 2012'
    elif mutation=='unit':meta[0][2]='PCT'
    elif mutation=='source':meta[0][5]='MEDSL'
    elif mutation=='duplicate_item':
        book.sheets=lambda:[book.sheet,book.sheet]
    elif mutation=='unknown_flag':book.sheet.rows[1][2]=9
    elif mutation=='fraction':book.sheet.rows[1][2]=0;book.sheet.rows[1][3]=0.5
    elif mutation=='missing_column':book.sheet.rows[0][3]='Not2008'
    with pytest.raises(ValueError):census_cells(book,meta,sources,flags,notes,RECORD)


def component(label,votes,unit='One',**kw):
    return dict(unit=unit,label=label,votes=votes,locator='table 1',**kw)


def test_other_remains_grouped_and_overlapping_candidate_layers_fail():
    rows=[component('Barack Obama',10),component('John McCain',9),component('All Others',3)]
    result=units(rows,RECORD,expected_count=1)[0]
    assert result['totals']['OTHER']==3 and result['components'][-1]['label']=='All Others'
    with pytest.raises(ValueError,match='Duplicate candidate'):
        units(rows+[rows[-1]],RECORD,expected_count=1)
    with pytest.raises(ValueError,match='Overlapping major'):
        units(rows+[component('Obama Combined Parties',10)],RECORD,expected_count=1)
    with pytest.raises(ValueError,match='Non-candidate'):
        units(rows+[component('Blank Votes',2)],RECORD,expected_count=1)


def test_accounting_relationship_does_not_assign_raw_other_to_candidates():
    official=units([component('Obama & Biden Electors',655),component('McCain & Palin Electors',794),
        component('Baldwin & Castle Electors',5),component('Barr & Root Electors',14),
        component('Nader & Gonzalez Electors',27)],RECORD,expected_count=1)[0]
    result=explain_difference(dict(state='SD',candidate='OTHER',votes=19),official)
    assert result['accounting_explanation']=='SHORTFALL_EQUALS_OFFICIAL_NADER_COUNTS'
    assert not result['raw_other_identity_inferred'] and not result['historical_extraction_cause_verified']


def test_town_export_does_not_add_state_precinct_or_ballot_totals():
    body=(',,'+'Barack Obama,John McCain,All Others,Total Votes Cast,Total Ballots Cast\n'
          ',,D,R,,,\nState,State,10,9,3,22,24\nCity/Town,One,10,9,3,22,24\nPrecinct,One A,10,9,3,22,24\n')
    result=civera_csv(body,RECORD,state='CT',count=1,level='City/Town')
    assert result[0]['totals']==dict(zip(BUCKETS,(10,9,3)))
    assert result[0]['reporting_level']=='municipality'
    with pytest.raises(ValueError,match='hierarchy'):
        civera_csv(body.replace('State,State,10','State,State,11'),RECORD,state='CT',count=1,level='City/Town')


def test_duplicate_control_rows_are_not_counted_as_counties_and_errors_are_explicit():
    body='County,John McCain,Barack Obama,All Others,Total Votes Cast\nTotals,9,10,3,22\nOne,9,10,3,22\nTotals,9,10,3,22\n'
    assert candidate_csv(body,RECORD,1)[0]['totals']['OTHER']==3
    with pytest.raises(ValueError,match='Duplicate candidate'):
        candidate_csv(body+'One,9,10,3,22\n',RECORD,1)
    bad=body.replace('One,9,10,3,22','One,9,10,3,21')
    with pytest.raises(ValueError,match='sum differs'):
        candidate_csv(bad,RECORD,1)
    result=candidate_csv(bad,RECORD,1,documented_ballot_errors=True)[0]
    assert result['internal_ballot_difference']['difference']==1
    assert assess(dict(candidate='OTHER',votes=3),dict(votes=3),result)['disposition']=='OFFICIAL_INTERNAL_CONFLICT'


def test_missing_authority_reference_conflicts_and_partial_candidate_groups():
    row=dict(candidate='OTHER',votes=8)
    assert assess(row,dict(votes=8),None)['disposition']=='REFERENCE_EXACT_AUTHORITY_UNAVAILABLE'
    assert assess(row,None,None)['disposition']=='EVIDENCE_UNAVAILABLE'
    official=dict(totals={'OTHER':5})
    assert assess(row,dict(votes=6),official)['disposition']=='OFFICIAL_REFERENCE_CONFLICT'
    supported=assess(row,dict(votes=6),official,state_control_matches=True)
    assert supported['disposition']=='AUTHORITY_CORRECTION_REFERENCE_DISAGREEMENT'
    assert supported['proposed_votes']==5
    assert not supported['publication_authorized']
    partial={**official,'incomplete_buckets':['OTHER']}
    result=assess(row,dict(votes=5),partial)
    assert result['disposition']=='INCOMPLETE_OFFICIAL_CANDIDATE_GROUPING'
    assert result['official_difference'] is None and result['proposed_votes']==8
    assert not result['publication_authorized']
    incompatible=assess(row,dict(votes=8),official,compatible=False)
    assert incompatible['official_difference'] is None and incompatible['reference_difference'] is None


def test_town_crosswalk_vintages_and_unmapped_or_duplicate_units_fail():
    old='CT0900100001'+f'{"One town":64}'+'0\n'
    new='USPS\tGEOID\tNAME\nCT\t0900100001\tOne town\n'
    lookup=stable_town_lookup(old,new,'CT')
    assert lookup=={'ONE':'09001'}
    with pytest.raises(ValueError,match='differ across'):
        stable_town_lookup(old,new.replace('09001','09003'),'CT')
    town=units([component('Barack Obama',10),component('John McCain',9),component('OTHER',3)],RECORD,expected_count=1)[0]
    result=municipal_to_counties([town],lookup,{'09001':'County'},RECORD)
    assert result[0]['comparison_crosswalk_only']
    assert not result[0]['intervening_legal_boundary_dates_verified']
    with pytest.raises(ValueError,match='coverage differs'):
        municipal_to_counties([town],{}, {'09001':'County'}, RECORD)


def test_wyoming_under_and_over_votes_do_not_enter_other():
    header=['county','John McCain','Barack Obama','Bob Barr','Chuck Baldwin','Ralph Nader','Write-Ins','Under Votes','Over Votes']
    rows=[['County'+chr(65+i),9,10,1,2,3,4,5,6] for i in range(23)]
    out=io.StringIO();writer=csv.writer(out);writer.writerow(header);writer.writerows(rows)
    writer.writerow(['Total',*[sum(r[i] for r in rows) for i in range(1,9)]])
    result=wyoming(out.getvalue(),RECORD)
    assert len(result)==23 and result[0]['totals']['OTHER']==10
    assert result[0]['components'][0]['under_votes']==5


def test_montana_legislative_columns_and_page_five_are_excluded():
    names=['County'+chr(65+i//26)+chr(65+i%26) for i in range(56)]
    out=io.StringIO();w=csv.writer(out);w.writerow(['county','Ron Paul','Barack Obama','Ralph Nader','Bob Barr','John McCain'])
    w.writerows([[n,0,10,0,0,9] for n in names]);w.writerow(['Total',0,560,0,0,504])
    controls={1:[0]*5,2:[0,3,143,12,0,0,0],3:[5,18,10,0],4:[0,1,1]}
    pages=[]
    for page,values in controls.items():
        lines=[]
        for i,name in enumerate(names):
            v=values if i==0 else [0]*len(values)
            if page==4:v=[*v,88,560,917]  # Legislative candidates on same page.
            lines.append(name+'  '+'  '.join(map(str,v)))
        lines.append('GRAND TOTAL  '+'  '.join(map(str,values+([0,0,0] if page==4 else []))))
        pages.append(dict(page=page,text='\n'.join(lines)))
    pages.append(dict(page=5,text='Legislative candidates only: 999999'))
    result=montana(out.getvalue(),pages,RECORD,{**RECORD,'id':'writeins'})
    assert sum(r['totals']['OTHER'] for r in result)==193
    assert result[0]['totals']['JOHN MCCAIN']==9


def test_pa_wrong_election_and_unsigned_raw_download_fail_closed(tmp_path):
    with pytest.raises(ValueError,match='Wrong Pennsylvania'):
        pennsylvania_counties('{}',json.dumps([dict(ElectionID=27,ElectionYear=2012)]),'{}',RECORD)
    raw=tmp_path/'source.raw';raw.write_bytes(b'original')
    record={**RECORD,'file':raw.name,'success':True,'sha256':sha256(b'original').hexdigest()}
    (tmp_path/'retrievals.json').write_text(json.dumps([record]))
    assert Archive([tmp_path]).raw('official')==b'original'
    raw.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Corrupt raw'):
        Archive([tmp_path])


def test_pdf_coordinates_preserve_adjacent_numeric_columns():
    import pymupdf
    doc=pymupdf.open();page=doc.new_page()
    page.insert_text((20,100),'County')
    page.insert_text((130,100),'422')
    page.insert_text((165,100),'252')
    rows=pdf_word_rows(doc.tobytes(),[1],100)
    assert rows[0]['name']=='County' and rows[0]['values']==['422','252']
    doc.close()


def test_observation_inventory_is_three_distinct_buckets_at_one_grain():
    rows=[dict(observation_id=str(i),state='VA',county='Charles City',county_fips='51036',
               candidate=b,votes=i,mode='TOTAL',raw_json={'year':'2008'}) for i,b in enumerate(BUCKETS)]
    assert len(observation_inventory(rows))==1
    with pytest.raises(ValueError,match='Duplicate observation'):
        observation_inventory(rows+[rows[0]])
    with pytest.raises(ValueError,match='Missing reporting-unit'):
        observation_inventory(rows[:-1])
    for key,value in [('mode','ABSENTEE'),('votes',-1),('candidate','RALPH NADER')]:
        changed=deepcopy(rows);changed[0][key]=value
        with pytest.raises(ValueError):observation_inventory(changed)


def test_exact_state_sums_do_not_prove_county_coverage_or_segment_nonoverlap():
    votes=dict(zip(BUCKETS,(10,9,3)))
    rows=[dict(reporting_level='county',disposition='AUTHORITY_EXACT',canonical_stored_accepted=True,
        geography_status='RESOLVED',source_fips='29095',candidate_bucket=b,observed_votes=v) for b,v in votes.items()]
    assert complete_county_coverage(rows,{'29095'},votes)
    assert not complete_county_coverage(rows,{'29095','29097'},votes)
    assert not complete_county_coverage(rows+rows,{'29095'},votes)
    segment=[{**r,'reporting_level':'election_authority_segment'} for r in rows]
    assert not complete_county_coverage(segment,{'29095'},votes)
    zero=[{**rows[0],'reporting_level':'unclassified_special_unit','observed_votes':0}]
    assert not complete_county_coverage(rows+zero,{'29095'},votes)
    assert not complete_county_coverage([{**r,'canonical_stored_accepted':False} for r in rows],{'29095'},votes)
