"""Pinned preparation, explicit exclusions, deterministic replay and fail-closed output."""
import hashlib
import io
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
import shapefile

from ingestion import boundaries
from ingestion.medsl import STATE_FIPS


def archive(path, level):
    streams = [io.BytesIO() for _ in range(3)]
    writer = shapefile.Writer(shp=streams[0], shx=streams[1], dbf=streams[2], encoding="latin1")
    writer.field('STATEFP', 'C', 2)
    if level == 'county':
        writer.field('COUNTYFP', 'C', 3)
    writer.field('NAME', 'C', 30)
    for fips in [*STATE_FIPS.values(), '72']:
        writer.poly([[[-87,32],[-87,33],[-86,33],[-87,32]]])
        writer.record(*([fips, '001', 'Cañon'] if level == 'county' else [fips, 'State']))
    writer.close()
    with ZipFile(path, 'w') as target:
        stem = f'tl_2008_us_{level}'
        for stream, suffix in zip(streams, ['.shp','.shx','.dbf']):
            target.writestr(stem + suffix, stream.getvalue())
        target.writestr(stem + '.prj', 'GEOGCS["GCS_North_American_1983",UNIT["Degree",0.017453292519943295]]')


def test_preparation_replay_corruption_and_source_pins(tmp_path, monkeypatch):
    files = {}
    for level in ['state', 'county']:
        path = tmp_path / f'{level}.zip'
        archive(path, level)
        files[level] = path
    pins = {level: hashlib.sha256(path.read_bytes()).hexdigest() for level, path in files.items()}
    monkeypatch.setattr(boundaries, 'SOURCES', pins)
    def acquire(adapter, data_dir):
        info = adapter.describe()
        level = info.metadata['level']
        return SimpleNamespace(path=files[level], sha256=hashlib.sha256(files[level].read_bytes()).hexdigest(),
                               retrieved_at=SimpleNamespace(isoformat=lambda: '2026-11-16T00:00:00+00:00'))
    monkeypatch.setattr(boundaries, 'acquire', acquire)
    class Connection:
        fail = False
        def execute(self, query, params):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: dict(original_valid=True,
                valid=not self.fail, empty=False, geometry=json.loads(params['raw']))))
    connection = Connection()
    output = tmp_path / 'output'
    result = boundaries.prepare(connection, data_dir=tmp_path, output=output)
    assert result['status'] == 'prepared' and result['counties'] == 51
    manifest_path = output / '2008.json'
    original = manifest_path.read_bytes()
    timestamp = manifest_path.stat().st_mtime_ns
    manifest = json.loads(original)
    assert manifest['excluded_territory_features'] == dict(state=1, county=1)
    assert manifest['source_crs'] == 'EPSG:4269' and manifest['crs'] == 'EPSG:4326'
    assert boundaries.prepare(connection, data_dir=tmp_path, output=output)['status'] == 'unchanged'
    assert manifest_path.stat().st_mtime_ns == timestamp
    connection.fail = True
    with pytest.raises(ValueError, match='Invalid display polygon'):
        boundaries.prepare(connection, data_dir=tmp_path, output=output)
    assert manifest_path.read_bytes() == original
    connection.fail = False
    monkeypatch.setattr(boundaries, 'SOURCES', dict(pins, state='0'*64))
    with pytest.raises(ValueError, match='checksum differs'):
        boundaries.prepare(connection, data_dir=tmp_path, output=output)
    assert manifest_path.read_bytes() == original
    monkeypatch.setattr(boundaries, 'SOURCES', pins)
    item = manifest['outputs']['state']
    (output / 'objects' / f"{item['object']}.json").write_text('{}')
    with pytest.raises(ValueError, match='verification'):
        boundaries.prepare(connection, data_dir=tmp_path, output=output)
