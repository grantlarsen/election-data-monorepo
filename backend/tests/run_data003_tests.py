"""DATA-003 tests using an explicitly disposable PostgreSQL database.

Run: python tests/run_data003_tests.py --create-test-db
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
name = os.environ['DB_NAME'] + '_test'
if not name.endswith('_test') or name == os.environ['DB_NAME']:
    raise RuntimeError('Refusing to touch a non-test database')
url = URL.create('postgresql+psycopg', username=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD'], host=os.getenv('DB_HOST', 'db'),
    port=int(os.getenv('DB_PORT', '5432')), database=name)
if '--create-test-db' in sys.argv:
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as c:
            exists = c.scalar(text('SELECT 1 FROM pg_database WHERE datname = :db'), {'db': name})
            if not exists:
                c.execute(text(f'CREATE DATABASE {admin.dialect.identifier_preparer.quote(name)}'))
                print(f'Created disposable PostgreSQL database {name}')
    finally:
        admin.dispose()
os.environ['TEST_DATABASE_URL'] = url.render_as_string(hide_password=False)
raise SystemExit(pytest.main(['-q','tests/test_data003_offline.py',
    'tests/test_data003_postgres.py']))
