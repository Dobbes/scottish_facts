from pathlib import Path

import pytest
from pgvector import Vector

from scotland_facts.db import Database
from scotland_facts.models import HISTORY_STATUSES


class Cursor:
    def __init__(self, rows=None, rowcount=1):
        self.rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class CaptureConnection:
    def __init__(self, rows=None, rowcount=1):
        self.calls = []
        self.rows = rows or []
        self.rowcount = rowcount
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        return Cursor(self.rows, self.rowcount)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_history_queries_include_send_attempted_and_exclude_dry_failed():
    conn = CaptureConnection()
    db = Database(conn)
    db.recent_subjects(14)
    sql, params = conn.calls[-1]
    assert set(params[0]) == set(HISTORY_STATUSES)
    assert "DRY_RUN" not in params[0]
    assert "FAILED" not in params[0]
    assert "interval '1 day'" in sql


def test_semantic_query_uses_cosine_distance_top_five_and_history_statuses():
    conn = CaptureConnection()
    db = Database(conn)
    db.nearest_facts([0.1, 0.2], 5)
    sql, params = conn.calls[-1]
    assert "embedding <=> %s" in sql
    assert "1 - (embedding <=> %s)" in sql
    assert params[-1] == 5
    assert set(params[1]) == set(HISTORY_STATUSES)
    assert isinstance(params[0], Vector)
    assert isinstance(params[2], Vector)


def test_send_attempt_transition_is_committed():
    conn = CaptureConnection()
    db = Database(conn)
    db.mark_send_attempted("fact-id")
    assert conn.commits == 1
    assert "status = 'SEND_ATTEMPTED'" in conn.calls[0][0]
    assert "status = 'PENDING'" in conn.calls[0][0]


def test_ineligible_send_attempt_rolls_back_and_raises():
    conn = CaptureConnection(rowcount=0)
    db = Database(conn)
    with pytest.raises(RuntimeError, match="not eligible"):
        db.mark_send_attempted("fact-id")
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_migration_defines_required_schema_and_indexes():
    sql = Path("migrations/001_initial.sql").read_text(encoding="utf-8")
    assert sql.startswith("create schema if not exists extensions;\ncreate extension if not exists vector")
    assert sql.index("generation_runs") < sql.index("facts") < sql.index("generation_attempts")
    assert "extensions.vector(1536)" in sql
    assert "using hnsw" in sql
    assert "extensions.vector_cosine_ops" in sql
    assert "SEND_ATTEMPTED', 'SUBMITTED', 'SENT', 'DELIVERED" in sql
