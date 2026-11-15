"""Capture read-only CLI and schema checks with unambiguous process exit codes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from app.services.geo002_review import read, write


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['schema', 'cli'])
    p.add_argument('--output-dir', type=Path, default=Path('/app/data/geo002'))
    args = p.parse_args()
    out = args.output_dir
    if args.phase == 'schema':
        results = []
        for operation in ['current', 'check']:
            env = {**os.environ, 'PGOPTIONS': '-c default_transaction_read_only=on'}
            run = subprocess.run(['alembic', operation], capture_output=True, text=True, env=env)
            write(out / f'schema-{operation}.json', {'exit_code': run.returncode,
                'stdout': run.stdout, 'stderr': run.stderr})
            results.append({'operation': operation, 'exit_code': run.returncode})
        if any(r['exit_code'] for r in results):
            raise RuntimeError('Read-only schema verification failed')
        print(json.dumps(results))
        return
    package = read(out / 'approval-manifest.json')
    cli_dir = out / 'cli'
    cli_dir.mkdir(exist_ok=False)
    summaries = []
    for scope in package['routine'] + package['bedford_separate']:
        label = Path(scope['manifest_file']).stem
        files_before = set((cli_dir / 'geography').glob('resolution-*.json'))
        run = subprocess.run([sys.executable, '-m', 'ingestion', 'geo', 'compare',
            '--vintage', str(scope['vintage']), '--context-file', str(out / scope['context_file']),
            '--publication-manifest', str(out / scope['manifest_file']),
            '--output', str(cli_dir / f'{label}.csv')], capture_output=True, text=True,
            env={**os.environ, 'INGESTION_DATA_DIR': str(cli_dir)})
        write(cli_dir / f'{label}-process.json', {'exit_code': run.returncode,
            'stdout': run.stdout, 'stderr': run.stderr})
        if run.returncode:
            raise RuntimeError(f'CLI subset replay failed: {label}')
        added = set((cli_dir / 'geography').glob('resolution-*.json')) - files_before
        if len(added) != 1:
            raise RuntimeError('Expected one CLI report')
        report = read(added.pop())
        if report['publication_sha256'] != scope['publication_sha256'] or report['published'] \
                or report['records_inserted'] or report['publication_target_count'] != scope['target_count']:
            raise RuntimeError('CLI subset mismatch')
        summaries.append({'scope': label, 'context_sha256': report['context_sha256'],
            'publication_sha256': report['publication_sha256'],
            'targets': report['publication_target_count'], 'published': False, 'inserted': 0,
            'votes_unchanged': report['vote_totals_unchanged'],
            'downgrades': report['publication_downgrades'], 'reassignments': report['publication_reassignments']})
    write(out / 'cli-replays.json', summaries)
    print(json.dumps(summaries))


if __name__ == '__main__':
    main()
