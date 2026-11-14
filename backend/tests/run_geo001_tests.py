"""Run tests only in isolated schemas of the disposable DB_NAME + '_test'."""
import os
import importlib.util
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

if importlib.util.find_spec('pytest') is None:
    subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check',
                    '--root-user-action=ignore','pytest>=8,<10'],check=True)
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
name = os.environ['DB_NAME'] + '_test'
assert name.endswith('_test')
url = URL.create('postgresql+psycopg', username=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD'], host=os.getenv('DB_HOST','db'),
    port=int(os.getenv('DB_PORT','5432')), database=name)
admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
with admin.connect() as c:
    if not c.scalar(text('SELECT 1 FROM pg_database WHERE datname=:db'), {'db':name}):
        c.execute(text(f'CREATE DATABASE {admin.dialect.identifier_preparer.quote(name)}'))
admin.dispose()
os.environ['TEST_DATABASE_URL'] = url.render_as_string(hide_password=False)
raise SystemExit(pytest.main(['-q', 'tests', '--junitxml=/app/data/geo001/pytest.xml']))
