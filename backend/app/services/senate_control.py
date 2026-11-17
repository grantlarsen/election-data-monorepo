"""Projected chamber composition from retained seats and explicit source outcomes.

2026 baseline: official Senate Class I/II/III rosters and Daily Press party
lineup. The two retained independents caucus with Democrats; newly elected
independents are never assigned a caucus automatically.
"""
from ingestion.current_senate import EXPECTED_STATES, YEAR

DEMOCRATIC_SEATS_UP = frozenset('CO DE GA IL MA MI MN NH NJ NM OR RI VA'.split())
RETAINED = {'D': 32, 'R': 31, 'I': 2, 'O': 0}
SOURCES = [
    'https://www.senate.gov/senators/Class_I.htm',
    'https://www.senate.gov/senators/Class_II.htm',
    'https://www.senate.gov/senators/Class_III.htm',
    'https://www.dailypress.senate.gov/on-the-floor/senate-facts/',
]


def senate_control(snapshot: dict) -> dict:
    if snapshot['year'] != YEAR:
        raise ValueError('Senate control baseline does not cover this election')
    called = dict.fromkeys(RETAINED, 0)
    gains, losses = dict.fromkeys(RETAINED, 0), dict.fromkeys(RETAINED, 0)
    seen = set()
    certified = 0
    for race in snapshot['races']:
        state = race['state_code']
        if state not in EXPECTED_STATES or state in seen or race['id'] != f'SEN-{state}':
            raise ValueError('Unknown or duplicate Senate control contest')
        seen.add(state)
        winners = [c for c in race['candidates'] if c['outcome'] == 'won']
        if race['status'] not in {'called', 'final'}:
            continue
        if len(winners) != 1:
            raise ValueError('Called Senate contest lacks one source winner')
        party = winners[0]['party'] if winners[0]['party'] in {'D', 'R', 'I'} else 'O'
        called[party] += 1
        certified += race['status'] == 'final'
        previous = 'D' if state in DEMOCRATIC_SEATS_UP else 'R'
        if party != previous:
            gains[party] += 1
            losses[previous] += 1
    totals = {party: RETAINED[party] + called[party] for party in RETAINED}
    unresolved = len(EXPECTED_STATES) - sum(called.values())
    aligned = totals['D'] + RETAINED['I']
    if sum(totals.values()) + unresolved != 100:
        raise ValueError('Senate control seats do not sum to 100')
    return {'total_seats': 100, 'majority_threshold': 51, 'seats_up': len(EXPECTED_STATES),
        'retained': RETAINED, 'called': called, 'totals': totals, 'unresolved': unresolved,
        'democratic_aligned': aligned, 'retained_democratic_aligned': RETAINED['D'] + RETAINED['I'],
        'independent_democratic_caucus': RETAINED['I'],
        'other_unaligned': called['I'] + totals['O'], 'certified_contests': certified,
        'control': 'D' if aligned >= 51 else 'R' if totals['R'] >= 51 else None,
        'gains': gains, 'net_change': {p: gains[p] - losses[p] for p in gains},
        'baseline_as_of': '2026-11-03', 'baseline_reviewed_at': '2026-11-17', 'sources': SOURCES}
