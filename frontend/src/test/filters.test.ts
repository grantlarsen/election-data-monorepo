import { describe, expect, it } from 'vitest';
import { apiQuery, filterSearch, validateSearch } from '../filters';
import { sourceUrl } from '../api';
import { contestId, jurisdictionId } from './fixtures';

describe('shared filter contract', () => {
  it('forwards the election calendar year and exact geography without leaking route context', () => {
    const params = new URLSearchParams({ year: '2008', office: 'President of the United States',
      stage: 'special_primary', state_code: 'NY', jurisdiction_id: jurisdictionId,
      reporting_level: 'congressional_district', offset: '25', contest_id: contestId, ignored: 'value' });
    const shared = new URLSearchParams(filterSearch(params).slice(1));
    expect(shared.get('year')).toBe('2008');
    expect(shared.has('offset')).toBe(false);
    expect(shared.has('contest_id')).toBe(false);
    const discovery = new URLSearchParams(apiQuery(params, 'contests'));
    expect(discovery.has('reporting_level')).toBe(false);
    expect(discovery.has('ignored')).toBe(false);
    const results = new URLSearchParams(apiQuery(params, 'results', contestId));
    expect(results.get('reporting_level')).toBe('congressional_district');
    expect(results.get('reporting_mode')).toBe('TOTAL');
    expect(results.get('jurisdiction_id')).toBe(jurisdictionId);
    expect(results.get('contest_id')).toBe(contestId);
  });

  it.each(['year=0', 'year=9999', 'year=2008.5', 'stage=invalid', 'state_code=ZZ',
    'jurisdiction_id=bad', 'contest_id=bad', 'reporting_level=state', 'offset=-1',
    'offset=9007199254740992', 'year=2008&year=2024'])('rejects unsupported deep-link filters: %s', query => {
    expect(validateSearch(new URLSearchParams(query))).toBeTruthy();
  });

  it('allows lowercase state codes, empty selections and distinct supported reporting levels', () => {
    expect(validateSearch(new URLSearchParams('state_code=ny&year=&reporting_level=precinct'))).toBeNull();
  });
});

describe('source links', () => {
  it.each(['javascript:alert(1)', 'data:text/html,test', 'file:///private', '/relative', 'not a url'])('does not link unsafe source URL %s', value => {
    expect(sourceUrl(value)).toBeUndefined();
  });
  it('retains official HTTPS download URLs', () => {
    expect(sourceUrl('https://example.org/source?id=1')).toBe('https://example.org/source?id=1');
  });
});
