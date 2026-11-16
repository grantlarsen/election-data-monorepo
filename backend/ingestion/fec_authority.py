"""Verified FEC summary inputs and an explicit state-grain authority policy."""
from hashlib import sha256
import json
from pathlib import Path

from ingestion.data005 import BUCKETS, digest, fec_states, sum_observations
from ingestion.medsl import STATE_NAMES

RULESET = 'fec-2008-state-authority-v1'
SCOPE = 'president:general:2008:state:TOTAL'
AUTHORIZATION = ('Handle resolving the 45 discrepancies and treat the fec data as the '
                 'source of truth where stored data is different from it.')


def load_authority(directory):
    records = json.loads((directory/'retrievals.json').read_text(encoding='utf-8'))
    matches = [r for r in records if r['id']=='fec-2008-president']
    if len(matches)!=1:
        raise ValueError('Expected one FEC presidential source')
    record = matches[0]
    from urllib.parse import urlparse
    if not record.get('success') or urlparse(record['url']).hostname!='www.fec.gov':
        raise ValueError('FEC authority requires an archived official FEC source')
    for filename, expected in ((record['file'],record['sha256']),
                               (record['text_file'],record['text_sha256'])):
        path = (directory/filename).resolve()
        if path.parent!=directory.resolve() or sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('FEC archive/extraction checksum mismatch')
    if not (directory/record['file']).read_bytes().startswith(b'%PDF'):
        raise ValueError('FEC archive must contain the original PDF')
    states = fec_states(json.loads((directory/record['text_file']).read_text(encoding='utf-8')),record)
    return record, states


def authority_rows(observations, stored, states):
    """FEC replaces whole-state totals. Signed differences are never counties."""
    if set(states)!=set(STATE_NAMES) or {r['state'] for r in observations}!=set(STATE_NAMES):
        raise ValueError('Authority comparison requires all 51 states/DC')
    sum_observations(observations)  # Validate unique IDs, modes and categories.
    result=[]
    for st in sorted(states):
        source = sum_observations([r for r in observations if r['state']==st])
        county = sum_observations([r for r in observations if r['state']==st and r['observation_id'] in stored])
        for b in BUCKETS:
            official=states[st]['totals'][b]
            components=[c for c in states[st]['components'] if c['bucket']==b]
            if sum(c['votes'] for c in components)!=official:
                raise ValueError('FEC component/bucket mismatch')
            result.append(dict(state_code=st,candidate_bucket=b,votes=official,
                medsl_source_votes=source[b],medsl_county_votes=county[b],
                source_adjustment=official-source[b],
                source_locator=states[st]['source_locator'],components_json=components))
    if not set(stored).issubset({r['observation_id'] for r in observations}):
        raise ValueError('County publication uses observations outside the active source')
    return result
