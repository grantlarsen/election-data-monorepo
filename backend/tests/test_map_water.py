"""Physical cartography preparation never alters election boundary identities."""
from datetime import datetime, timezone
import io
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
import shapefile

from ingestion import map_water


def test_water_asset_is_pinned_complete_and_reproducible(tmp_path, monkeypatch):
    streams = [io.BytesIO() for _ in range(3)]
    writer = shapefile.Writer(shp=streams[0], shx=streams[1], dbf=streams[2])
    writer.field('name', 'C', 40)
    for name in sorted(map_water.LAKES | {'Unselected water'}):
        writer.poly([[[-87,43],[-87,44],[-86,44],[-87,43]]])
        writer.record(name)
    writer.close()
    archive_path = tmp_path / 'lakes.zip'
    with ZipFile(archive_path, 'w') as archive:
        for stream, suffix in zip(streams, ['.shp','.shx','.dbf']):
            archive.writestr('ne_10m_lakes' + suffix, stream.getvalue())
        archive.writestr('ne_10m_lakes.VERSION.txt', '5.0.0\r\n')
    source = SimpleNamespace(path=archive_path, sha256=map_water.SHA256,
                             retrieved_at=datetime(2026,11,16,tzinfo=timezone.utc))
    monkeypatch.setattr(map_water, 'acquire', lambda *args: source)
    output = tmp_path / 'display.json'
    map_water.prepare(tmp_path, output)
    original = output.read_bytes()
    asset = json.loads(original)
    assert len(asset['features']) == 6
    assert {f['properties']['name'] for f in asset['features']} == map_water.LAKES
    assert asset['source']['sha256'] == map_water.SHA256
    assert 'not historical jurisdiction' in asset['source']['role']
    map_water.prepare(tmp_path, output)
    assert output.read_bytes() == original
    source.sha256 = '0' * 64
    with pytest.raises(ValueError, match='checksum differs'):
        map_water.prepare(tmp_path, output)
    assert output.read_bytes() == original
