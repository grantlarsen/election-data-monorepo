"""Read-only report aggregation unit tests, without a database dependency."""
import pytest
from ingestion.geography.reconcile import combine_reports, VINTAGES, YEARS


def fixture_report(vintage, years, count):
    return {
        'vintage':vintage, 'reference_release_id':f'example-{vintage}',
        'election_years':list(years), 'status_counts':{'RESOLVED':count},
        'records_examined':count, 'dry_run':True,'published':False,
        'vote_totals_unchanged':True, 'differences':[],
        'coverage_by_year_state':[{'year':year,'state':'AL','status':'RESOLVED',
           'observations':count//len(years),'distinct_reporting_units':1} for year in years],
        'vote_totals_by_year_state':[],
        'proposal_sha256':'00'*32,
    }


def test_reconciliation_requires_complete_distinct_election_years():
    reports=[fixture_report(v,(y,),3) for v,y in zip(VINTAGES,(2000,2004,2012,2020,2024))]
    with pytest.raises(ValueError,match='incomplete'):
        combine_reports(reports,expected_observations=15)
    reports[1]['election_years']=[2004,2008]
    reports[1]['coverage_by_year_state'].append({'year':2008,'state':'AL','status':'RESOLVED',
        'observations':3,'distinct_reporting_units':1})
    reports[1]['status_counts']['RESOLVED']=6
    reports[1]['records_examined']=6
    reports[2]['election_years']=[2012,2016]
    reports[2]['coverage_by_year_state'].append({'year':2016,'state':'AL','status':'RESOLVED',
        'observations':3,'distinct_reporting_units':1})
    reports[2]['status_counts']['RESOLVED']=6
    reports[2]['records_examined']=6
    report=combine_reports(reports,expected_observations=21)
    assert report['complete'] and report['total_observations']==21
    assert report['county_match_rate']==1
    assert report['changed_decisions']==0
    assert report['publication_permitted'] is False


def test_reconciliation_fails_if_any_preview_published_or_misaligned():
    reports=[fixture_report(v,(y,),1) for v,y in zip(VINTAGES,(2000,2004,2012,2020,2024))]
    reports[0]['published']=True
    with pytest.raises(ValueError,match='read-only'):
        combine_reports(reports,expected_observations=5)
