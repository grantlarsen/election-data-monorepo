"""Shared pytest environment configuration."""

import os

# Provide defaults for unit tests that import SQLAlchemy models.
# These values are not used to connect to PostgreSQL.

os.environ.setdefault("DB_USER", "pytest_user")
os.environ.setdefault("DB_PASSWORD", "pytest_password")
os.environ.setdefault("DB_NAME", "pytest_db")
# Tests opt into scheduler execution explicitly; ordinary TestClients stay offline.
os.environ.setdefault("SENATE_RESULTS_AUTO_REFRESH", "0")
