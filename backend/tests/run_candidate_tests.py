"""Run candidate/identity/API tests in a guarded disposable PostgreSQL database.

Run in the API environment: python tests/run_candidate_tests.py --create-test-db
Extra pytest arguments can be supplied after the optional creation flag.
"""
import os
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
base = os.environ["DB_NAME"]
name = base + "_test"
if not name.endswith("_test") or name == base:
    raise RuntimeError("Refusing non-test database")
url = URL.create("postgresql+psycopg", username=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
    host=os.getenv("DB_HOST", "db"), port=int(os.getenv("DB_PORT", "5432")), database=name)
if "--create-test-db" in sys.argv:
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            if not connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}):
                connection.execute(text(f"CREATE DATABASE {admin.dialect.identifier_preparer.quote(name)}"))
                print(f"Created disposable database {name}")
    finally:
        admin.dispose()
os.environ["TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
arguments = [a for a in sys.argv[1:] if a != "--create-test-db"]
raise SystemExit(pytest.main(arguments or ["-q", "tests/test_candidate_identity.py", "tests/test_candidate_migration.py",
    "tests/test_candidate_results.py", "tests/test_identity.py", "tests/test_identity_migration.py",
    "tests/test_election_api.py", "tests/test_election_api_contract.py"]))
