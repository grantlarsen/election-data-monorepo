"""Independent 2008 evidence parsers and exact, coverage-aware comparisons.

No database mutation, geographic resolver, candidate identity matching or vote
allocation is performed here. OTHER is a source-level residual, never a person.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import re

from ingestion.medsl import STATE_NAMES

BUCKETS = ('BARACK OBAMA', 'JOHN MCCAIN', 'OTHER')
FORMAT = 'data005-reconciliation-v1'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def bucket(label):
    """Only the three observed MEDSL 2008 source categories are supported."""
    if label not in BUCKETS:
        raise ValueError(f'Unreviewed 2008 candidate category: {label!r}')
    return label


def number(value):
    if not re.fullmatch(r'\d+(?:,\d{3})*', value.strip()):
        raise ValueError(f'Invalid vote count: {value!r}')
    return int(value.replace(',', ''))


def evidence(directory):
    records = json.loads((directory / 'retrievals.json').read_text(encoding='utf-8'))
    result = {}
    for r in records:
        if r['id'] in result:
            raise ValueError('Duplicate evidence IDs')
        result[r['id']] = r
        if r.get('success'):
            if sha256((directory / r['file']).read_bytes()).hexdigest() != r['sha256']:
                raise ValueError(f"Corrupt raw evidence: {r['id']}")
            if r.get('text_file') and sha256((directory / r['text_file']).read_bytes()).hexdigest() != r['text_sha256']:
                raise ValueError(f"Corrupt extracted evidence: {r['id']}")
    return result


def provenance(record, locator):
    return {'evidence_id': record['id'], 'source_url': record['url'],
            'source_sha256': record['sha256'], 'retrieved_at': record['retrieved_at'],
            'source_locator': locator}


def fec_states(pages, record):
    """Parse the 51 state summaries, excluding bracketed fusion ballot lines.

The summary precedes the later state-by-state detailed election tables. All
candidate components must sum exactly to each printed state total.
"""
    names = {name: code for code, name in STATE_NAMES.items()}
    found, current, components = {}, None, []
    for page in pages:
        for line in page['text'].splitlines():
            line = line.strip()
            if line in names and names[line] not in found:
                if current:
                    raise ValueError('Missing FEC state total')
                current, components = names[line], []
                continue
            if not current:
                continue
            total = re.fullmatch(r'Total (?:State )?Votes:\s*([\d,]+)', line)
            if total:
                votes = number(total[1])
                if sum(c['votes'] for c in components) != votes:
                    raise ValueError(f'FEC component sum differs for {current}')
                sums = {b: sum(x['votes'] for x in components if x['bucket'] == b) for b in BUCKETS}
                if any(not any(x['bucket'] == b for x in components) for b in BUCKETS[:2]):
                    raise ValueError(f'Missing FEC major candidate: {current}')
                found[current] = dict(state=current, totals=sums, total_votes=votes,
                    components=components, **provenance(record, f"PDF page {page['page']}; state {current}; summary"))
                current = None
                continue
            # NY/SC print combined candidate totals followed by bracketed party
            # components. Counting both would double count fusion ballot lines.
            if '[' in line or ']' in line:
                continue
            match = re.fullmatch(r'(.+?)\s+([\d,]+)\s+\d+\.\d+%', line)
            if match:
                label, votes = match[1], number(match[2])
                kind = ('BARACK OBAMA' if label.startswith('Obama, Barack') else
                        'JOHN MCCAIN' if label.startswith('McCain, John') else 'OTHER')
                components.append(dict(bucket=kind, label=label, votes=votes,
                    **provenance(record, f"PDF page {page['page']}; {current}; {label}")))
        if len(found) == 51:
            break
    if set(found) != set(STATE_NAMES):
        raise ValueError(f'Incomplete FEC summary: {set(STATE_NAMES) - set(found)}')
    return found


def unit_key(name):
    """Comparison label only. Never creates or changes a geographic identity."""
    return re.sub(r'[^A-Z0-9]', '', name.upper())


def manual_units(text, columns, record, locator, expected_units):
    """Parse explicit numeric table rows (including two facing MO pages).

Column order is reviewed against the source header; no OCR/label-only identity
inference. A malformed/omitted row fails the expected row count.
"""
    count = len(columns)
    pattern = r'([A-Z][A-Z .\-]*?)\s+' + r'\s+'.join([r'([\d,]+)'] * count) + r'(?=\s|$)'
    rows = []
    for line in text.splitlines():
        for match in re.finditer(pattern, line):
            name = match[1].strip()
            if name == 'TOTAL':
                continue
            values = list(map(number, match.groups()[1:]))
            sums = {b: sum(n for c, n in zip(columns, values) if c == b) for b in BUCKETS}
            rows.append(dict(unit=name, unit_key=unit_key(name), totals=sums,
                components=values, **provenance(record, f'{locator}; row {name}')))
    if len(rows) != expected_units or len({r['unit_key'] for r in rows}) != len(rows):
        raise ValueError(f'Expected {expected_units} distinct manual rows, got {len(rows)}')
    return rows


def virginia_units(body, record):
    rows = list(csv.reader(io.StringIO(body)))
    if len(rows[0]) != 11 or rows[0][2:4] != ['Barack Obama and Joe Biden', 'John McCain and Sarah Palin']:
        raise ValueError('Virginia export columns changed')
    if rows[0][8:10] != ['Write-Ins', 'Total Votes Cast']:
        raise ValueError('Virginia export write-in/total columns changed')
    result = []
    for n, r in enumerate(rows[2:], 3):
        if r[0] != 'Locality':
            continue  # Never add precinct or statewide rows to locality totals.
        votes = list(map(number, r[2:9]))
        if sum(votes) != number(r[9]):
            raise ValueError('Virginia locality component sum differs')
        name = r[1].upper()
        name = re.sub(r' COUNTY$', '', name)
        # Retain CITY to distinguish independent cities from counties.
        result.append(dict(unit=name, unit_key=unit_key(name),
            totals=dict(zip(BUCKETS, (votes[0], votes[1], sum(votes[2:])))),
            components=votes, **provenance(record, f'CSV line {n}; Locality {r[1]}')))
    if len(result) != 134 or len({r['unit_key'] for r in result}) != 134:
        raise ValueError('Expected all 134 Virginia county/independent-city rows')
    return result


def alaska_district(pages, record, district):
    """Use only the final presidential Total, never sum it with precincts.

Long districts span multiple pages. The printed Total must equal the sum of
the preceding precinct/mode rows and its six candidate categories exactly.
"""
    all_rows, locators = [], []
    for page in pages:
        text = page['plain_text']
        if 'US PRESIDENT' not in text:
            continue
        if 'Official Results' not in text or f'District {district} - Absentee' not in '\n'.join(p['plain_text'] for p in pages):
            raise ValueError('Alaska election/district header differs')
        tail = text.split('US PRESIDENT', 1)[1]
        for line in tail.splitlines():
            m = re.fullmatch(r'(\d+)\s+(\d+)\s+(?:\d+\.\d+%|-)\s+' + r'\s+'.join([r'(\d+)']*8), line.strip())
            if m:
                # registered, cards cast, registered, presidential total,
                # Baldwin, Barr, McCain, Nader, Obama, write-ins.
                values = list(map(int, m.groups()))
                all_rows.append(values[3:])
                locators.append(page['page'])
    if len(all_rows) < 2:
        raise ValueError('Missing Alaska presidential numeric rows')
    total = all_rows[-1]
    if sum(total[1:]) != total[0] or any(sum(r[i] for r in all_rows[:-1]) != total[i] for i in range(7)):
        raise ValueError('Alaska precinct/total hierarchy does not reconcile')
    sums = {'BARACK OBAMA': total[5], 'JOHN MCCAIN': total[3],
            'OTHER': total[1]+total[2]+total[4]+total[6]}
    return dict(unit=f'DISTRICT {district}', unit_key=unit_key(f'DISTRICT {district}'),
        totals=sums, components=total, precinct_rows=len(all_rows)-1,
        **provenance(record, f'PDF page {locators[-1]}; US PRESIDENT; final Total row; District {district}'))


def minnesota_units(body, lookup, record):
    """The official county export includes scattered AND named write-ins.

The 87 county IDs are the archive's own namespace, not Census county FIPS.
Use its supplied lookup for comparisons; do not create geographic decisions.
"""
    names = {}
    for r in csv.reader(io.StringIO(lookup), delimiter=';'):
        if not r or not 1 <= int(r[0]) <= 87:
            continue
        if r[0] in names or len(r) != 3:
            raise ValueError('Invalid Minnesota county lookup')
        names[r[0]] = r[1]
    grouped, seen = defaultdict(list), set()
    for n, r in enumerate(csv.reader(io.StringIO(body), delimiter=';'), 1):
        if len(r) != 16 or r[0] != 'MN' or r[2] or r[3] != '0101' or r[4] != 'US PRESIDENT & VICE PRESIDENT':
            raise ValueError('Unexpected Minnesota results layout/scope')
        if r[1] not in names or (r[1],r[6]) in seen:
            raise ValueError('Unknown county or duplicate Minnesota candidate row')
        seen.add((r[1],r[6]))
        b = ('BARACK OBAMA' if r[7] == 'BARACK OBAMA AND JOE BIDEN' else
             'JOHN MCCAIN' if r[7] == 'JOHN MCCAIN AND SARAH PALIN' else 'OTHER')
        grouped[r[1]].append(dict(bucket=b, votes=number(r[13]), label=r[7],
            candidate_id=r[6], total_votes=number(r[15]), csv_line=n))
    if len(names) != 87 or set(grouped) != set(names):
        raise ValueError('Missing Minnesota counties')
    result = []
    for code, values in sorted(grouped.items()):
        totals = {v['total_votes'] for v in values}
        if len(totals) != 1 or sum(v['votes'] for v in values) != next(iter(totals)):
            raise ValueError('Minnesota candidate/office totals differ')
        if any(sum(v['bucket'] == b for v in values) != 1 for b in BUCKETS[:2]):
            raise ValueError('Missing/duplicate Minnesota major candidate')
        result.append(dict(unit=names[code], unit_key=unit_key(names[code]),
            totals={b: sum(v['votes'] for v in values if v['bucket'] == b) for b in BUCKETS},
            components=values, authority_county_id=code,
            **provenance(record, f'County ID {code}; US PRESIDENT; 23 candidate rows; semicolon layout')))
    return result


def sum_observations(rows):
    ids, totals = set(), Counter()
    for r in rows:
        if r['observation_id'] in ids:
            raise ValueError('Duplicate observation in aggregation')
        ids.add(r['observation_id'])
        if r['mode'] != 'TOTAL' or r['votes'] is None or r['votes'] < 0:
            raise ValueError('Incompatible reporting mode or missing votes')
        totals[bucket(r['candidate'])] += r['votes']
    return {b: totals[b] for b in BUCKETS}


def compare(expected, observed, *, comparable, complete, evidence_available=True):
    if not evidence_available:
        return dict(expected_votes=None, observed_votes=observed, difference=None,
                    disposition='EVIDENCE_UNAVAILABLE')
    if not comparable:
        return dict(expected_votes=expected, observed_votes=observed, difference=None,
                    disposition='INCOMPATIBLE_REPORTING_LEVEL')
    delta = observed - expected
    return dict(expected_votes=expected, observed_votes=observed, difference=delta,
        disposition=('EXACT' if delta == 0 and complete else
                     'PARTIAL_COVERAGE' if not complete else 'MISMATCH'))


def exclusion_partition(handoff, observations):
    """The original 144 are fixed even when a new preview accepts some rows."""
    ids = [r['observation_id'] for r in handoff]
    if len(ids) != 144 or len(set(ids)) != 144:
        raise ValueError('Handoff must contain exactly 144 distinct observations')
    by_id = {r['observation_id']: r for r in observations}
    if len(by_id) != len(observations):
        raise ValueError('Duplicate input observations')
    if set(ids) != {r['observation_id'] for r in observations if not r['stored_accepted']}:
        raise ValueError('Original exclusions differ from the stored batch; review baseline')
    counts = Counter()
    for h in handoff:
        row = by_id[h['observation_id']]
        if row['row_sha256'] != h['row_sha256'] or row['votes'] != int(h['votes']):
            raise ValueError('Handoff source lineage differs')
        state, name = row['state'], row['county']
        part = ('AK_DISTRICTS_1_40' if state == 'AK' and name != 'DISTRICT 99' else
                'AK_DISTRICT_99' if state == 'AK' else 'MN_ALIAS' if state == 'MN' else
                'VA_COUNTIES' if state == 'VA' else 'SPECIAL_UNITS')
        counts[part] += 1
    if counts != Counter(AK_DISTRICTS_1_40=120, AK_DISTRICT_99=3,
                         MN_ALIAS=3, VA_COUNTIES=6, SPECIAL_UNITS=12):
        raise ValueError('Original exclusion partitions differ')
    return by_id
