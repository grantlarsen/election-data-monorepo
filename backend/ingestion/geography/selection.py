"""Exact, replayable publication subsets. A manifest is a review target, not approval."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from ingestion.geography.context import digest

FORMAT = 'geo002-publication-v1'


def payload(decision):
    return {k: (str(decision[k]) if decision[k] is not None else None)
            for k in ('status', 'method', 'reference_id', 'jurisdiction_id', 'reason')} | {
                'evidence_json': decision['evidence_json']}


def target(observation_id, previous, decision):
    return {'observation_id': str(observation_id),
            'previous': ({k: str(previous[k]) if previous[k] is not None else None
                          for k in ('id', 'status', 'method', 'reference_id', 'jurisdiction_id')}
                         if previous else None),
            'decision': payload(decision)}


def manifest(release_id, ruleset, context_sha256, targets):
    return {'format': FORMAT, 'reference_release_id': str(release_id),
            'ruleset_version': ruleset, 'context_sha256': context_sha256,
            'targets': sorted(targets, key=lambda x: x['observation_id'])}


def validate(document, release_id, ruleset, context_sha256):
    if not isinstance(document, dict) or set(document) != {
            'format', 'reference_release_id', 'ruleset_version', 'context_sha256', 'targets'}:
        raise ValueError('Malformed publication manifest')
    for key, expected in [('format', FORMAT), ('reference_release_id', str(release_id)),
                          ('ruleset_version', ruleset), ('context_sha256', context_sha256)]:
        if document[key] != expected:
            raise ValueError(f'Publication manifest {key} differs; regenerate and review')
    rows = document['targets']
    if not isinstance(rows, list) or not rows:
        raise ValueError('Publication manifest requires a nonempty exact subset')
    if any(not isinstance(x, dict) or set(x) != {'observation_id', 'previous', 'decision'} for x in rows):
        raise ValueError('Malformed publication target')
    ids = [x['observation_id'] for x in rows]
    if any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
        raise ValueError('Duplicate or invalid publication observation IDs')
    if ids != sorted(ids):
        raise ValueError('Publication targets must be sorted by observation ID')
    for row in rows:
        try:
            UUID(row['observation_id'])
            previous = row['previous']
            if previous is not None:
                if not isinstance(previous, dict) or set(previous) != {'id', 'status', 'method', 'reference_id', 'jurisdiction_id'}:
                    raise ValueError('Malformed publication predecessor')
                UUID(previous['id'])
            proposed = row['decision']
            if not isinstance(proposed, dict) or set(proposed) != {
                    'status', 'method', 'reference_id', 'jurisdiction_id', 'reason', 'evidence_json'}:
                raise ValueError('Malformed publication decision payload')
            if not isinstance(proposed['evidence_json'], dict):
                raise ValueError('Malformed publication evidence')
        except (TypeError, AttributeError) as exc:
            raise ValueError('Malformed publication target') from exc
    return {x['observation_id']: x for x in rows}


def read(path: Path):
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document.get('manifest'), dict) or digest(document['manifest']) != document.get('publication_sha256'):
        raise ValueError('Missing or corrupt publication manifest digest')
    return document['manifest']


def check_target(approved, observation_id, previous, decision, *, context_sha256,
                 publication_sha256, actor=None):
    """Return True only for an exact already-published direct successor."""
    candidate = target(observation_id, previous, decision)
    if approved == candidate:
        return False
    # Replaying the same authorization is safe only while its exact successor
    # remains the head. A later publisher or different payload is stale approval.
    if previous is not None and approved['decision'] == candidate['decision']:
        ev = previous['evidence_json']
        stored = payload(previous)
        stored['evidence_json'] = {k: v for k, v in ev.items()
                                   if k not in {'ruleset_version', 'publication_audit'}}
        predecessor = approved['previous']['id'] if approved['previous'] else None
        if (str(previous['supersedes_id']) if previous['supersedes_id'] else None) == predecessor \
                and stored == approved['decision'] \
                and previous['context_sha256'] == context_sha256 \
                and ev.get('publication_audit', {}).get('publication_sha256') == publication_sha256 \
                and (actor is None or previous['published_by'] == actor):
            return True
    raise ValueError(f'Stale or changed publication target {observation_id}; regenerate and review')
