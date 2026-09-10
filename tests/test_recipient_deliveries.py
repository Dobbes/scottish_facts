"""Opt-in real PostgreSQL delivery boundaries; never initializes a provider client."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from test_db_integration import private_database, seed, candidate, vector
from scotland_facts.models import FactStatus


def test_separate_rows_primary_mirror_and_reconciliation(private_database):
    db = private_database()
    fact_id = seed(db, candidate(), vector(), FactStatus.PENDING)
    deliveries = dict((slot, key) for key, slot in db.prepare_deliveries(fact_id, ("primary", "secondary")))
    db.mark_send_attempted(deliveries["primary"], "primary")
    db.mark_submitted(deliveries["primary"], "SM-primary-test", "delivered", FactStatus.DELIVERED)
    db.mark_send_attempted(deliveries["secondary"], "secondary")
    assert [(row["id"], row["recipient_slot"]) for row in db.reconciliation_candidates()] == [
        (deliveries["secondary"], "secondary")
    ]
    db.mark_definitive_send_failure(deliveries["secondary"], 21211)
    row = db.conn.execute("SELECT status, twilio_sid FROM facts WHERE id = %s", (fact_id,)).fetchone()
    assert row == {"status": "DELIVERED", "twilio_sid": "SM-primary-test"}
    assert db.reconciliation_candidates() == []
    assert {row["recipient_slot"]: row["status"] for row in db.history(1)[0]["deliveries"]} == {
        "primary": "DELIVERED", "secondary": "FAILED",
    }


def test_concurrent_claim_has_one_winner_per_recipient(private_database):
    db = private_database()
    fact_id = seed(db, candidate(), vector(), FactStatus.PENDING)
    deliveries = db.prepare_deliveries(fact_id, ("primary", "secondary"))
    for delivery_id, slot in deliveries:
        workers = [private_database(), private_database()]
        barrier = Barrier(2, timeout=10)

        def claim(worker):
            barrier.wait()
            try:
                worker.mark_send_attempted(delivery_id, slot)
                return True
            except RuntimeError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(claim, workers)) == [False, True]
    assert len(db.reconciliation_candidates()) == 2


def test_preview_and_wrong_slot_and_suppression_cannot_send(private_database):
    db = private_database()
    preview = seed(db, candidate(), vector(), FactStatus.DRY_RUN)
    with pytest.raises(RuntimeError):
        db.prepare_deliveries(preview, ("primary", "secondary"))
    assert db.conn.execute("SELECT count(*) AS n FROM sms_deliveries").fetchone()["n"] == 0
    fact_id = seed(db, candidate("A second fact.", "second subject"), vector(1), FactStatus.PENDING)
    deliveries = db.prepare_deliveries(fact_id, ("primary", "secondary"))
    with pytest.raises(RuntimeError):
        db.mark_send_attempted(deliveries[1][0], "primary")
    db.set_subscription_suppressed(True)
    for delivery_id, slot in deliveries:
        with pytest.raises(RuntimeError):
            db.mark_send_attempted(delivery_id, slot)
    rows = db.conn.execute("SELECT status, send_attempted_at FROM sms_deliveries").fetchall()
    assert rows == [{"status": "PENDING", "send_attempted_at": None}] * 2


def test_duplicate_preparation_cannot_add_another_attempt(private_database):
    import psycopg
    db = private_database()
    fact_id = seed(db, candidate(), vector(), FactStatus.PENDING)
    db.prepare_deliveries(fact_id, ("primary", "secondary"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.prepare_deliveries(fact_id, ("primary", "secondary"))
    assert db.conn.execute("SELECT count(*) AS n FROM sms_deliveries").fetchone()["n"] == 2
