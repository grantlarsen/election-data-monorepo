"""Prepare a pinned physical-water display layer, independent of election geography."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from ingestion.source import SourceInfo, acquire

URL = 'https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes.zip'
SHA256 = '0803a06f9c3cb4671d89b68c48b142aad9366ba40f665245e12a913fbc61722a'
LAKES = {'Lake Superior', 'Lake Michigan', 'Lake Huron', 'Lake Erie', 'Lake Ontario', 'Lake Saint Clair'}


def prepare(data_dir: Path, output: Path) -> None:
    import shapefile
    info = SourceInfo('natural_earth_lakes', '', '5.0.0', 1, 'ne_10m_lakes.zip', URL, None, None, {})
    source = acquire(SimpleNamespace(key=info.source_name, describe=lambda: info), data_dir)
    if source.sha256 != SHA256:
        raise ValueError('Physical lake archive checksum differs')
    with ZipFile(source.path) as archive:
        if archive.read('ne_10m_lakes.VERSION.txt').decode().strip() != '5.0.0':
            raise ValueError('Unexpected physical lake version')
        reader = shapefile.Reader(shp=io.BytesIO(archive.read('ne_10m_lakes.shp')),
            dbf=io.BytesIO(archive.read('ne_10m_lakes.dbf')))
        features = [dict(type='Feature', properties={'name': row.record.as_dict()['name']},
                         geometry=row.shape.__geo_interface__)
                    for row in reader.iterShapeRecords() if row.record.as_dict()['name'] in LAKES]
    if {f['properties']['name'] for f in features} != LAKES or len(features) != 6:
        raise ValueError('Expected exactly six Great Lakes system polygons')
    features.sort(key=lambda f: f['properties']['name'])
    payload = dict(type='FeatureCollection', source=dict(name='Natural Earth lakes', version='5.0.0',
        url=URL, sha256=SHA256, retrieved_at=source.retrieved_at.isoformat(),
        documentation='https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-lakes/',
        role='Physical cartographic water mask; not historical jurisdiction or election geography'), features=features)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=Path('data/ingestion'))
    args = parser.parse_args()
    prepare(args.data_dir, args.output)
