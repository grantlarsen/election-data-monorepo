"""Run the regression suite on isolated schemas in DB_NAME + '_test'."""
import os
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
name = os.environ['DB_NAME'] + '_test'
url = URL.create('postgresql+psycopg', username=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD'], host=os.getenv('DB_HOST','db'),
    port=int(os.getenv('DB_PORT','5432')), database=name)
if '--create-test-db' in sys.argv:
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        if not conn.scalar(text('SELECT 1 FROM pg_database WHERE datname=:db'), {'db':name}):
            conn.execute(text(f'CREATE DATABASE {admin.dialect.identifier_preparer.quote(name)}'))
    admin.dispose()
test = create_engine(url)
with test.begin() as conn:
    conn.execute(text('CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public'))
test.dispose()
os.environ['TEST_DATABASE_URL'] = url.render_as_string(hide_password=False)
paths = [p for p in sys.argv[1:] if p != '--create-test-db'] or ['tests']
raise SystemExit(pytest.main(['-q', *paths, '--junitxml=/app/data/data004/pytest.xml']))
