"""Exact, release-pinned lookup of legally dated geographic identifiers.

The MEDSL resolver separately uses documented statistical product coverage.
Unknown legal starts never become implied boundary or identifier validity.
"""
from datetime import date
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import select

from app.models.geography import GeographicReference, JurisdictionIdentifier, JurisdictionBoundaryVintage
from app.models.ingestion import SourceRelease


def resolve_identifier(conn, *, release_id: UUID, kind: str, scheme: str,
                       value: str, as_of: date) -> dict:
    request = dict(release_id=str(release_id), kind=kind, scheme=scheme,
                   value=value, as_of=str(as_of))
    result = dict(request=request, status='UNRESOLVED', jurisdiction_id=None,
                  reference_id=None, boundary_vintage_id=None, candidates=[])
    if kind not in {'state','county','place','congressional_district'} or not scheme or not value:
        result['status'] = 'INVALID'
    else:
        i, r = JurisdictionIdentifier, GeographicReference
        rows = conn.execute(select(i.id, i.jurisdiction_id, i.reference_id,
            i.valid_from, i.valid_until, i.validity_evidence_url, SourceRelease.sha256)
            .join(r, r.id == i.reference_id).join(SourceRelease, SourceRelease.id == r.release_id)
            .where(r.release_id == release_id, r.kind == kind,
                   i.scheme == scheme, i.value == value).order_by(i.id)).mappings().all()
        result['candidates'] = [dict(x) for x in rows]
        eligible = [x for x in rows if (x['valid_from'] is None or x['valid_from'] <= as_of)
                    and (x['valid_until'] is None or as_of < x['valid_until'])]
        if len(eligible) > 1:
            result['status'] = 'AMBIGUOUS'
        elif eligible:
            match = eligible[0]
            if match['valid_from'] is None:
                result['status'] = 'PENDING_REVIEW'
            else:
                result.update(status='RESOLVED', jurisdiction_id=match['jurisdiction_id'],
                              reference_id=match['reference_id'])
                b = JurisdictionBoundaryVintage
                result['boundary_vintage_id'] = conn.scalar(select(b.id).where(
                    b.jurisdiction_id == match['jurisdiction_id'], b.valid_from <= as_of,
                    (b.valid_until.is_(None) | (b.valid_until > as_of))))
        elif rows:
            result['status'] = 'OUT_OF_VINTAGE'
    # A transportable, deterministic decision record including all competing evidence.
    result = json.loads(json.dumps(result, default=str))
    result['decision_sha256'] = sha256(json.dumps(result, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return result
