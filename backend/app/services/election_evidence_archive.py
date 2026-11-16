"""Archive public election evidence without touching ingestion/database records.

Raw bytes are content addressed; an existing archive is verified, never replaced.
PDF extraction requires pypdf (research-only dependency).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode


def archive(item, output, extract=True):
    record = {**item, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
    try:
        form = item.get('post_fields')
        request = Request(item['url'], data=urlencode(form).encode() if form is not None else None,
                          headers={'User-Agent': 'Mozilla/5.0 (historical election reconciliation)'})
        with urlopen(request, timeout=45) as response:
            body = response.read()
            record.update(http_status=response.status, final_url=response.url,
                          content_type=response.headers.get('Content-Type'))
        digest = sha256(body).hexdigest()
        suffix = '.pdf' if body.startswith(b'%PDF') else '.raw'
        filename = f"{item['id']}-{digest[:16]}{suffix}"
        path = output / filename
        if path.exists():
            if sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Existing evidence archive is corrupt')
        else:
            with path.open('xb') as stream:
                stream.write(body)
        record.update(file=filename, sha256=digest, bytes=len(body),
                      success=record['http_status'] == 200 and bool(body))
        if b'captcha' in body[:3000].lower() or b'<title>access denied' in body[:3000].lower():
            record.update(success=False, error='HTML challenge/access denial; archived response is not election evidence')
        if suffix == '.pdf' and record['success'] and extract:
            from pypdf import PdfReader
            reader = PdfReader(path)
            pages = [{'page': n, 'text': page.extract_text(extraction_mode='layout') or ''}
                     for n, page in enumerate(reader.pages, 1)]
            record.update(pages=len(pages), extraction='pypdf layout; no OCR')
            extraction = output / (filename + '.pages.json')
            encoded = (json.dumps(pages, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            if extraction.exists() and extraction.read_bytes() != encoded:
                raise ValueError('Existing extraction differs; use a new evidence directory')
            extraction.write_bytes(encoded)
            record.update(text_file=extraction.name, text_sha256=sha256(encoded).hexdigest())
    except Exception as exc:
        record.update(success=False, error=str(exc))
        if isinstance(exc, HTTPError):
            record['http_status'] = exc.code
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('requests', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--download-only', action='store_true')
    args = parser.parse_args()
    if not args.download_only:
        import pypdf  # Fail before downloading if the research dependency is absent.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    items = json.loads(args.requests.read_text(encoding='utf-8'))
    if len({x['id'] for x in items}) != len(items):
        raise ValueError('Duplicate evidence IDs')
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda item: archive(item, args.output_dir, not args.download_only), items))
    (args.output_dir / 'retrievals.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    print(json.dumps([{k: r[k] for k in ('id', 'success', 'bytes', 'error') if k in r} for r in records]))


if __name__ == '__main__':
    main()
