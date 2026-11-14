"""Independent official 2024 Census *place* GEOID reference (not county FIPS).

National Gazetteer ZIP is acquired/cached/hashed via the existing source layer.
The place reference does not establish earlier-year boundaries or place identity.
"""
from __future__ import annotations

from datetime import datetime,timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4, uuid5
from zipfile import ZipFile

import polars as pl
from sqlalchemy import insert,select,update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.core import DataSource,Jurisdiction
from app.models.geography import GeographicReference,JurisdictionIdentifier,JurisdictionRelationship
from app.models.ingestion import SourceRelease,IngestionRun
from ingestion.source import SourceInfo
from ingestion.geography.load import STATE_BY_FIPS,stable_jurisdiction_id,REFERENCE_NS
from ingestion.geography.rules import name_key
from ingestion.loader import _chunks

URL='https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip'


def parse_places(path:Path)->pl.DataFrame:
    with ZipFile(path) as arc:
        contents=[n for n in arc.namelist() if n.lower().endswith('.txt') and not n.startswith('__MACOSX')]
        if len(contents)!=1:raise ValueError(f'Expected exactly one Gazetteer text file: {contents}')
        payload=arc.read(contents[0])
    frame=pl.read_csv(BytesIO(payload),separator='\t',infer_schema_length=0,encoding='utf8-lossy')
    frame=frame.rename({c:c.strip().upper() for c in frame.columns})
    if not {'GEOID','NAME'}.issubset(frame.columns):
        raise ValueError(f'Unexpected Census Gazetteer place header: {frame.columns}')
    frame=frame.with_row_index('source_row_number',offset=2).select(
        pl.col('source_row_number'),pl.col('GEOID').str.strip_chars().alias('geoid'),
        pl.col('NAME').str.strip_chars().alias('name_raw'))
    return frame.with_columns(pl.col('geoid').str.slice(0,2).alias('state_fips'),
        pl.col('name_raw').map_elements(name_key,return_dtype=pl.String).alias('name_key'))


class Job:
    geographic_reference=True
    key='census_2024_places_gazetteer'
    source_url='https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2024.html'
    supported_vintages=frozenset({2024})

    def __init__(self,vintage:int|None=None):
        if vintage!=2024:raise ValueError('2024 places Gazetteer requires --vintage 2024')

    def describe(self)->SourceInfo:
        return SourceInfo(source_name=self.key,doi='Census 2024 National Places Gazetteer',
            version='2024-places',file_id=2024,filename='2024_Gaz_place_national.zip',
            download_url=URL,expected_size=None,published_at=None,
            metadata={'provider':'U.S. Census Bureau','series':'Gazetteer places',
                'vintage_start':2024,'vintage_end':2024,
                'source_page':self.source_url,'license':'U.S. government public-domain data',
                'vintage_semantics':'2024 statistical reference, not historical legal effective dates'})

    def parse(self,path:Path)->pl.DataFrame:
        return parse_places(path)

    def validate(self,frame:pl.DataFrame)->dict:
        from ingestion.medsl import STATE_FIPS
        allowed=set(STATE_FIPS.values())
        malformed=frame.filter(~pl.col('geoid').str.contains(r'^\d{7}$') |
            pl.col('name_key').is_null() | (pl.col('name_key')=='')).height
        if malformed:raise ValueError(f'Gazetteer has {malformed} malformed place rows')
        df=frame.filter(pl.col('state_fips').is_in(list(allowed)))
        if df.height<10000:raise ValueError('Place Gazetteer appears incomplete')
        dup=df.group_by('geoid').agg(pl.len().alias('n')).filter(pl.col('n')>1)
        if dup.height:raise ValueError('Duplicate Census place GEOID')
        return {'records_in_file':frame.height,'eligible_places':df.height,
                'excluded_outside_50_states_dc':frame.height-df.height,
                'distinct_states':df.get_column('state_fips').n_unique()}

    def load(self,engine,source_id:UUID,run_id:UUID,asset,frame,validation,*,started_at=None)->dict:
        states=STATE_BY_FIPS
        records=frame.filter(pl.col('state_fips').is_in(list(states))).to_dicts()
        with engine.begin() as conn:
            conn.execute(select(DataSource.id).where(DataSource.id==source_id).with_for_update()).scalar_one()
            conn.execute(pg_insert(SourceRelease.__table__).values(
                id=uuid4(),source_id=source_id,version=asset.info.version,sha256=asset.sha256,
                filename=asset.info.filename,file_id=asset.info.file_id,download_url=asset.info.download_url,
                raw_path=str(asset.path),retrieved_at=asset.retrieved_at,published_at=asset.info.published_at,
                metadata_json=asset.info.metadata).on_conflict_do_nothing(
                    index_elements=['source_id','version','sha256']))
            release_id=conn.execute(select(SourceRelease.id).where(SourceRelease.source_id==source_id,
                SourceRelease.version==asset.info.version,SourceRelease.sha256==asset.sha256)).scalar_one()
            jids={r['geoid']:stable_jurisdiction_id('place',r['geoid'],r['name_key']) for r in records}
            for chunk in _chunks([{'id':jids[r['geoid']],'name':r['name_raw'],'level':'place',
                'state_code':states[r['state_fips']]} for r in records]):
                conn.execute(pg_insert(Jurisdiction.__table__).values(chunk).on_conflict_do_nothing(index_elements=['id']))
            refs=[{'id':uuid5(REFERENCE_NS,f'{release_id}:place:{r["geoid"]}'),
                'release_id':release_id,'jurisdiction_id':jids[r['geoid']], 'kind':'place',
                'geoid':r['geoid'],'state_fips':r['state_fips'],
                'name_raw':r['name_raw'],'name_key':r['name_key'],
                'vintage_start':2024,'vintage_end':2024,
                'source_row_number':r['source_row_number'],
                'note':'2024 Census place only; no county allocation or historical extension'} for r in records]
            inserted=0
            for chunk in _chunks(refs):
                inserted+=len(conn.execute(pg_insert(GeographicReference.__table__).values(chunk)
                    .on_conflict_do_nothing(index_elements=['release_id','kind','geoid'])
                    .returning(GeographicReference.id)).all())
            for chunk in _chunks([{'id':uuid5(REFERENCE_NS,f'identifier:{r["id"]}'),
                'jurisdiction_id':r['jurisdiction_id'],'reference_id':r['id'],
                'scheme':'CENSUS_PLACE_GEOID','value':r['geoid']} for r in refs]):
                conn.execute(pg_insert(JurisdictionIdentifier.__table__).values(chunk)
                    .on_conflict_do_nothing(index_elements=['reference_id','scheme']))
            for chunk in _chunks([{'id':uuid5(REFERENCE_NS,f'relationship:{r["id"]}'),
                'parent_id':stable_jurisdiction_id('state',r['state_fips'],''),
                'child_id':r['jurisdiction_id'],'reference_id':r['id'],'relationship':'contains'} for r in refs]):
                conn.execute(pg_insert(JurisdictionRelationship.__table__).values(chunk)
                    .on_conflict_do_nothing(index_elements=['reference_id']))
            now=datetime.now(timezone.utc)
            elapsed=int((now-(started_at or now)).total_seconds()*1000)
            conn.execute(update(IngestionRun.__table__).where(IngestionRun.id==run_id).values(
                release_id=release_id,status='SUCCEEDED',records_read=frame.height,
                records_inserted=inserted,records_updated=0,records_rejected=0,
                warnings_json=[],errors_json=[],raw_sha256=asset.sha256,
                completed_at=now,duration_ms=max(0,elapsed)))
        return {'release_id':str(release_id),'records_inserted':inserted,
            'records_already_present':len(refs)-inserted,'place_rows':len(refs),**validation}
