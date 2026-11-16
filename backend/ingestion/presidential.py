"""Prepare pinned FEC workbooks, preview/publish state summaries, or audit coverage.

Run from backend: python -m ingestion.presidential --help
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from ingestion.presidential_state_returns import digest, extract_summary
from ingestion.source import _request, atomic_json, sha256_file


def prepare(catalog: Path, directory: Path, *, download: bool = False) -> list[dict]:
    directory.mkdir(parents=True, exist_ok=True)
    receipts = []
    for pinned in json.loads(catalog.read_text(encoding='utf-8')):
        spec = dict(pinned)
        raw = directory / spec['filename']
        retrieval = raw.with_suffix(raw.suffix + '.retrieval.json')
        if not raw.exists() and download:
            part = raw.with_suffix(raw.suffix + '.part')
            try:
                response = _request(spec['url'], destination=part)
                if response is not None or sha256_file(part) != spec['sha256']:
                    raise ValueError('Downloaded FEC workbook differs from pinned checksum')
                part.replace(raw)
                atomic_json(retrieval, dict(sha256=spec['sha256'], url=spec['url'],
                                            retrieved_at=datetime.now(timezone.utc).isoformat()))
            finally:
                part.unlink(missing_ok=True)
        if sha256_file(raw) != spec['sha256']:
            raise ValueError('Pinned FEC workbook checksum mismatch')
        if retrieval.exists():
            record = json.loads(retrieval.read_text(encoding='utf-8'))
            if record['sha256'] != spec['sha256'] or record['url'] != spec['url']:
                raise ValueError('FEC retrieval metadata differs')
            spec['retrieved_at'] = record['retrieved_at']
        package = extract_summary(raw, spec)
        output = directory / f"{spec['year']}-state-summary.json"
        if output.exists() and json.loads(output.read_text(encoding='utf-8')) != package:
            raise ValueError('Refusing to overwrite a different prepared FEC package')
        atomic_json(output, package)
        receipts.append(dict(year=spec['year'], package_sha256=digest(package),
                             votes=spec['national_votes'], states=51))
    return receipts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--catalog', type=Path, required=True)
    prep.add_argument('--directory', type=Path, required=True)
    prep.add_argument('--download', action='store_true')
    audit = commands.add_parser('inventory')
    audit.add_argument('--output', type=Path, required=True)
    state = commands.add_parser('state')
    state.add_argument('--directory', type=Path, required=True)
    state.add_argument('--year', type=int, required=True)
    state.add_argument('--publish', action='store_true')
    state.add_argument('--expected-fingerprint')
    state.add_argument('--actor')
    state.add_argument('--authorization-note')
    state.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        print(json.dumps(prepare(args.catalog, args.directory, download=args.download), indent=2))
        return 0
    from sqlalchemy import text
    from app.database import SessionLocal
    with SessionLocal() as session, session.begin():
        writing = args.command == 'state' and args.publish
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ' + ('' if writing else ' READ ONLY')))
        if args.command == 'inventory':
            from app.services.presidential_coverage import inventory
            report = inventory(session)
        else:
            from app.services.presidential_state_returns import projection, publish
            package = json.loads((args.directory / f'{args.year}-state-summary.json').read_text(encoding='utf-8'))
            if package['year'] != args.year:
                raise ValueError('Prepared package year differs from requested election')
            if writing:
                if not args.expected_fingerprint or not args.actor or not args.authorization_note:
                    parser.error('Publication requires fingerprint, actor and authorization note')
                report = publish(session, package, args.directory, expected_fingerprint=args.expected_fingerprint,
                                 actor=args.actor, authorization_note=args.authorization_note)
            else:
                plan = projection(session, package, args.directory)
                report = dict(action='PREVIEW_ONLY', year=args.year, fingerprint=plan['fingerprint'],
                              manifest=plan['manifest'])
    atomic_json(args.output, report)
    print(json.dumps({k:v for k,v in report.items() if k != 'manifest'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
