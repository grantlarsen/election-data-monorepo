"""Regression tests for PostgreSQL bulk-insert reporting.

Run inside the Docker api service, where the existing DB_* variables are set.
No PostgreSQL connection is needed for these tests.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from ingestion.loader import insert_observation_chunk


class FakeResult:
    # The -1 simulates the DBAPI behavior that caused the original bug.
    rowcount = -1

    def __init__(self, inserted: int) -> None:
        self.inserted = inserted

    def all(self) -> list[tuple]:
        return [(uuid4(),) for _ in range(self.inserted)]


class FakeConnection:
    def __init__(self, inserted: int) -> None:
        self.inserted = inserted
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return FakeResult(self.inserted)


@pytest.mark.parametrize("actual_inserted", [0, 1, 3])
def test_counts_returning_rows_not_unavailable_rowcount(actual_inserted: int) -> None:
    conn = FakeConnection(actual_inserted)
    rows = [
        {"id": uuid4(), "release_id": uuid4(), "source_row_number": 1},
        {"id": uuid4(), "release_id": uuid4(), "source_row_number": 2},
        {"id": uuid4(), "release_id": uuid4(), "source_row_number": 3},
    ]

    assert insert_observation_chunk(conn, rows) == actual_inserted
    sql = str(conn.statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql
    assert "RETURNING" in sql
