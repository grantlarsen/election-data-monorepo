"""Prepare official NARA presidential electoral votes; no vote inference from popular returns."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from types import SimpleNamespace
from ingestion.medsl import STATE_NAMES
from ingestion.source import SourceInfo, acquire, atomic_json
CANDIDATES = {2000: [('George W. Bush', 'REPUBLICAN'), ('Al Gore', 'DEMOCRATIC')], 2004: [('George W. Bush', 'REPUBLICAN'), ('John Kerry', 'DEMOCRATIC')], 2008: [('Barack Obama', 'DEMOCRATIC'), ('John McCain', 'REPUBLICAN')], 2012: [('Barack Obama', 'DEMOCRATIC'), ('Mitt Romney', 'REPUBLICAN')], 2016: [('Donald Trump', 'REPUBLICAN'), ('Hillary Clinton', 'DEMOCRATIC')], 2020: [('Joe Biden', 'DEMOCRATIC'), ('Donald Trump', 'REPUBLICAN')], 2024: [('Kamala Harris', 'DEMOCRATIC'), ('Donald Trump', 'REPUBLICAN')]}
TOTALS = {2000: [271, 266], 2004: [286, 251], 2008: [365, 173], 2012: [332, 206], 2016: [304, 227], 2020: [306, 232], 2024: [226, 312]}

class Tables(HTMLParser):

    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th'):
            self.cell = ''

    def handle_data(self, value):
        if self.cell is not None:
            self.cell += value

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.row is not None and (self.cell is not None):
            self.row.append(' '.join(self.cell.split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

def parse(raw: bytes, year: int) -> dict:
    parser = Tables()
    parser.feed(raw.decode('utf-8'))
    names = {name.casefold(): code for (code, name) in STATE_NAMES.items()}
    states = {}

    def votes(value):
        if value.strip() in ('-', '?', '?', ''):
            return 0
        match = re.fullmatch('(\\d+)[*??]*', value.strip())
        if not match:
            raise ValueError(f'Invalid electoral vote: {value}')
        return int(match[1])
    for row in parser.rows:
        label = row[0].rstrip(' *??') if row else ''
        if year == 2024:
            label = {'Indiana1': 'Indiana', 'Maine2': 'Maine', 'Nebraska3': 'Nebraska', 'New Hampshire1': 'New Hampshire', 'Oregon 1': 'Oregon'}.get(label, label)
        code = names.get(label.casefold())
        if not code:
            continue
        if code in states:
            raise ValueError('Duplicate state')
        (capacity, a, b) = map(votes, [row[1], row[2], row[4] if year == 2016 else row[3]])
        if a + b > capacity:
            raise ValueError('Electoral state partition exceeds allocation')
        states[code] = dict(name=STATE_NAMES[code], electors=capacity, votes=[a, b], other=capacity - a - b)
    if len(states) != 51 or sum((s['electors'] for s in states.values())) != 538:
        raise ValueError(f'Incomplete electoral allocation {year}: {set(STATE_NAMES) - set(states)}')
    if [sum((s['votes'][i] for s in states.values())) for i in (0, 1)] != TOTALS[year]:
        raise ValueError(f"Official totals differ {year}: {[sum((s['votes'][i] for s in states.values())) for i in (0, 1)]}")
    return dict(candidates=[dict(name=n, party=p, votes=TOTALS[year][i]) for (i, (n, p)) in enumerate(CANDIDATES[year])], states=states, other_label='Abstained' if year == 2000 else 'Other candidates', other=sum((s['other'] for s in states.values())))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=Path('data/ingestion'))
    args = parser.parse_args()
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    result = {}
    for year in CANDIDATES:
        url = f'https://www.archives.gov/electoral-college/{year}'
        info = SourceInfo('nara_electoral_college', '', str(year), year, f'{year}.html', url, None, None, {})
        asset = acquire(SimpleNamespace(key=info.source_name, describe=lambda : info), args.data_dir)
        if str(year) in existing and existing[str(year)]['source']['sha256'] != asset.sha256:
            raise ValueError('Pinned NARA source changed')
        result[str(year)] = {**parse(asset.path.read_bytes(), year), 'source': dict(url=url, sha256=asset.sha256, retrieved_at=asset.retrieved_at.isoformat())}
    atomic_json(args.output, result)
    print(json.dumps({year: [c['votes'] for c in item['candidates']] for (year, item) in result.items()}))
if __name__ == '__main__':
    main()
