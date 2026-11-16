"""Extract an existing checksum-verified evidence archive into a new directory."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil


def main():
    from pypdf import PdfReader, __version__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--supplement', type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    inputs = [args.archive] + ([args.supplement] if args.supplement else [])
    pairs = [(directory, r) for directory in inputs for r in
             json.loads((directory / 'retrievals.json').read_text(encoding='utf-8'))]
    records = [r for _, r in pairs]
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('Duplicate evidence IDs')
    for directory, record in pairs:
        if not record['success']:
            continue
        source = directory / record['file']
        if sha256(source.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Raw evidence checksum differs')
        shutil.copyfile(source, args.output_dir / record['file'])
        if source.suffix != '.pdf':
            continue
        reader = PdfReader(source)
        pages = [{'page': n, 'text': page.extract_text(extraction_mode='layout') or '',
                  'plain_text': page.extract_text() or ''}
                 for n, page in enumerate(reader.pages, 1)]
        name = source.name + '.pages.json'
        data = (json.dumps(pages, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        (args.output_dir / name).write_bytes(data)
        record.update(text_file=name, text_sha256=sha256(data).hexdigest(), pages=len(pages),
                      extraction=f'pypdf {__version__}; layout and plain text; no OCR')
    (args.output_dir / 'retrievals.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'records': len(records), 'successful_retrievals': sum(r['success'] for r in records)}))


if __name__ == '__main__':
    main()
