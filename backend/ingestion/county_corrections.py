"""Strict scope and byte verification for the reviewed 283 county amendments."""
from hashlib import sha256
import json
from pathlib import Path
from ingestion.data005 import digest

REVIEW_SHA='596801cc989380199a7511b305c480f6aaa27b838b815102658d0eaa8432c9e5'
AUTHORIZATION='Apply the proposed corrections'
RULESET='data005-county-corrections-v1'


def validate_changes(changes, expected_sha, count):
    if digest(changes)!=expected_sha or len(changes)!=count:
        raise ValueError('Reviewed correction digest/count differs')
    ids=set()
    for r in changes:
        if r['observation_id'] in ids:
            raise ValueError('Duplicate correction observation')
        ids.add(r['observation_id'])
        if (not r['disposition'].startswith('AUTHORITY_CORRECTION') or r['election_year']!=2008
            or r['reporting_level']!='county' or r['election_stage']!='general' or r['vote_mode']!='TOTAL'
            or not r['canonical_preview_accepted'] or r['official_votes']!=r['proposed_votes']
            or r['proposed_votes']<0 or r['observed_votes']==r['proposed_votes']
            or r['vote_adjustment']!=r['proposed_votes']-r['observed_votes']):
            raise ValueError('Unsupported/withheld correction scope')


def load_review(directory, root):
    proposal=json.loads((directory/'correction-manifest.json').read_text(encoding='utf-8'))
    changes=proposal['changes']
    validate_changes(changes,REVIEW_SHA,283)
    if proposal['sha256']!=REVIEW_SHA or sum(r['vote_adjustment'] for r in changes)!=89944:
        raise ValueError('Correction proposal scope changed')
    inventory={r['id']:r for r in json.loads((directory/'source-inventory.json').read_text(encoding='utf-8'))}
    required={}
    def collect(obj):
        if isinstance(obj,dict):
            key=obj.get('evidence_id',obj.get('id'))
            checksum=obj.get('source_sha256',obj.get('sha256'))
            if key and checksum:
                if key not in inventory or inventory[key].get('sha256')!=checksum:
                    raise ValueError('Official evidence lineage differs')
                required[key]=inventory[key]
            for v in obj.values():collect(v)
        elif isinstance(obj,list):
            for v in obj:collect(v)
    for r in changes:collect(r['official_source']);collect(r.get('accounting_sources',[]))
    files=[]
    for key,r in sorted(required.items()):
        value=r['archive_location'].replace('\\','/')
        relative='data/'+value.split('/data/',1)[1] if '/data/' in value else value
        path=root/relative
        if not r['success'] or sha256(path.read_bytes()).hexdigest()!=r['sha256']:
            raise ValueError(f'Official raw file checksum differs: {key}')
        files.append(dict(id=key,file=relative,sha256=r['sha256'],url=r['url'],retrieved_at=r['retrieved_at']))
    reviewed=root/'docs/sources/DATA005-county-reviewed.json'
    tables=json.loads(reviewed.read_text(encoding='utf-8'))
    for row in tables['tables']:
        path=reviewed.parent/row['file']
        if sha256(path.read_bytes()).hexdigest()!=row['sha256'] or required[row['evidence_id']]['sha256']!=row['source_sha256']:
            raise ValueError('Reviewed numeric transcription differs')
        files.append(dict(id=row['file'],file=path.relative_to(root).as_posix(),sha256=row['sha256']))
    return dict(proposal=proposal,changes=changes,evidence_files=files,review_sha256=REVIEW_SHA)
