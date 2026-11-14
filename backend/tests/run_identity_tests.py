"""Launch DATA-002 tests against an explicitly disposable PostgreSQL database.

Run inside the API container, where DB_* variables come from Docker Compose.
"""
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
base = os.environ["DB_NAME"]
test_name = f"{base}_test"
if not test_name.endswith("_test"):
    raise RuntimeError("refusing to run on non-test database")
url = URL.create("postgresql+psycopg", username=os.environ["DB_USER"],
                 password=os.environ["DB_PASSWORD"],
                 host=os.getenv("DB_HOST", "db"), port=int(os.getenv("DB_PORT", "5432")),
                 database=test_name)
if "--create-test-db" in sys.argv:
    admin_url = url.set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": test_name})
            if not exists:
                quoted = admin.dialect.identifier_preparer.quote(test_name)
                conn.execute(text(f"CREATE DATABASE {quoted}"))
                print(f"Created disposable database {test_name}")
    finally:
        admin.dispose()
os.environ["TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
sys.exit(pytest.main(["-q", "tests/test_identity.py", "tests/test_identity_migration.py"]))
