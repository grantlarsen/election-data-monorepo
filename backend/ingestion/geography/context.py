"""Freeze every supplemental input, not merely the primary reference release."""
from datetime import date
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import select

from app.models.core import DataSource
from app.models.geography import (GeographicReference, GeographicAlias,
    GeographicChange, GeographicResolutionContext)
from app.models.ingestion import SourceRelease, SourceActiveYear
from ingestion.geography.rules import RULESET_VERSION, name_key


def digest(manifest):
    return sha256(json.dumps(manifest, sort_keys=True, default=str,
                             separators=(',', ':')).encode()).hexdigest()


def capture(conn, release_id, years):
    refs = select(GeographicReference.__table__, SourceRelease.sha256.label('release_sha256'),
                  DataSource.name.label('source_name')).join(SourceRelease,
        SourceRelease.id == GeographicReference.release_id).join(DataSource,
        DataSource.id == SourceRelease.source_id).where(GeographicReference.kind == 'county')
    manifest = dict(format='data004-context-v1', ruleset_version=RULESET_VERSION,
        reference_release_id=str(release_id), election_years=years,
        references=[dict(x) for x in conn.execute(refs.order_by(GeographicReference.id)).mappings()],
        aliases=[dict(x) for x in conn.execute(select(GeographicAlias.__table__).where(
            GeographicAlias.status == 'APPROVED',
            GeographicAlias.source_name == 'medsl_presidential_county').order_by(GeographicAlias.id)).mappings()],
        changes=[dict(x) for x in conn.execute(select(GeographicChange.__table__).where(
            GeographicChange.status == 'VERIFIED').order_by(GeographicChange.id)).mappings()],
        observation_scope=[dict(x) for x in conn.execute(select(SourceActiveYear.release_id,
            SourceActiveYear.year, SourceRelease.sha256).join(SourceRelease,
            SourceRelease.id == SourceActiveYear.release_id).join(DataSource, DataSource.id == SourceActiveYear.source_id)
            .where(DataSource.name == 'medsl_presidential_county', SourceActiveYear.year.in_(years))
            .order_by(SourceActiveYear.year)).mappings()])
    return json.loads(json.dumps(manifest, default=str))


def restore(conn, sha):
    manifest = conn.scalar(select(GeographicResolutionContext.manifest).where(
        GeographicResolutionContext.sha256 == sha))
    if manifest is None or digest(manifest) != sha:
        raise ValueError('Unknown or corrupt geographic resolution context')
    return manifest


def _decode(row):
    return {k: UUID(v) if k in {'id','release_id','jurisdiction_id'} and v is not None
            else date.fromisoformat(v) if k == 'effective_date' else v for k,v in row.items()}


def _by_code(rows):
    """Use newest product evidence; reject contradictory ties instead of picking one."""
    found = {}
    for row in sorted(rows, key=lambda r: (-r['vintage_end'], str(r['release_id']), str(r['id']))):
        old = found.setdefault(row['geoid'], row)
        if old['vintage_end'] == row['vintage_end'] and (
                old['jurisdiction_id'] != row['jurisdiction_id'] or name_key(old['name_raw']) != name_key(row['name_raw'])):
            raise ValueError('Conflicting supplemental references; pin/review evidence before resolving')
    return found


def indexes(manifest, begin, end):
    refs = [_decode(x) for x in manifest['references']]
    primary = [x for x in refs if str(x['release_id']) == manifest['reference_release_id']]
    by_code = _by_code(primary)
    if not by_code or len(by_code) != len(primary):
        raise ValueError('Missing or duplicate county reference identifiers')
    newest = max(x['vintage_end'] for x in refs)
    latest = {code: (r['vintage_end'], name_key(r['name_raw'])) for code,r in
              _by_code([x for x in refs if x['vintage_end'] == newest]).items()} if newest > end else {}
    legacy = _by_code([x for x in refs if x['state_fips'] == '09' and x['vintage_end'] <= 2021])
    newer = _by_code([x for x in refs if x['vintage_end'] > end])
    supplement = _by_code([x for x in refs if x['source_name'] == 'census_2000_counties_gazetteer'
                           and x['vintage_start'] == x['vintage_end'] == 2000])
    return by_code, latest, legacy, newer, supplement, [_decode(x) for x in manifest['aliases']], [_decode(x) for x in manifest['changes']]
