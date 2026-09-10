"""Opt-in tests against an existing migrated PostgreSQL/pgvector database.

Only SCOTLAND_FACTS_TEST_DB_URL enables database access; no dotenv is loaded.
Public tables supply definitions only. All test data lives in disposable clones.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from scotland_facts.config import Settings
from scotland_facts.db import Database, connect_database
from scotland_facts.dedupe import normalize_fact
from scotland_facts.models import CATEGORIES, AttemptRecord, FactStatus, RunType
from scotland_facts.orchestrator import make_run_key


class IsolatedConnection:
    def __init__(self, conn, schema):
        self._conn = conn
        self._schema = schema

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, query, params=None):
        # Reapply inside every transaction, including with transaction poolers.
        # Never fall back to public if a cloned application table is missing.
        self._conn.execute(sql.SQL("SET LOCAL search_path TO {}, extensions").format(
            sql.Identifier(self._schema)
        ))
        self._conn.execute("SET LOCAL statement_timeout TO '15s'")
        self._conn.execute("SET LOCAL lock_timeout TO '10s'")
        return self._conn.execute(query, params)


@pytest.fixture
def private_database():
    __tracebackhide__ = True
    dsn = os.environ.get("SCOTLAND_FACTS_TEST_DB_URL")
    if not dsn:
        pytest.skip("Set SCOTLAND_FACTS_TEST_DB_URL to opt in to PostgreSQL tests")

    schema = "novelty_test_" + uuid4().hex
    workers = []
    created = False

    def connect():
        __tracebackhide__ = True
        try:
            return connect_database(dsn)
        except Exception:
            # Connection errors can contain credentials or the supplied DSN.
            pytest.fail("Could not connect to the opt-in PostgreSQL test database", pytrace=False)

    admin = connect()
    try:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        admin.execute(
            sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema))
        )
        tables = ("generation_runs", "facts", "generation_attempts", "sms_deliveries", "subscription_state")
        for table in tables:
            admin.execute(
                sql.SQL("CREATE TABLE {} (LIKE {} INCLUDING ALL)").format(
                    sql.Identifier(schema, table), sql.Identifier("public", table)
                )
            )
        admin.execute(sql.SQL("INSERT INTO {} (id, suppressed) VALUES (true, false)").format(
            sql.Identifier(schema, "subscription_state")
        ))
        admin.commit()
        created = True

        def open_worker():
            __tracebackhide__ = True
            conn = connect()
            workers.append(conn)
            isolated = IsolatedConnection(conn, schema)
            # Fail before exercising Database if any relation resolves outside the clone.
            for table in tables:
                row = isolated.execute(
                    "SELECT %s::regclass::oid = %s::regclass::oid AS isolated",
                    (table, f"{schema}.{table}"),
                ).fetchone()
                assert row["isolated"]
            conn.commit()
            return Database(isolated)

        yield open_worker
    finally:
        try:
            for conn in workers:
                conn.close()
        finally:
            try:
                admin.rollback()
                if created:
                    admin.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )
                    admin.commit()
            finally:
                admin.close()


def vector(axis=0):
    result = [0.0] * 1536
    result[axis] = 1.0
    return result


def candidate(text="A Scottish castle has an unusual tower.", subject="castle alpha"):
    return AttemptRecord(
        attempt_number=1,
        candidate_fact=text,
        normalized_fact=normalize_fact(text),
        category="castles",
        subjects=[subject],
        source_url="https://example.org/scotland",
        source_title="Integration test source",
        sources=[{"url": "https://example.org/scotland", "title": "Integration test source"}],
    )


def start(db, status=FactStatus.DRY_RUN):
    run_type = RunType.DRY_RUN if status == FactStatus.DRY_RUN else RunType.DAILY
    run = db.start_run(f"integration:{uuid4().hex}", run_type, Settings())
    assert run.owned
    return run.id


def seed(db, record, embedding, status):
    return db.insert_fact(
        start(db, status), record.candidate_fact, record.normalized_fact,
        "SMS: " + record.candidate_fact, record.category, record.subjects,
        record.source_url, record.source_title, record.sources, embedding, status,
    )


@pytest.mark.parametrize("status", list(FactStatus))
def test_all_statuses_influence_six_history_queries(private_database, status):
    db = private_database()
    record = candidate()
    fact_id = seed(db, record, vector(), status)

    assert db.category_order() == sorted(c for c in CATEGORIES if c != "castles") + ["castles"]
    assert db.recent_subjects(14) == record.subjects
    assert db.prior_facts() == [record.candidate_fact]
    assert db.recent_sms() == ["SMS: " + record.candidate_fact]
    assert db.exact_duplicate(record.normalized_fact) == fact_id
    matches = db.nearest_facts(vector())
    assert [match[0] for match in matches] == [fact_id]
    assert matches[0][1] == pytest.approx(1.0)


def test_cosine_scan_is_exact_even_with_restrictive_hnsw_search(private_database):
    db = private_database()
    expected = []
    for index in range(48):
        embedding = vector()
        embedding[1] = (index + 1) / 48
        fact_id = seed(db, candidate(f"Scottish fact number {index}.", f"subject {index}"),
                       embedding, list(FactStatus)[index % len(FactStatus)])
        expected.append((fact_id, 1 / (1 + embedding[1] ** 2) ** 0.5))
    # An approximate index scan with ef_search=1 cannot supply this exact top ten.
    db.conn.execute("SET LOCAL hnsw.ef_search = 1")
    db.conn.execute("SET LOCAL enable_seqscan = off")
    matches = db.nearest_facts(vector(), limit=10)
    assert [item[0] for item in matches] == [item[0] for item in expected[:10]]
    assert [item[1] for item in matches] == pytest.approx([item[1] for item in expected[:10]])


def test_atomic_novelty_ignores_legacy_context_tags_but_keeps_specific_subjects(private_database):
    db = private_database()
    old = candidate("A fact about beavers.", "beavers")
    old.subjects = ["scotland", "wildlife", "beavers"]
    seed(db, old, vector(), FactStatus.DRY_RUN)
    fresh = candidate("An unrelated fact about hen harriers.", "hen harriers")
    assert db.try_accept_fact(start(db), fresh, "Preview", vector(1), FactStatus.DRY_RUN, Settings())
    repeated = candidate("A different fact about beavers.", "beavers")
    assert db.try_accept_fact(start(db), repeated, "Preview", vector(2), FactStatus.DRY_RUN, Settings()) is None
    assert repeated.rejection_code == "RECENT_SUBJECT"


@pytest.mark.parametrize("status", list(FactStatus))
def test_old_subject_expires_but_exact_and_semantic_history_remain(private_database, status):
    db = private_database()
    original = candidate()
    fact_id = seed(db, original, vector(), status)
    db.conn.execute(
        "UPDATE facts SET generated_at = now() - interval '15 days' WHERE id = %s", (fact_id,)
    )
    db.conn.commit()
    assert db.recent_subjects(14) == []
    assert db.exact_duplicate(original.normalized_fact) == fact_id
    assert db.nearest_facts(vector())[0][0] == fact_id

    exact = candidate(subject="unrelated exact subject")
    semantic = candidate("An unusual tower stands on a castle in Scotland.", "other subject")
    for record, embedding, code in (
        (exact, vector(1), "EXACT_DUPLICATE"),
        (semantic, vector(), "SEMANTIC_DUPLICATE"),
    ):
        assert db.try_accept_fact(start(db), record, "Preview", embedding,
                                  FactStatus.DRY_RUN, Settings()) is None
        assert record.rejection_code == code
        assert record.matched_fact_id == fact_id
        assert not record.accepted

    fresh = candidate("A different castle fact.", original.subjects[0])
    assert isinstance(db.try_accept_fact(start(db), fresh, "Fresh preview", vector(1),
                                        FactStatus.DRY_RUN, Settings()), UUID)
    assert db.conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 2
    assert db.conn.execute("SELECT count(*) AS n FROM generation_attempts").fetchone()["n"] == 1


@pytest.mark.parametrize("statuses", [
    (FactStatus.DRY_RUN, FactStatus.DRY_RUN),
    (FactStatus.PENDING, FactStatus.PENDING),
    (FactStatus.DRY_RUN, FactStatus.PENDING),
], ids=["previews", "pending", "mixed"])
@pytest.mark.parametrize("conflict", ["EXACT_DUPLICATE", "SEMANTIC_DUPLICATE", "RECENT_SUBJECT"])
def test_parallel_acceptance_has_one_winner(private_database, statuses, conflict):
    dbs = [private_database(), private_database()]
    records = [candidate(), candidate("A Scottish island has a distinctive beach.", "island beta")]
    embeddings = [vector(), vector(1)]
    if conflict == "EXACT_DUPLICATE":
        records[1] = candidate(records[0].candidate_fact, "island beta")
    elif conflict == "SEMANTIC_DUPLICATE":
        records[1] = candidate("An unusual tower stands on a castle in Scotland.", "island beta")
        embeddings[1] = vector()
    else:
        records[1].subjects = records[0].subjects.copy()
    run_ids = [start(db, status) for db, status in zip(dbs, statuses)]
    barrier = Barrier(2, timeout=10)

    def accept(index):
        db = dbs[index]
        # Both speculative read transactions see an empty history before racing.
        assert db.recent_subjects(14) == []
        assert db.exact_duplicate(records[index].normalized_fact) is None
        assert db.nearest_facts(embeddings[index]) == []
        barrier.wait()
        return db.try_accept_fact(run_ids[index], records[index], f"Preview {index}",
                                  embeddings[index], statuses[index], Settings())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(accept, index) for index in range(2)]
        results = [future.result(timeout=30) for future in futures]

    assert sum(isinstance(result, UUID) for result in results) == 1
    winner = next(index for index, result in enumerate(results) if result is not None)
    loser = 1 - winner
    assert records[winner].accepted
    assert records[winner].rejection_code is None
    assert not records[loser].accepted
    assert records[loser].rejection_code == conflict
    if conflict != "RECENT_SUBJECT":
        assert records[loser].matched_fact_id == results[winner]

    observer = private_database()
    facts = observer.conn.execute("SELECT id, run_id, status FROM facts").fetchall()
    assert facts == [{"id": results[winner], "run_id": run_ids[winner], "status": statuses[winner].value}]
    attempts = observer.conn.execute(
        "SELECT run_id, accepted, rejection_code FROM generation_attempts"
    ).fetchall()
    assert attempts == [{"run_id": run_ids[winner], "accepted": True, "rejection_code": None}]
    runs = observer.conn.execute("SELECT id, attempts FROM generation_runs").fetchall()
    assert {row["id"]: row["attempts"] for row in runs} == {run_ids[winner]: 1, run_ids[loser]: 0}
    # A different connection must acquire the same lock after both calls return.
    assert observer.conn.execute(
        "SELECT pg_try_advisory_xact_lock(1935896436) AS acquired"
    ).fetchone()["acquired"]
    observer.conn.commit()


def test_sequential_previews_reserve_novelty_not_daily_key_or_delivery(private_database):
    db = private_database()
    settings = Settings()
    now = datetime(2026, 1, 20, 12, tzinfo=timezone.utc)
    preview = db.start_run(make_run_key(True, now), RunType.DRY_RUN, settings)
    assert preview.owned
    record = candidate()
    fact_id = db.try_accept_fact(preview.id, record, "Preview only", vector(), FactStatus.DRY_RUN, settings)
    assert isinstance(fact_id, UUID)
    second = db.start_run(make_run_key(True, now), RunType.DRY_RUN, settings)
    assert second.owned and second.id != preview.id
    duplicate = candidate(subject="another subject")
    assert db.try_accept_fact(second.id, duplicate, "Another preview", vector(1),
                              FactStatus.DRY_RUN, settings) is None
    assert duplicate.rejection_code == "EXACT_DUPLICATE"

    daily_key = make_run_key(False, now)
    daily = db.start_run(daily_key, RunType.DAILY, settings)
    assert daily.owned and daily.id not in (preview.id, second.id)
    repeated_daily = db.start_run(daily_key, RunType.DAILY, settings)
    assert not repeated_daily.owned and repeated_daily.id == daily.id
    rows = db.conn.execute("SELECT id, run_type, dry_run FROM generation_runs").fetchall()
    assert {row["id"]: (row["run_type"], row["dry_run"]) for row in rows} == {
        preview.id: ("DRY_RUN", True), second.id: ("DRY_RUN", True), daily.id: ("DAILY", False),
    }
    facts = db.conn.execute(
        "SELECT id, status, send_attempted_at, twilio_sid, twilio_status, twilio_error_code, "
        "sent_at, delivered_at FROM facts"
    ).fetchall()
    assert facts == [{"id": fact_id, "status": "DRY_RUN", "send_attempted_at": None,
                      "twilio_sid": None, "twilio_status": None, "twilio_error_code": None,
                      "sent_at": None, "delivered_at": None}]
    assert db.conn.execute("SELECT count(*) AS n FROM generation_attempts").fetchone()["n"] == 1


@pytest.mark.parametrize("status", [FactStatus.DRY_RUN, FactStatus.PENDING])
def test_audit_failure_rolls_back_fact_and_releases_lock(private_database, status):
    db = private_database()
    run_id = start(db, status)
    # A real unique-constraint failure occurs after insert_fact, not a mocked write.
    db.record_attempt(run_id, AttemptRecord(attempt_number=1, rejection_code="TEST_SETUP"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.try_accept_fact(run_id, candidate(), "Never committed", vector(), status, Settings())

    observer = private_database()
    assert observer.conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 0
    attempts = observer.conn.execute("SELECT accepted, rejection_code FROM generation_attempts").fetchall()
    assert attempts == [{"accepted": False, "rejection_code": "TEST_SETUP"}]
    assert observer.conn.execute(
        "SELECT pg_try_advisory_xact_lock(1935896436) AS acquired"
    ).fetchone()["acquired"]
    observer.conn.commit()
    retry = candidate()
    retry.attempt_number = 2
    assert isinstance(db.try_accept_fact(run_id, retry, "Committed retry", vector(), status, Settings()), UUID)
    assert observer.conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 1
    assert observer.conn.execute(
        "SELECT count(*) AS n FROM generation_attempts WHERE accepted"
    ).fetchone()["n"] == 1
