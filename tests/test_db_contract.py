from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4

import pytest
from pgvector import Vector

from scotland_facts.db import Database
from scotland_facts.config import Settings
from scotland_facts.models import AttemptRecord, FactStatus


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
        self.in_transaction = False

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        return Cursor(self.rows, self.rowcount)

    def commit(self):
        assert not self.in_transaction, "No intermediate commit inside atomic acceptance"
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    @contextmanager
    def transaction(self):
        self.in_transaction = True
        try:
            yield
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1
        finally:
            self.in_transaction = False


@pytest.mark.parametrize("method,args", [
    ("category_order", ()), ("recent_subjects", (14,)), ("prior_facts", (50,)),
    ("recent_sms", (10,)), ("exact_duplicate", ("a fact",)),
    ("nearest_facts", ([1.0, 0.0],)),
])
def test_novelty_queries_include_every_persisted_status(method, args):
    conn = CaptureConnection()
    db = Database(conn)
    getattr(db, method)(*args)
    sql, _ = conn.calls[-1]
    assert "from facts" in sql
    assert "status" not in sql
    if method == "recent_subjects":
        assert "interval '1 day'" in sql


def test_semantic_query_uses_exact_cosine_distance_top_five():
    conn = CaptureConnection()
    db = Database(conn)
    db.nearest_facts([0.1, 0.2], 5)
    sql, params = conn.calls[-1]
    assert "embedding <=> %s" in sql
    assert "1 - (embedding <=> %s)" in sql
    assert params[-1] == 5
    assert isinstance(params[0], Vector)
    assert isinstance(params[1], Vector)
    assert "order by (embedding <=> %s) + 0" in sql


def candidate_record():
    return AttemptRecord(
        attempt_number=1, candidate_fact="A novel fact.", normalized_fact="a novel fact",
        category="castles", subjects=["novel castle"], source_url="https://example.org/fact",
        sources=[{"url": "https://example.org/fact"}],
    )


def test_acceptance_locks_before_fresh_checks_and_commits_fact_and_audit_together():
    conn = CaptureConnection()
    db = Database(conn)
    record = candidate_record()
    assert db.try_accept_fact(uuid4(), record, "SMS", [1.0, 0.0], FactStatus.DRY_RUN, Settings())
    statements = [sql for sql, _ in conn.calls]
    assert "read committed" in statements[0]
    assert "pg_advisory_xact_lock" in statements[1]
    assert statements[2].startswith("select subjects")
    assert statements[3].startswith("select id from facts")
    assert statements[4].startswith("select id, 1 -")
    assert statements[5].startswith("insert into facts")
    assert statements[6].startswith("insert into generation_attempts")
    assert record.accepted
    assert conn.commits == 2  # Finish speculative reads, then commit atomic acceptance.


@pytest.mark.parametrize("conflict", ["RECENT_SUBJECT", "EXACT_DUPLICATE", "SEMANTIC_DUPLICATE"])
def test_acceptance_rechecks_collisions_without_writing(monkeypatch, conflict):
    conn = CaptureConnection()
    db = Database(conn)
    record = candidate_record()
    monkeypatch.setattr(db, "recent_subjects", lambda _: ["novel castle"] if conflict == "RECENT_SUBJECT" else [])
    monkeypatch.setattr(db, "exact_duplicate", lambda _: uuid4() if conflict == "EXACT_DUPLICATE" else None)
    monkeypatch.setattr(db, "nearest_facts", lambda _: [(uuid4(), 0.95)])
    assert db.try_accept_fact(uuid4(), record, "SMS", [1.0, 0.0], FactStatus.DRY_RUN, Settings()) is None
    assert record.rejection_code == conflict
    assert not record.accepted
    assert not any("insert into" in sql for sql, _ in conn.calls)


def test_acceptance_rolls_back_fact_if_audit_write_fails(monkeypatch):
    conn = CaptureConnection()
    db = Database(conn)
    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit write failed")
    monkeypatch.setattr(db, "record_attempt", fail_audit)
    with pytest.raises(RuntimeError, match="audit write failed"):
        db.try_accept_fact(uuid4(), candidate_record(), "SMS", [1.0, 0.0], FactStatus.DRY_RUN, Settings())
    assert conn.commits == 1
    assert conn.rollbacks == 1


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
