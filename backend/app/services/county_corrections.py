"""Atomic, authorized county amendments and canonical supersession."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID,uuid4
from sqlalchemy import select,text
from app.models.core import DataSource
from app.models.ingestion import SourceRelease
from app.models.election import CanonicalPublication,CanonicalResultBatch
from app.models.county_corrections import CountyCorrectionBatch,CountyVoteCorrection
from ingestion.presidential_returns_2008 import digest
from ingestion.county_corrections import AUTHORIZATION,RULESET,validate_changes,evidence_path

SCOPE='medsl_presidential_county:2008:county_total'


def amend_plan(session,plan,batch_id):
    batch=session.get(CountyCorrectionBatch,batch_id)
    if batch is None or digest(batch.manifest_json)!=batch.fingerprint:
        raise ValueError('Invalid correction batch manifest')
    manifest=batch.manifest_json
    source=session.get(SourceRelease,batch.source_release_id)
    archive=Path(source.raw_path)
    if sha256(archive.read_bytes()).hexdigest()!=source.sha256:
        raise ValueError('Correction source archive checksum differs')
    for record in manifest['evidence_files']:
        if sha256((archive.parent/record['sha256']).read_bytes()).hexdigest()!=record['sha256']:
            raise ValueError('Archived official correction evidence differs')
    if (plan['release'].id!=batch.compared_source_release_id or
        plan['fingerprint']!=manifest['raw_projection_fingerprint']):
        raise ValueError('Correction source/geographic projection changed; review required')
    corrections=list(session.scalars(select(CountyVoteCorrection).where(CountyVoteCorrection.batch_id==batch.id)))
    expected={r['observation_id']:r for r in manifest['rows']}
    accepted={str(o.id):(o,g) for o,g,_,_ in plan['accepted']}
    if len(corrections)!=batch.correction_count or len(expected)!=len(corrections):
        raise ValueError('Incomplete correction batch')
    mapped={}
    for r in corrections:
        key=str(r.observation_id)
        row=expected.get(key)
        if row is None or key not in accepted:
            raise ValueError('Correction targets excluded or unknown observation')
        o,g=accepted[key]
        actual=dict(observation_id=key,geographic_resolution_id=str(r.geographic_resolution_id),
            row_sha256=r.row_sha256,original_votes=r.original_votes,votes=r.votes,
            state_code=r.state_code,candidate_bucket=r.candidate_bucket,evidence_json=r.evidence_json)
        if (actual!=row or o.row_sha256!=r.row_sha256 or o.candidate_votes!=r.original_votes
                or g.id!=r.geographic_resolution_id or o.state_code!=r.state_code
                or o.candidate_normalized!=r.candidate_bucket):
            raise ValueError('Correction row/source/geography manifest mismatch')
        mapped[o.id]=r
    plan['correction_batch']=batch
    plan['corrections']=mapped
    plan['effective_votes']={o.id:mapped[o.id].votes if o.id in mapped else o.candidate_votes for o,_,_,_ in plan['accepted']}
    plan['target_sum']=sum(plan['effective_votes'].values())
    plan['fingerprint']=digest([RULESET,plan['fingerprint'],batch.fingerprint])
    return plan


def prepare(session,review):
    from app.services.canonical_results import _plan
    validate_changes(review['changes'],review['review_sha256'],len(review['changes']))
    base=_plan(session,2008,None,ignore_corrections=True)
    if sha256(Path(base['release'].raw_path).read_bytes()).hexdigest()!=base['release'].sha256:
        raise ValueError('MEDSL source archive checksum differs')
    proposal=review['proposal']
    if base['fingerprint']!=proposal['current_canonical_preview']['fingerprint'] or str(base['release'].id)!=proposal['source_release']['id']:
        raise ValueError('Stale correction preview/source/geography')
    accepted={str(o.id):(o,g) for o,g,_,_ in base['accepted']}
    rows=[]
    for change in review['changes']:
        pair=accepted.get(change['observation_id'])
        if pair is None:
            raise ValueError('Correction observation is not currently eligible')
        o,g=pair
        if (o.row_sha256!=change['row_sha256'] or o.candidate_votes!=change['observed_votes']
            or o.candidate_normalized!=change['candidate_bucket'] or o.state_code!=change['state']
            or o.county_fips!=change['source_fips'] or o.year!=2008 or o.mode_normalized!='TOTAL'):
            raise ValueError('Correction observation lineage differs')
        rows.append(dict(observation_id=str(o.id),geographic_resolution_id=str(g.id),row_sha256=o.row_sha256,
            original_votes=o.candidate_votes,votes=change['proposed_votes'],state_code=o.state_code,
            candidate_bucket=o.candidate_normalized,evidence_json=change))
    rows.sort(key=lambda r:r['observation_id'])
    manifest=dict(format=RULESET,year=2008,review_sha256=review['review_sha256'],
        raw_projection_fingerprint=base['fingerprint'],source_release_id=str(base['release'].id),
        source_sha256=base['release'].sha256,compared_canonical_batch=proposal['current_county_batch'],
        rows=rows,evidence_files=review['evidence_files'],authorization=AUTHORIZATION,
        coverage='PARTIAL; no state-only allocation; no new geographic decisions')
    fingerprint=digest(manifest)
    correction_sha=digest([RULESET,base['fingerprint'],fingerprint])
    adjustment=sum(r['votes']-r['original_votes'] for r in rows)
    return dict(manifest=manifest,fingerprint=fingerprint,canonical_fingerprint=correction_sha,
        accepted_rows=len(base['accepted']),excluded_rows=len(base['rejected']),
        votes=base['target_sum']+adjustment,raw_preview_votes=base['target_sum'],
        correction_count=len(rows),vote_adjustment=adjustment,status='PARTIAL')


def publish(session,review,*,expected_fingerprint,actor,archive_dir,root):
    from app.services.canonical_results import materialize_medsl_year
    if not actor or not actor.strip() or len(actor)>100:
        raise ValueError('Publishing actor required')
    if session.scalar(text('SHOW transaction_isolation'))!='repeatable read':
        raise ValueError('County publication requires REPEATABLE READ')
    session.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'),{'scope':SCOPE})
    projection=prepare(session,review)
    if projection['fingerprint']!=expected_fingerprint:
        raise ValueError('Stale publication digest')
    pointer=session.get(CanonicalPublication,SCOPE)
    current=session.get(CanonicalResultBatch,pointer.batch_id) if pointer else None
    manifest=projection['manifest']
    if current is None or (str(current.id)!=manifest['compared_canonical_batch']['id'] and current.fingerprint!=projection['canonical_fingerprint']):
        raise ValueError('Canonical baseline/pointer changed since review')
    batch=session.scalar(select(CountyCorrectionBatch).where(CountyCorrectionBatch.fingerprint==projection['fingerprint']))
    if batch is None:
        archive_dir.mkdir(parents=True,exist_ok=True)
        for record in review['evidence_files']:
            original=evidence_path(root,record['file']).read_bytes()
            if sha256(original).hexdigest()!=record['sha256']:
                raise ValueError('Evidence changed before publication')
            path=archive_dir/record['sha256']
            if path.exists() and path.read_bytes()!=original:
                raise ValueError('Archived official evidence changed')
            if not path.exists():path.write_bytes(original)
        content=(json.dumps(manifest,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
        checksum=sha256(content).hexdigest()
        path=archive_dir/(checksum+'.json')
        if path.exists() and path.read_bytes()!=content:
            raise ValueError('Correction source archive changed')
        if not path.exists():path.write_bytes(content)
        source=session.scalar(select(DataSource).where(DataSource.name=='official_presidential_county_corrections'))
        if source is None:
            source=DataSource(name='official_presidential_county_corrections',url='Official election authority evidence; DATA-005 reviewed amendments')
            session.add(source);session.flush()
        release=SourceRelease(source_id=source.id,version='2008:'+review['review_sha256'][:24],sha256=checksum,
            filename=path.name,file_id=0,download_url='Reviewed local manifest of official source URLs',raw_path=str(path),
            retrieved_at=datetime.now(timezone.utc),metadata_json=dict(authority='Official state/county election records',
                review_sha256=review['review_sha256'],reporting_level='county',original_observations_preserved=True))
        session.add(release);session.flush()
        batch=CountyCorrectionBatch(id=uuid4(),election_year=2008,source_release_id=release.id,
            compared_source_release_id=UUID(manifest['source_release_id']),
            compared_canonical_batch_id=UUID(manifest['compared_canonical_batch']['id']),
            fingerprint=projection['fingerprint'],review_sha256=review['review_sha256'],
            correction_count=projection['correction_count'],vote_adjustment=projection['vote_adjustment'],
            published_by=actor.strip(),authorization_note=AUTHORIZATION,manifest_json=manifest)
        session.add(batch);session.flush()
        for row in manifest['rows']:
            session.add(CountyVoteCorrection(id=uuid4(),batch_id=batch.id,**{k:UUID(v) if k in
                ('observation_id','geographic_resolution_id') else v for k,v in row.items()}))
        session.flush()
    result=materialize_medsl_year(session,year=2008,dry_run=False,allow_partial=True,correction_batch_id=batch.id)
    if result['fingerprint']!=projection['canonical_fingerprint'] or result['eligible_canonical_votes']!=projection['votes']:
        raise ValueError('Published county projection differs from reviewed preview')
    session.expire_all()
    return dict(**projection,action=result['action'],batch_id=result['batch_id'],correction_batch_id=str(batch.id),
                canonical_report=result,published_by=batch.published_by)
