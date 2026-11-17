"""Control accounting uses retained seats and source calls, never vote leaders."""
import pytest

from app.services.senate_control import senate_control, EXPECTED_STATES, DEMOCRATIC_SEATS_UP


def snapshot():
    return {'year': 2026, 'races': [{'id': f'SEN-{state}', 'state_code': state, 'status': 'counting',
        'candidates': [{'party': 'D', 'outcome': 'leads'}, {'party': 'R', 'outcome': ''}]} for state in sorted(EXPECTED_STATES)]}


def test_uncalled_or_missing_races_are_not_assigned_by_lead():
    for races in [snapshot()['races'], []]:
        c = senate_control({'year': 2026, 'races': races})
        assert c['democratic_aligned'] == 34 and c['totals']['D'] == 32 and c['totals']['R'] == 31
        assert c['unresolved'] == 35 and c['control'] is None
        assert sum(c['totals'].values()) + c['unresolved'] == 100


def test_calls_flips_independents_and_certification_are_distinct():
    s = snapshot()
    for race in s['races']:
        race['status'] = 'called'
        party = 'D' if race['state_code'] in DEMOCRATIC_SEATS_UP else 'R'
        race['candidates'] = [{'party': party, 'outcome': 'won'}]
    c = senate_control(s)
    assert c['totals'] == {'D': 45, 'R': 53, 'I': 2, 'O': 0}
    assert c['control'] == 'R' and c['net_change']['D'] == 0
    republicans = [r for r in s['races'] if r['state_code'] not in DEMOCRATIC_SEATS_UP]
    for race in republicans[:9]:
        race['candidates'][0]['party'] = 'D'
    c = senate_control(s)
    assert c['democratic_aligned'] == 56 and c['totals']['D'] == 54 and c['totals']['R'] == 44
    assert c['gains']['D'] == 9 and c['net_change']['D'] == 9 and c['net_change']['R'] == -9
    republicans[0]['candidates'][0]['party'] = 'I'
    republicans[0]['status'] = 'final'
    c = senate_control(s)
    assert c['democratic_aligned'] == 55 and c['other_unaligned'] == 1 and c['certified_contests'] == 1
    assert c['totals']['I'] == 3 and c['independent_democratic_caucus'] == 2
    assert sum(c['totals'].values()) + c['unresolved'] == 100


def test_invalid_year_duplicate_seats_and_missing_source_winner_fail():
    with pytest.raises(ValueError):
        senate_control({'year': 2024, 'races': []})
    s = snapshot()
    s['races'].append(s['races'][0])
    with pytest.raises(ValueError, match='duplicate'):
        senate_control(s)
    s = snapshot()
    s['races'][0]['status'] = 'called'
    with pytest.raises(ValueError, match='winner'):
        senate_control(s)
