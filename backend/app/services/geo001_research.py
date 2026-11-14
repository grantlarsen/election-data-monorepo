"""Archive explicit public source URLs for GEO-001 with byte-level checksums.

python -m app.services.geo001_research /app/data/geo001/research-requests.json
Downloads are local evidence only. No database access or ingestion is performed.
PDF text extraction is optional: install pypdf in a disposable container first.
Failed requests are retained as research gaps, never treated as source evidence.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('requests', type=Path)
    p.add_argument('--output-dir', type=Path, default=Path('/app/data/geo001/research'))
    p.add_argument('--extract-only', action='store_true')
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    requests = json.loads(args.requests.read_text(encoding='utf-8'))
    if args.extract_only:
        try:
            import pypdf
        except ImportError:
            subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check',
                            '--root-user-action=ignore','pypdf>=6,<7'],check=True)
        from pypdf import PdfReader
        extracted = []
        for path in sorted(args.output_dir.glob('*.pdf')):
            try:
                pages = PdfReader(path).pages
                txt = '\n\n'.join(f'PAGE {n}\n' + (page.extract_text() or '') for n,page in enumerate(pages,1))
                path.with_suffix('.txt').write_text(txt, encoding='utf-8')
                extracted.append({'file':path.name,'pages':len(pages),'text_sha256':sha256(txt.encode()).hexdigest()})
            except Exception as exc:
                extracted.append({'file':path.name,'error':str(exc)})
        (args.output_dir/'extractions.json').write_text(json.dumps(extracted,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(extracted))
        return
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    previous_path = args.output_dir / 'retrievals.json'
    previous = {r['id']:r for r in json.loads(previous_path.read_text())} if previous_path.exists() else {}

    def fetch(item):
        cached = previous.get(item['id'],{})
        if cached.get('success') and cached.get('url') == item['url']:
            path = args.output_dir / cached['file']
            if path.is_file() and sha256(path.read_bytes()).hexdigest() == cached['sha256']:
                return cached
        result = {**item, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
        try:
            req = Request(item['url'], headers={'User-Agent':'Mozilla/5.0 (GEO-001 evidence audit)'})
            with urlopen(req, timeout=25) as r:
                body = r.read()
                result.update(http_status=r.status, final_url=r.url, content_type=r.headers.get('Content-Type'))
            suffix = '.pdf' if body.startswith(b'%PDF') else '.html'
            path = args.output_dir / (item['id'] + suffix)
            path.write_bytes(body)
            result.update(file=path.name, bytes=len(body), sha256=sha256(body).hexdigest(), success=True)
            if suffix == '.pdf' and PdfReader:
                pages = PdfReader(path).pages
                txt = '\n\n'.join(f'PAGE {n}\n' + (page.extract_text() or '') for n,page in enumerate(pages,1))
                path.with_suffix('.txt').write_text(txt, encoding='utf-8')
                result['text_file'] = path.with_suffix('.txt').name
                result['pages'] = len(pages)
        except Exception as exc:
            result.update(success=False, error=str(exc))
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, requests))
    (args.output_dir / 'retrievals.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    for r in results:
        print(json.dumps({k:r[k] for k in ('id','success','bytes','error') if k in r}))


if __name__ == '__main__':
    main()
