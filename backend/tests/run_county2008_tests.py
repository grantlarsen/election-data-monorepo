"""Run the current full suite with research dependencies in DB_NAME + '_test'.

The explicit --install-research option installs optional parsers into the
disposable container. No production dependencies or live data are changed.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--install-research',action='store_true')
args,extra=parser.parse_known_args()
root=Path(__file__).resolve().parents[1]
if args.install_research:
    subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check',
                    '--root-user-action=ignore','-r',str(root/'requirements-research.txt')],check=True)
sys.argv=[str(root/'tests/run_geo002_tests.py'),*(extra or ['tests','--tb=short'])]
def hashes():
    files=[p for d in ('app','ingestion','tests','migrations') for p in (root/d).rglob('*.py')]
    return {p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
before=hashes()
try:
    runpy.run_path(str(root/'tests/run_geo002_tests.py'),run_name='__main__')
except SystemExit:
    output=Path(os.getenv('GEO002_TEST_OUTPUT','/app/data/geo002/tests'))
    if output.exists():
        after=hashes()
        (output/'test-source-hashes.json').write_text(json.dumps(dict(before=before,after=after,
            source_unchanged_during_tests=before==after),indent=2)+'\n',encoding='utf-8')
        if before!=after:
            raise RuntimeError('Implementation changed during the test run')
    raise
