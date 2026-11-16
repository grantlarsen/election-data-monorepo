"""Offline 2008 county verification. Evidence never changes source observations.

Census/CQ is an independent published *comparison*, not an election authority.
Unavailable cells, state-only ballots and election-authority segments retain
their reporting level; no geographic allocation is performed here.
"""
from __future__ import annotations

from collections import defaultdict
import csv
import io
import json
import re

from ingestion.data005 import BUCKETS, number, provenance, unit_key


ITEMS = dict(zip(('total', *BUCKETS),
                 ('ELE010208D', 'ELE020208D', 'ELE030208D', 'ELE060208D')))


def observation_inventory(rows):
    groups=defaultdict(dict)
    seen=set()
    for row in rows:
        if row['observation_id'] in seen:
            raise ValueError('Duplicate observation inventory')
        seen.add(row['observation_id'])
        if (row['raw_json']['year']!='2008' or row['mode']!='TOTAL'
                or row['candidate'] not in BUCKETS or row['votes'] is None
                or integer(row['votes'])!=row['votes']):
            raise ValueError('Incompatible source year/candidate/mode/votes')
        key=row['state'],row['county'],row['county_fips']
        if row['candidate'] in groups[key]:
            raise ValueError('Duplicate reporting-unit candidate; possible overlapping observations')
        groups[key][row['candidate']]=row
    if any(set(v)!=set(BUCKETS) for v in groups.values()):
        raise ValueError('Missing reporting-unit candidate bucket')
    return groups


def complete_county_coverage(rows, expected_fips, fec_votes):
    """A state sum cannot establish county completeness or eliminate overlaps."""
    if not rows or not expected_fips:
        return False
    if any(r['reporting_level']!='county' or r['disposition']!='AUTHORITY_EXACT'
           or not r['canonical_stored_accepted'] or r['geography_status']!='RESOLVED' for r in rows):
        return False
    cells={(r['source_fips'],r['candidate_bucket']) for r in rows}
    expected={(f,b) for f in expected_fips for b in BUCKETS}
    if cells!=expected or len(cells)!=len(rows):
        return False
    return all(sum(r['observed_votes'] for r in rows if r['candidate_bucket']==b)==fec_votes[b] for b in BUCKETS)


def integer(value):
    if isinstance(value, bool):
        raise ValueError('Invalid integer cell')
    if isinstance(value, (int, float)):
        if value < 0 or int(value) != value:
            raise ValueError('Invalid integer cell')
        return int(value)
    return number(str(value))


def census_cells(book, metadata, sources, flags, notes, record):
    """Find columns by item ID, retain flags and exact Excel cell locators.

    A numeric zero accompanied by flag 3 or 5 is NOT a zero-vote return.
    The unit/year/source declarations are checked before reading any votes.
    """
    meta = {str(r[0]): r for r in metadata}
    if not any(r[0] == 'CQ Press' for r in sources):
        raise ValueError('Missing declared CQ Press source')
    descriptions = {}
    for item in ITEMS.values():
        row = meta.get(item)
        if (not row or '2008' not in row[1] or row[2:4] != ['ABS', '0']
                or row[5] != 'CQ Press'):
            raise ValueError('Unexpected county reference year/unit/source')
        descriptions[item] = row[1]
    definitions = {integer(r[0]): str(r[1]) for r in flags if str(r[0]) not in ('', 'ID')}
    footnotes = {str(r[0]): str(r[2]) for r in notes if str(r[0]) != 'Footkey'}
    result, seen = {}, set()
    for sheet in book.sheets():
        header = sheet.row_values(0)
        for bucket, item in ITEMS.items():
            if item not in header:
                continue
            if item in seen:
                raise ValueError('Duplicate county reference item')
            seen.add(item)
            col = header.index(item)
            if header[:2] != ['Areaname', 'STCOU'] or col == 0:
                raise ValueError('Unexpected county reference layout')
            keys = set()
            for n in range(1, sheet.nrows):
                row = sheet.row_values(n)
                fips = f'{integer(row[1]):05d}'
                if fips in keys:
                    raise ValueError('Duplicate county reference geography')
                keys.add(fips)
                target = result.setdefault(fips, dict(fips=fips, name=row[0], cells={}))
                if target['name'] != row[0]:
                    raise ValueError('County reference sheets disagree on geography')
                flag = integer(row[col-1]) if row[col-1] != '' else 0
                if flag not in (0, 1, *definitions):
                    raise ValueError('Unknown county reference flag')
                refs = [str(integer(x)) if isinstance(x, (int, float)) else x
                        for x in row[col+1:col+3] if x != '']
                if any(x not in footnotes for x in refs):
                    raise ValueError('Missing county reference footnote')
                # Flag 1 refers to a footnote; missing/suppressed cells are null.
                available = flag in (0, 1)
                target['cells'][bucket] = dict(votes=integer(row[col]) if available else None,
                    flag=flag, flag_meaning=definitions.get(flag, 'Footnote' if flag else 'Reported'),
                    footnotes=[dict(id=x, text=footnotes[x]) for x in refs], item=item,
                    **provenance(record, f'{sheet.name}!R{n+1}C{col+1}; STCOU {fips}; {item}'))
            if any(set(x['cells']) - set(ITEMS) for x in result.values()):
                raise ValueError('Unexpected county reference field')
    if seen != set(ITEMS.values()) or any(set(r['cells']) != set(ITEMS) for r in result.values()):
        raise ValueError('Incomplete county reference fields/geographies')
    for r in result.values():
        vals = [r['cells'][b]['votes'] for b in ITEMS]
        r['component_difference'] = None if None in vals else sum(vals[1:]) - vals[0]
    return result, descriptions


def candidate_bucket(label):
    value = label.upper()
    if 'OBAMA' in value:
        return BUCKETS[0]
    if 'MCCAIN' in value:
        return BUCKETS[1]
    if any(x in value for x in ('BLANK', 'VOID', 'OVERVOTE', 'UNDERVOTE', 'TOTAL VOTE','TOTAL BALLOT','BALLOTS CAST','TURNOUT')):
        raise ValueError('Non-candidate category passed as candidate')
    if not value.strip():
        raise ValueError('Missing candidate label')
    return 'OTHER'


def units(components, record, *, expected_count, reporting_level='county'):
    """Validate unique candidate cells and retain unnamed OTHER as a group."""
    grouped, seen = defaultdict(list), set()
    for r in components:
        key = unit_key(r['unit'])
        cell = (key, r['label'])
        if cell in seen:
            raise ValueError('Duplicate candidate cell; possible overlap/double-counting')
        seen.add(cell)
        b = candidate_bucket(r['label'])
        grouped[key].append({**r, 'bucket': b, 'votes': integer(r['votes'])})
    if len(grouped) != expected_count:
        raise ValueError(f'Expected {expected_count} reporting units, found {len(grouped)}')
    result = []
    for key, rows in sorted(grouped.items()):
        if any(not any(r['bucket'] == b for r in rows) for b in BUCKETS[:2]):
            raise ValueError('Missing major candidate')
        for b in BUCKETS[:2]:
            candidates=[r for r in rows if r['bucket']==b]
            if len(candidates)>1:
                partitions=[r.get('town') for r in candidates]
                if None in partitions or len(set(partitions))!=len(partitions):
                    raise ValueError('Overlapping major-candidate groups; combined and component totals cannot be added')
        # Multiple party lines are allowed only as explicit disjoint components;
        # the adapters pass combined candidates once when supplied by authority.
        result.append(dict(unit=rows[0]['unit'], unit_key=key, reporting_level=reporting_level,
            election_year=2008, election_stage='general', vote_mode='TOTAL',
            totals={b: sum(r['votes'] for r in rows if r['bucket'] == b) for b in BUCKETS},
            components=rows, **provenance(record, '; '.join(r['locator'] for r in rows))))
    return result


def civera_csv(body, record, *, state, count, level='County'):
    rows = list(csv.reader(io.StringIO(body)))
    header = rows[0]
    if not any('Obama' in x for x in header) or not any('McCain' in x for x in header):
        raise ValueError('Unexpected official candidate header')
    # New York and MA-style blank/void/total ballots are not candidate votes.
    excluded = {'BLANK', 'BLANKS', 'VOID', 'TOTAL VOTES', 'TOTAL VOTES CAST', 'TOTAL BALLOTS CAST'}
    columns = [(i, x) for i, x in enumerate(header) if i >= 2 and x and x.upper() not in excluded]
    cells = []
    state_rows = []
    for line, row in enumerate(rows[2:], 3):
        if len(row) != len(header):
            raise ValueError('Ragged official export')
        if row[0] == 'State':
            state_rows.append(row)
        if row[0] != level:
            continue  # Never add state, town and precinct subtotals together.
        for i, label in columns:
            cells.append(dict(unit=row[1], label=label, votes=number(row[i]),
                              locator=f'CSV line {line}; column {i+1}; {label}'))
    result = units(cells, record, expected_count=count,
                   reporting_level='county' if level == 'County' else 'municipality')
    if len(state_rows) != 1:
        raise ValueError('Expected one state control total')
    control = {b: sum(number(state_rows[0][i]) for i, label in columns if candidate_bucket(label) == b)
               for b in BUCKETS}
    if any(sum(r['totals'][b] for r in result) != control[b] for b in BUCKETS):
        raise ValueError(f'{state} export hierarchy does not reconcile')
    return result


def florida(body, record):
    cells = []
    for line, row in enumerate(csv.DictReader(io.StringIO(body), delimiter='\t'), 2):
        if row['ElectionDate'] != '11/4/2008':
            raise ValueError('Wrong Florida election date')
        if row['RaceCode'] != 'PRE':
            continue
        if row['OfficeDesc'] != 'President of the United States':
            raise ValueError('Unexpected Florida office')
        label = ' '.join(row[k] for k in ('CanNameFirst','CanNameMiddle','CanNameLast'))
        cells.append(dict(unit=row['CountyName'], label=label, votes=number(row['CanVotes']),
            locator=f'TSV line {line}; PRE; {row["CountyCode"]}; {label}'))
    return units(cells, record, expected_count=67)


def pennsylvania(body, readme, record):
    section = readme.split('County Code Table', 1)[1].split('Municipality Type Codes', 1)[0]
    lookup = {int(code): name.strip() for code, name in re.findall(r'^\s*(\d{2})\s+([^\r\n]+)', section, re.M)}
    if len(lookup) != 67 or 'USP President of the United States' not in readme:
        raise ValueError('Missing Pennsylvania schema/county lookup')
    counts, seen, locators, candidates = defaultdict(int), set(), defaultdict(list), {}
    for line, r in enumerate(csv.reader(io.StringIO(body)), 1):
        if not r:
            continue
        if len(r) != 33 or r[0:2] != ['2008', 'G']:
            raise ValueError('Unexpected Pennsylvania layout/election')
        if r[8] != 'USP':
            continue
        county = int(r[2])
        if county not in lookup or r[5] != '0':
            raise ValueError('Unexpected Pennsylvania reporting coverage')
        cell = county, r[3], r[10]
        if cell in seen:
            raise ValueError('Duplicate Pennsylvania precinct/candidate')
        seen.add(cell)
        label = ' '.join(x for x in (r[12],r[13],r[11],r[14]) if x)
        if r[10] in candidates and candidates[r[10]] != label:
            raise ValueError('Candidate ID has incompatible labels')
        candidates[r[10]] = label
        key = county, label
        counts[key] += number(r[15])
        locators[key].append(line)
    cells = [dict(unit=lookup[k[0]], label=k[1], votes=v,
                  locator=f'CSV lines {min(locators[k])}-{max(locators[k])}; county {k[0]:02d}; USP; {k[1]}; {len(locators[k])} precinct cells',
                  precinct_cells=len(locators[k])) for k, v in sorted(counts.items())]
    return units(cells, record, expected_count=67)


def pa_json(body):
    value=json.loads(body)
    return json.loads(value) if isinstance(value,str) else value


def pennsylvania_counties(body, metadata, state_body, record):
    meta=pa_json(metadata)
    if len(meta)!=1 or any(meta[0].get(k)!=v for k,v in
        {'ElectionID':17,'ElectionDate':'2008-11-04T00:00:00','ElectionType':'G',
         'ElectionName':'2008 General Election,Official'}.items()):
        raise ValueError('Wrong Pennsylvania year/stage/certification')
    state=pa_json(state_body)['Election']['President of the United States']
    if len(state)!=1 or state[0]['OfficeId']!='1' or state[0]['DistrictId']!='1':
        raise ValueError('Unexpected Pennsylvania office/district')
    controls={unit_key(r['CandidateName']):number(r['Votes']) for r in state[0]['Statewide']}
    groups=pa_json(body)['Election']['StateWide']
    if len(groups)!=1:
        raise ValueError('Unexpected Pennsylvania county hierarchy')
    cells=[]
    totals=defaultdict(int)
    for name,rows in groups[0].items():
        for n,r in enumerate(rows):
            if r['ElectionYear']!='2008' or r['CountyName']!=name or r['Level']!=name:
                raise ValueError('Incompatible Pennsylvania county/year')
            label=' '.join(r['CandidateName'].split())
            if unit_key(label) not in controls:
                raise ValueError('Unexpected Pennsylvania county candidate')
            totals[unit_key(label)]+=number(r['Votes'])
            cells.append(dict(unit=name,label=label,votes=number(r['Votes']),
                locator=f'JSON Election.StateWide[0].{name}[{n}]; 2008 general; {label}'))
    if dict(totals)!=controls:
        raise ValueError('Pennsylvania county/state candidate controls differ')
    result=units(cells,record,expected_count=67)
    for row in result:
        row['incomplete_buckets']=['OTHER']
        row['grouping_note']='OTHER here includes Nader and Barr only; FEC has 18,135 additional write-in votes without county attribution in this export.'
    return result


def html_rows(body):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(body, 'html.parser')
    return [[[c.get_text(' ', strip=True) for c in r.find_all(['td','th'], recursive=False)]
             for r in t.find_all('tr')] for t in soup.find_all('table')]


def south_dakota(body, record):
    cells = []
    for table in html_rows(body):
        for line, r in enumerate(table, 1):
            if len(r) != 6 or r[0] != 'Presidential Electors':
                continue
            cells.append(dict(unit=r[1], label=r[3], votes=number(r[4]),
                              locator=f'HTML table; row {line}; Presidential Electors; {r[1]}; {r[3]}'))
    return units(cells, record, expected_count=66)


def massachusetts(body, record):
    cells = []
    tables = [t for t in html_rows(body) if any(r and r[0] == 'County' and 'Blanks' in r for r in t)]
    if len(tables) != 1:
        raise ValueError('Missing Massachusetts county table')
    table = tables[0]
    header = next(r for r in table if r and r[0] == 'County')
    if len(header) != 10 or header[7:] != ['All Others', 'Blanks', 'Total Votes Cast']:
        raise ValueError('Unexpected Massachusetts candidate groups')
    for line, r in enumerate(table, 1):
        if len(r) != len(header) or not r[0].endswith('More »'):
            continue
        name = r[0].removesuffix('More »').strip()
        if sum(number(v) for v in r[1:9]) != number(r[9]):
            raise ValueError('Massachusetts ballot totals do not reconcile')
        for i in range(1, 8):
            cells.append(dict(unit=name, label=header[i], votes=number(r[i]),
                              locator=f'HTML county table; row {line}; {name}; {header[i]}'))
    return units(cells, record, expected_count=14)


def texas(body, record):
    tables = html_rows(body)
    table = tables[0]
    header = table[0]
    if len(header) != 14 or 'McCain' not in header[1] or 'Obama' not in header[2]:
        raise ValueError('Unexpected Texas candidate table')
    cells = []
    control = None
    for line, r in enumerate(table[3:], 4):
        if len(r) != 14:
            raise ValueError('Unexpected Texas row')
        if sum(number(v) for v in r[1:11]) != number(r[11]):
            raise ValueError('Texas candidate/total votes differ')
        if r[0] == 'ALL COUNTIES':
            control = [number(x) for x in r[1:11]]
            continue
        for i in range(1, 11):
            cells.append(dict(unit=r[0], label=header[i], votes=number(r[i]),
                locator=f'HTML table 1; row {line}; {r[0]}; {header[i]}'))
    result = units(cells, record, expected_count=254)
    if control is None or sum(sum(r['totals'].values()) for r in result) != sum(control):
        raise ValueError('Texas county/state control differs')
    return result


def oklahoma(pages, record):
    cells = []
    controls = []
    for page in pages:
        for line, text in enumerate(page['text'].splitlines(), 1):
            match = re.fullmatch(r'([A-Z][A-Za-z .:]+?)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*', text.strip())
            if not match:
                continue
            name, rep, dem, total = match.groups()
            if number(rep) + number(dem) != number(total):
                raise ValueError('Oklahoma candidate/total votes differ')
            if name.strip() == 'STATE TOTAL:':
                controls.append(number(total)); continue
            for label, value in zip(('JOHN MCCAIN','BARACK OBAMA','OTHER (no remaining candidate votes)'), (rep, dem, '0')):
                cells.append(dict(unit=name.strip(), label=label, votes=number(value),
                    locator=f'PDF page {page["page"]}; text line {line}; {name.strip()}; total equals two named candidates'))
    result = units(cells, record, expected_count=77)
    if len(controls) != 1 or sum(sum(r['totals'].values()) for r in result) != controls[0]:
        raise ValueError('Oklahoma county/state control differs')
    return result


def idaho(body, record):
    table = html_rows(body)[0]
    header = table[2]
    if header != ['Counties', 'Chuck Baldwin', 'Bob Barr', 'John McCain', 'Ralph Nader', 'Barack Obama']:
        raise ValueError('Unexpected Idaho candidates')
    cells = []
    control = None
    for line, r in enumerate(table[3:], 4):
        if not r or not r[0]:
            continue
        if len(r) != 6:
            raise ValueError('Unexpected Idaho row')
        if 'TOTAL' in r[0].upper():
            control = [number(x) for x in r[1:]]
            continue
        if r[0] in ('Plurality','Percentage'):
            continue
        for i in range(1, 6):
            cells.append(dict(unit=r[0], label=header[i], votes=number(r[i]),
                              locator=f'HTML table; row {line}; {r[0]}; {header[i]}'))
    result = units(cells, record, expected_count=44)
    if control is None or sum(sum(r['totals'].values()) for r in result) != sum(control):
        raise ValueError('Idaho county/state control differs')
    return result


def candidate_csv(body, record, count, *, documented_ballot_errors=False):
    """Civera county-only export: one combined column per candidate, one control."""
    rows=[r for r in csv.reader(io.StringIO(body)) if r]
    header=rows[0]
    if header[0]!='County' or header[-1]!='Total Votes Cast':
        raise ValueError('Unexpected county-only candidate export')
    cells=[]
    controls=None
    control_ballots=None
    totals=[0]*(len(header)-2)
    ballot_errors={}
    for line,r in enumerate(rows[1:],2):
        if len(r)!=len(header):
            raise ValueError('Ragged county candidate export')
        votes=[number(v) for v in r[1:-1]]
        if sum(votes)!=number(r[-1]):
            if not documented_ballot_errors:
                raise ValueError('County candidate export sum differs')
            ballot_errors[unit_key(r[0])]=dict(reported_total=number(r[-1]),
                candidate_sum=sum(votes),difference=sum(votes)-number(r[-1]))
        if r[0]=='Totals':
            if controls is not None and (controls!=votes or control_ballots!=number(r[-1])):
                raise ValueError('Conflicting duplicate county candidate control')
            controls=votes;control_ballots=number(r[-1]);continue
        for i,v in enumerate(votes,1):
            totals[i-1]+=v
            cells.append(dict(unit=r[0],label=header[i].splitlines()[0],votes=v,
                              locator=f'CSV record {line}; {r[0]}; column {i+1}; {header[i].splitlines()[0]}'))
    result=units(cells,record,expected_count=count)
    if controls is None or totals!=controls:
        raise ValueError('County candidate export hierarchy differs')
    for row in result:
        row['internal_ballot_difference']=ballot_errors.get(row['unit_key'])
        row['documented_state_ballot_difference']=ballot_errors.get('TOTALS')
    return result


def stable_town_lookup(before, after, state):
    """Cross-check 2000 fixed-width and 2010 tabular Census county membership.

    This is a comparison crosswalk. It does not resolve/publish geography, prove
    intervening legal boundary dates, or reinterpret CT's zero statewide unit.
    """
    old={}
    for line in before.splitlines():
        if line.startswith(state) and line[12:76].strip().endswith(' town'):
            name=unit_key(line[12:76].strip().removesuffix(' town'))
            if name in old:
                raise ValueError('Ambiguous historical town name')
            old[name]=line[2:7]
    new={}
    for r in csv.DictReader(io.StringIO(after),delimiter='\t'):
        if r['USPS']==state and r['NAME'].endswith(' town'):
            name=unit_key(r['NAME'].removesuffix(' town'))
            if name in new:
                raise ValueError('Ambiguous town name')
            new[name]=r['GEOID'][:5]
    if old!=new or not old:
        raise ValueError('Town/county assignments differ across reference vintages')
    return old


def municipal_to_counties(towns, lookup, county_names, record):
    if {r['unit_key'] for r in towns}!=set(lookup):
        raise ValueError('Municipal export/crosswalk coverage differs')
    cells=[]
    for row in towns:
        county=lookup[row['unit_key']]
        if county not in county_names:
            raise ValueError('Unknown county in municipal crosswalk')
        for r in row['components']:
            cells.append(dict(unit=county_names[county],label=r['label']+'; town '+row['unit'],
                votes=r['votes'],locator=r['locator'],town=row['unit'],county_fips=county,
                candidate_bucket=r['bucket']))
    result=units(cells,record,expected_count=len(county_names))
    for row in result:
        row['comparison_crosswalk_only']=True
        row['intervening_legal_boundary_dates_verified']=False
    return result


def maryland(body, record):
    cells = []
    for index, table in enumerate(html_rows(body), 1):
        header = table[0]
        if len(header) != 7 or header[0] != '':
            raise ValueError('Unexpected Maryland candidate table')
        count = 0
        for line, r in enumerate(table[1:], 2):
            if len(r) != len(header):
                raise ValueError('Unexpected Maryland row')
            if 'TOTAL' in r[0].upper():
                continue
            count += 1
            for i in range(1, len(r)):
                cells.append(dict(unit=r[0], label=header[i], votes=number(r[i]),
                                  locator=f'HTML table {index}; row {line}; {r[0]}; {header[i]}'))
        if count != 24:
            raise ValueError('Missing Maryland county candidate block')
    return units(cells, record, expected_count=24)


def hawaii(pages_by_county, records):
    result = []
    for name, pages in pages_by_county.items():
        cells = []
        text = pages[0]['text']
        if '**FINAL SUMMARY REPORT**' not in text or 'November 4, 2008' not in text:
            raise ValueError('Unexpected Hawaii election/report status')
        for line, value in enumerate(text.splitlines(), 1):
            m = re.match(r'^\(([DRILGC])\)\s+(.+?)\s{2,}([\d,]+)\s+\d+\.\d+%', value.strip())
            if not m:
                if len(cells) == 6:
                    break
                continue
            cells.append(dict(unit=name, label=m[2], votes=number(m[3]),
                              locator=f'PDF page 1; text line {line}; President and Vice President; {name}; {m[2]}'))
        if len(cells) != 6:
            raise ValueError('Missing Hawaii presidential candidate')
        result += units(cells, records[name], expected_count=1, reporting_level='county_election_authority')
    return result


def pdf_word_rows(body, pages, cutoff):
    """Extract table cells by PDF coordinates, preserving adjacent numeric cells.

    PDF layout/plain text can concatenate adjacent numbers (e.g. 422 and 252).
    Each word retains its original position; no numeric string is guessed apart.
    """
    import pymupdf
    result = []
    with pymupdf.open(stream=body, filetype='pdf') as doc:
        for index in pages:
            groups = []
            for word in sorted(doc[index-1].get_text('words'), key=lambda w:(w[1], w[0])):
                # Baselines differ slightly between labels and numbers.
                group = next((g for g in groups if abs(g[0]-word[1]) < 2), None)
                if group is None:
                    group = [word[1], []]; groups.append(group)
                group[1].append(word)
            for y, words in sorted(groups):
                words.sort(key=lambda w:w[0])
                name = ' '.join(w[4] for w in words if w[0] < cutoff)
                values = [w[4] for w in words if w[0] >= cutoff]
                if values and all(re.fullmatch(r'[\d,]+', v) for v in values):
                    result.append(dict(page=index, y=round(y,3), name=name, values=values))
    return result


def california(body, record):
    cells = []
    controls = []
    for pages, labels in (([1,2,3], ['Barack Obama','John McCain','Alan Keyes','Cynthia McKinney',
                                    'Bob Barr','Ralph Nader','Frank Moore','Ron Paul']),
                          ([4,5,6], ['James Harris','Chuck Baldwin'])):
        count = 0
        totals = [0]*len(labels)
        control = None
        for r in pdf_word_rows(body, pages, 140):
            if len(r['values']) != len(labels):
                continue
            if r['name'] == 'State Totals':
                control = [number(v) for v in r['values']]; continue
            if not r['name'] or r['name'].startswith(('Percent', 'Registration')):
                continue
            count += 1
            for i, (label, v) in enumerate(zip(labels,r['values'])):
                totals[i] += number(v)
                cells.append(dict(unit=r['name'], label=label, votes=number(v),
                                  locator=f'PDF page {r["page"]}; y={r["y"]}; {r["name"]}; {label}'))
        if count != 58 or totals != control:
            raise ValueError(f'California county/control cells differ: {count}, {totals}, {control}')
        controls += control
    return units(cells, record, expected_count=58)


def tennessee(body, record):
    cells, controls, totals = [], None, [0]*8
    labels = ['Barack Obama','John McCain','Chuck Baldwin','Bob Barr',
              'Charles Jay','Cynthia McKinney','Ralph Nader','Brian Moore']
    for r in pdf_word_rows(body,[1,2],170):
        if len(r['values']) != 8:
            continue
        if r['name'] == 'STATEWIDE TOTALS':
            controls = [number(v) for v in r['values']]; continue
        if not r['name']:
            continue
        for i, (label, v) in enumerate(zip(labels, r['values'])):
            totals[i] += number(v)
            cells.append(dict(unit=r['name'],label=label,votes=number(v),
                              locator=f'PDF page {r["page"]}; y={r["y"]}; {r["name"]}; {label}'))
    result = units(cells, record, expected_count=95)
    if totals != controls:
        raise ValueError(f'Tennessee county/control cells differ: {totals}, {controls}')
    return result


def new_jersey(pages, record):
    cells = []
    labels = ['Barack Obama','John McCain','Ralph Nader','Bob Barr','Chuck Baldwin',
              'Cynthia McKinney','Brian Moore','Alan Keyes','Roger Calero','Gloria La Riva']
    for page, label in zip(pages[:10], labels):
        # County occupies x~345 in the official tallies, separated from addresses.
        matched, total = [], None
        for line, text in enumerate(page['text'].splitlines(), 1):
            m = re.search(r'\b(Atlantic|Bergen|Burlington|Camden|Cape May|Cumberland|Essex|Gloucester|Hudson|Hunterdon|Mercer|Middlesex|Monmouth|Morris|Ocean|Passaic|Salem|Somerset|Sussex|Union|Warren)\s{2,}.+?\s{2,}([\d,]+)\s*$', text)
            if m:
                matched.append(dict(unit=m[1], label=label, votes=number(m[2]),
                    locator=f'PDF page {page["page"]}; text line {line}; {m[1]}; {label}'))
            m = re.fullmatch(r'\s*Total\s+([\d,]+)\s*', text)
            if m:
                total = number(m[1])
        if len(matched) != 21 or sum(x['votes'] for x in matched) != total:
            raise ValueError(f'New Jersey county/candidate control differs: {label}, {len(matched)}')
        cells += matched
    return units(cells, record, expected_count=21)


def colorado(pages, record, body):
    cells = []
    labels_by_page = {
        93:['John McCain','Barack Obama','Chuck Baldwin','Bob Barr'],
        94:['Cynthia McKinney','Jonathan Allen','Gene Amondson','James Harris','Charles Jay','Alan Keyes'],
        95:['Gloria La Riva','Bradford Lyttle','Frank McEnulty','Brian Moore','Ralph Nader','Thomas Stevens']}
    for page in pages:
        labels = labels_by_page.get(page['page'])
        if labels is None:
            continue
        if 'General Election held November 4,  2008' not in page['plain_text']:
            raise ValueError('Wrong Colorado election stage')
        matched, totals, control = [], [0]*len(labels), None
        for row in pdf_word_rows(body,[page['page']],100):
            if len(row['values']) != len(labels)+(2 if page['page']==93 else 0):
                continue
            values = row['values'][(2 if page['page']==93 else 0):]
            if row['name'].lower() in ('total','totals'):
                control = [number(v) for v in values]; continue
            matched.append(row['name'])
            for i,(label,v) in enumerate(zip(labels,values)):
                totals[i] += number(v)
                cells.append(dict(unit=row['name'],label=label,votes=number(v),
                    locator=f'PDF page {page["page"]}; y={row["y"]}; {row["name"]}; {label}'))
        if len(matched)!=64 or totals!=control:
            raise ValueError(f'Colorado county/control cells differ: page {page["page"]}, {len(matched)}, {totals}, {control}')
    return units(cells, record, expected_count=64)


def wyoming(body, record):
    rows = list(csv.reader(io.StringIO(body)))
    header = ['county','John McCain','Barack Obama','Bob Barr','Chuck Baldwin',
              'Ralph Nader','Write-Ins','Under Votes','Over Votes']
    if rows[0] != header or len(rows)!=25 or rows[-1][0]!='Total':
        raise ValueError('Unexpected reviewed Wyoming table')
    if any(sum(number(r[i]) for r in rows[1:-1]) != number(rows[-1][i]) for i in range(1,9)):
        raise ValueError('Wyoming county/control cells differ')
    cells=[]
    for line,r in enumerate(rows[1:-1],2):
        for i in range(1,7):  # Under/over votes are ballot accounting, not candidates.
            cells.append(dict(unit=r[0],label=header[i],votes=number(r[i]),
                locator=f'PDF page 1; {r[0]}; {header[i]}; reviewed CSV line {line}',
                under_votes=number(r[7]), over_votes=number(r[8])))
    return units(cells,record,expected_count=23)


def illinois(body, control_body, record):
    cells=[]
    totals=defaultdict(int)
    controls={}
    for r in csv.DictReader(io.StringIO(control_body),delimiter='\t'):
        if r['Election']!='GE 2008':
            raise ValueError('Wrong Illinois election')
        if r['OfficeName']=='PRESIDENT AND VICE PRESIDENT':
            if r['CandidateID'] in controls:
                raise ValueError('Duplicate Illinois state candidate')
            controls[r['CandidateID']]=number(r['Votes'])
    for line,r in enumerate(csv.DictReader(io.StringIO(body),delimiter='\t'),2):
        if r['Election']!='GE 2008':
            raise ValueError('Wrong Illinois election')
        if r['OfficeName']!='PRESIDENT AND VICE PRESIDENT':
            continue
        if r['CandidateID'] not in controls or r['VoteFor']!='1':
            raise ValueError('Unexpected Illinois candidate/scope')
        label=r['CanFirstName']+' '+r['CanLastName']
        cells.append(dict(unit=r['County'],label=label,votes=number(r['Votes']),
            locator=f'TSV line {line}; GE 2008; President and Vice President; {r["County"]}; candidate {r["CandidateID"]}'))
        totals[r['CandidateID']]+=number(r['Votes'])
    if dict(totals)!=controls:
        raise ValueError('Illinois county/state candidate controls differ')
    return units(cells,record,expected_count=102)


def montana(body, writein_pages, record, supplement):
    rows=list(csv.reader(io.StringIO(body)))
    header=['county','Ron Paul','Barack Obama','Ralph Nader','Bob Barr','John McCain']
    if rows[0]!=header or len(rows)!=58 or rows[-1][0]!='Total':
        raise ValueError('Unexpected reviewed Montana canvass')
    if any(sum(number(r[i]) for r in rows[1:-1])!=number(rows[-1][i]) for i in range(1,6)):
        raise ValueError('Montana canvass county/candidate controls differ')
    cells=[]
    for line,r in enumerate(rows[1:-1],2):
        for i in range(1,6):
            cells.append(dict(unit=r[0],label=header[i],votes=number(r[i]),
                locator=f'Canvass PDF page 1; {r[0]}; {header[i]}; reviewed CSV line {line}'))
    presidential_columns={
        1:['Keith Russell Judd','Kenneth A. Marcure','Lawson Mitchell Bone','Lynne Anne Starr','Ronald G. Hobbs'],
        2:['Frank Moore','Santa Claus','Chuck Baldwin','RaeDeen Heupel','Jerry Carroll','Charles Jay','James Edgar Lundeen'],
        3:['Cynthia Ann McKinney and Rosa A. Clemente','Cynthia Ann McKinney','Rosa A. Clemente','Larry Goddard'],
        4:['James Germalic','Jonathan Allen','Amy Lou Wyatt']}
    supplement_total=0
    for p in writein_pages:
        labels=presidential_columns.get(p['page'])
        if labels is None:
            continue  # Page 5 contains legislative candidates only.
        matched=[]
        control=None
        sums=[0]*len(labels)
        for line,text in enumerate(p['text'].splitlines(),1):
            m=re.fullmatch(r'\s*([A-Za-z][A-Za-z &]*?)\s{2,}([\d\s]+)',text)
            if not m:
                continue
            name=m[1].strip().replace('&','and')
            values=[number(v) for v in m[2].split()]
            if len(values)<len(labels):
                raise ValueError('Missing Montana presidential write-in cell')
            values=values[:len(labels)]  # p4 columns 4+ are legislative, not president.
            if name=='GRAND TOTAL':
                control=values;continue
            matched.append(name)
            for i,(label,v) in enumerate(zip(labels,values)):
                sums[i]+=v
                cells.append(dict(unit=name,label='Write-in: '+label,votes=v,
                    locator=f'Write-in PDF page {p["page"]}; text line {line}; presidential column {i+1}; {name}; {label}',
                    **provenance(supplement,f'Write-in PDF page {p["page"]}; {name}; presidential column {i+1}')))
        if len(matched)!=56 or sums!=control:
            raise ValueError(f'Montana write-in county/candidate controls differ: page {p["page"]}, {len(matched)}')
        supplement_total+=sum(control)
    if supplement_total!=193:
        raise ValueError('Incomplete Montana presidential write-in supplement')
    result=units(cells,record,expected_count=56)
    for r in result:
        r['supplement_source']=provenance(supplement,'PDF pages 1-4; presidential columns only; 193 votes')
    return result


def montana_legislative_accounting(body, record):
    """Nonpresidential cells explain discrepancies; they never enter returns."""
    amounts=defaultdict(list)
    for page in (4,5):
        subtotal=0
        control=None
        for r in pdf_word_rows(body,[page],85):
            values=r['values'][3:] if page==4 else r['values']
            value=sum(number(v) for v in values)
            if r['name']=='GRAND TOTAL':
                control=value;continue
            if not r['name']:
                continue
            subtotal+=value
            if value:
                key=unit_key(r['name'].replace('&','and'))
                amounts[key].append(dict(votes=value,
                    **provenance(record,f'PDF page {page}; y={r["y"]}; {r["name"]}; LEGISLATIVE write-in columns only')))
        if subtotal!=control:
            raise ValueError('Montana legislative accounting control differs')
    if sum(v['votes'] for values in amounts.values() for v in values)!=4144:
        raise ValueError('Unexpected Montana legislative accounting scope')
    return amounts


def explain_difference(row, official):
    """Report accounting identities without inventing raw OTHER identities."""
    if official is None:
        return dict(accounting_explanation='ELECTION_AUTHORITY_EVIDENCE_UNAVAILABLE',
            historical_extraction_cause_verified=False)
    b=row['candidate']
    delta=row['votes']-official['totals'][b]
    explanation='EXACT' if delta==0 else 'OFFICIAL_COUNT_DIFFERS_HISTORICAL_EXTRACTION_CAUSE_UNESTABLISHED'
    sources=[]
    if delta and b=='OTHER':
        components=official['components']
        if row['state']=='WY':
            ballot=components[0]['under_votes']+components[0]['over_votes']
            if delta==ballot:
                explanation='EXCESS_EQUALS_OFFICIAL_UNDER_PLUS_OVER_VOTES'
        elif row['state']=='MT':
            values=official.get('nonpresidential_accounting',[])
            if values and delta==sum(r['votes'] for r in values):
                explanation='EXCESS_EQUALS_PRINTED_LEGISLATIVE_WRITEIN_COUNTS'
                sources=values
        elif row['state']=='NJ':
            omitted=sum(r['votes'] for r in components if r['label'] in ('Ralph Nader','Bob Barr'))
            if -delta==omitted:
                explanation='SHORTFALL_EQUALS_OFFICIAL_NADER_PLUS_BARR_COUNTS'
        elif row['state']=='NY':
            omitted=sum(r['votes'] for r in components if r['label']=='Scattering')
            if -delta==omitted:
                explanation='SHORTFALL_EQUALS_OFFICIAL_SCATTERING_COUNTS'
        elif row['state']=='SD':
            omitted=sum(r['votes'] for r in components if 'NADER' in r['label'].upper())
            if -delta==omitted:
                explanation='SHORTFALL_EQUALS_OFFICIAL_NADER_COUNTS'
    return dict(accounting_explanation=explanation,accounting_sources=sources,
        historical_extraction_cause_verified=False,
        raw_other_identity_inferred=False,
        explanation_limit='An exact arithmetic relationship identifies the accounting difference; raw grouped OTHER identities and the historical extraction process are not established.')


def assess(observation, reference, official, *, compatible=True, state_control_matches=False):
    """Never turn reference agreement, missing evidence or overlap into approval."""
    expected = official['totals'][observation['candidate']] if official else None
    cited = reference['votes'] if reference else None
    observed = observation['votes']
    if not compatible:
        status = 'INCOMPATIBLE_COVERAGE'
    elif official is None:
        status = ('REFERENCE_EXACT_AUTHORITY_UNAVAILABLE' if cited == observed else
                  'REFERENCE_DIFFERENCE_AUTHORITY_UNAVAILABLE' if cited is not None else
                  'EVIDENCE_UNAVAILABLE')
    elif observation['candidate'] in official.get('incomplete_buckets',[]):
        status='INCOMPLETE_OFFICIAL_CANDIDATE_GROUPING'
    elif official.get('internal_ballot_difference'):
        status='OFFICIAL_INTERNAL_CONFLICT'
    elif cited is not None and expected != cited:
        status = ('AUTHORITY_CORRECTION_REFERENCE_DISAGREEMENT' if expected!=observed else
                  'AUTHORITY_EXACT_REFERENCE_DISAGREEMENT') if state_control_matches else 'OFFICIAL_REFERENCE_CONFLICT'
    else:
        status = 'AUTHORITY_EXACT' if expected == observed else 'AUTHORITY_CORRECTION_EVIDENCED'
    return dict(disposition=status, observed_votes=observed, official_votes=expected,
        reference_votes=cited, official_difference=None if expected is None or not compatible or status=='INCOMPLETE_OFFICIAL_CANDIDATE_GROUPING' else observed-expected,
        reference_difference=None if cited is None or not compatible else observed-cited,
        proposed_votes=expected if status.startswith('AUTHORITY_CORRECTION') else observed,
        publication_authorized=False)
