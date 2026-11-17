"""Pinned preparation, explicit exclusions, deterministic replay and fail-closed output."""
import hashlib
from copy import deepcopy
import io
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
import shapefile

from ingestion import boundaries
from ingestion.medsl import STATE_FIPS
from app.services.election_map import load_boundaries
from app.services.canonical_results import MaterializationError


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


@pytest.mark.parametrize('year', [2000, 2004, 2012, 2016, 2020, 2024])
def test_presidential_vintages_historical_fields_state_selection_and_replay(tmp_path, monkeypatch, year):
    config = deepcopy(boundaries.configuration(year, 'president'))
    config['expected_counties'] = 51
    files = {}
    for index, spec in enumerate(config['sources']):
        streams = [io.BytesIO() for _ in range(3)]
        writer = shapefile.Writer(shp=streams[0], shx=streams[1], dbf=streams[2], encoding='latin1')
        writer.field(spec.get('state_field', 'STATEFP'), 'C', 2)
        if spec['level'] == 'county':
            writer.field(spec.get('county_field', 'COUNTYFP'), 'C', 3)
        writer.field(spec.get('name_field', 'NAME'), 'C', 30)
        for fips in [*STATE_FIPS.values(), '72']:
            writer.poly([[[-87,32],[-87,33],[-86,33],[-87,32]]])
            writer.record(*([fips, '001', 'County'] if spec['level'] == 'county' else [fips, 'State']))
        writer.close()
        path = tmp_path / f'{index}.zip'
        with ZipFile(path, 'w') as target:
            stem = spec['filename'][:-4]
            for stream, suffix in zip(streams, ['.shp', '.shx', '.dbf']):
                target.writestr(stem + suffix, stream.getvalue())
            target.writestr(stem + '.prj', 'GEOGCS["North_American_1983",UNIT["Degree",1]]')
        spec['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        files[spec['filename']] = path
    monkeypatch.setattr(boundaries, 'configuration', lambda y, office: config)
    def acquire(adapter, data_dir):
        path = files[adapter.describe().filename]
        return SimpleNamespace(path=path, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            retrieved_at=SimpleNamespace(isoformat=lambda: '2026-11-16T00:00:00+00:00'))
    monkeypatch.setattr(boundaries, 'acquire', acquire)
    connection = SimpleNamespace(execute=lambda query, params: SimpleNamespace(mappings=lambda: SimpleNamespace(
        one=lambda: dict(original_valid=True, valid=True, empty=False, geometry=json.loads(params['raw'])))))
    output = tmp_path / 'display'
    result = boundaries.prepare(connection, data_dir=tmp_path, output=output, year=year, office='president')
    assert result['counties'] == 51 and result['states'] == 51
    monkeypatch.setenv('BOUNDARY_DATA_DIR', str(output))
    metadata, features = load_boundaries(None, year, 'state')
    assert len(features) == 51 and metadata['year'] == year
    assert len(load_boundaries('NY', year, 'county')[1]) == 1
    assert len(load_boundaries('AK', year, 'county')[1]) == 1  # No duplicate Alaska features in the 2004 composite.
    assert bool(metadata.get('approximate')) == (year == 2004)
    manifest = (output / f'{year}.json').read_bytes()
    replay = boundaries.prepare(connection, data_dir=tmp_path, output=output, year=year, office='president')
    assert replay['status'] == 'unchanged'
    assert (output / f'{year}.json').read_bytes() == manifest
    config['expected_counties'] = 52
    with pytest.raises(ValueError, match='count differs'):
        boundaries.prepare(connection, data_dir=tmp_path, output=output, year=year, office='president')
    assert (output / f'{year}.json').read_bytes() == manifest


def test_same_year_layers_preserve_house_objects_sources_and_replays(tmp_path, monkeypatch):
    output = tmp_path
    (output / 'objects').mkdir()
    objects = {}
    for level, geoid in [('state', '36'), ('county', '36001'), ('congressional_district', '3614')]:
        payload = json.dumps(dict(type='FeatureCollection', features=[dict(type='Feature', id=geoid,
            properties=dict(geoid=geoid, state_code='NY', name=level),
            geometry=dict(type='Polygon', coordinates=[]))])).encode()
        digest = hashlib.sha256(payload).hexdigest()
        (output / 'objects' / f'{digest}.json').write_bytes(payload)
        objects[level if level == 'state' else f'{level}:NY'] = dict(object=digest, sha256=digest, count=1, repaired=0)
    house = dict(version='tiger2024-display-v1', year=2024, reporting_levels=['congressional_district'],
        boundary_vintage='119th Congress', sources=[{'url':'https://www.census.gov/house'}],
        outputs={key: value for key, value in objects.items() if key.startswith('congressional_district')})
    president = dict(version=house['version'], year=2024, reporting_levels=['state', 'county'],
        boundary_vintage='2024-01-01', sources=[{'url':'https://www.census.gov/counties'}],
        outputs={key: value for key, value in objects.items() if not key.startswith('congressional_district')})
    combined = boundaries.merge_manifest(house, president)
    assert combined['outputs'] == objects
    assert boundaries.merge_manifest(combined, house) == combined
    assert boundaries.merge_manifest(combined, president) == combined
    (output / '2024.json').write_text(json.dumps(combined))
    monkeypatch.setenv('BOUNDARY_DATA_DIR', str(output))
    house_meta, house_shapes = load_boundaries('NY', 2024, 'congressional_district')
    assert house_shapes[0]['id'] == '3614' and house_meta['sources'] == house['sources']
    state_meta, state_shapes = load_boundaries(None, 2024, 'state')
    assert state_shapes[0]['id'] == '36' and state_meta['sources'] == president['sources']
    assert state_meta['boundary_vintage'] == '2024-01-01'
    combined['layers']['state']['year'] = 2008
    (output / '2024.json').write_text(json.dumps(combined))
    with pytest.raises(MaterializationError):
        load_boundaries(None, 2024, 'state')
    with pytest.raises(ValueError, match='incompatible year'):
        boundaries.merge_manifest(house, dict(president, year=2008))
