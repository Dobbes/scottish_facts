from types import SimpleNamespace
from uuid import uuid4

import pytest
from twilio.base.exceptions import TwilioRestException

from scotland_facts.models import FactStatus
from scotland_facts.sms import (
    AmbiguousTwilioSendError,
    DefinitiveTwilioSendError,
    TwilioDeliveryError,
    app_status_for_twilio,
    poll_delivery,
    reconcile_recent,
    send_once,
)


class SendDB:
    def __init__(self, trace):
        self.trace = trace
        self.status = None
        self.sid = None

    def mark_send_attempted(self, fact_id):
        self.trace.append("commit_send_attempted")
        self.status = FactStatus.SEND_ATTEMPTED

    def mark_submitted(self, fact_id, sid, status):
        self.trace.append("store_sid")
        self.sid = sid
        self.status = FactStatus.SUBMITTED

    def update_twilio_status(self, fact_id, app_status, status, error_code=None):
        self.trace.append(f"status:{status}")
        self.status = app_status

    def mark_definitive_send_failure(self, fact_id, error_code):
        self.trace.append("definitive_failure")
        self.status = FactStatus.FAILED


class Messages:
    def __init__(self, trace, create_result=None, create_error=None, fetch_statuses=()):
        self.trace = trace
        self.create_result = create_result
        self.create_error = create_error
        self.fetch_statuses = iter(fetch_statuses)
        self.create_calls = 0

    def create(self, **kwargs):
        self.create_calls += 1
        self.trace.append("twilio_create")
        if self.create_error:
            raise self.create_error
        return self.create_result

    def __call__(self, sid):
        return self

    def fetch(self):
        status = next(self.fetch_statuses)
        return SimpleNamespace(status=status, error_code=30001 if status in {"failed", "undelivered"} else None)


def test_send_attempt_is_committed_before_one_twilio_call(production_settings):
    trace = []
    db = SendDB(trace)
    messages = Messages(trace, SimpleNamespace(sid="SM123", status="queued"))
    sid, status = send_once(db, uuid4(), "safe sms", production_settings, SimpleNamespace(messages=messages))
    assert trace[:3] == ["commit_send_attempted", "twilio_create", "store_sid"]
    assert messages.create_calls == 1
    assert sid == "SM123"
    assert status == FactStatus.SUBMITTED
    assert db.sid == "SM123"


def test_timeout_is_not_retried_and_leaves_send_attempted(production_settings):
    trace = []
    db = SendDB(trace)
    messages = Messages(trace, create_error=TimeoutError("network timeout to TEST_RECIPIENT"))
    with pytest.raises(AmbiguousTwilioSendError):
        send_once(db, uuid4(), "safe sms", production_settings, SimpleNamespace(messages=messages))
    assert messages.create_calls == 1
    assert db.status == FactStatus.SEND_ATTEMPTED


def test_definitive_api_rejection_is_failed(production_settings):
    trace = []
    db = SendDB(trace)
    error = TwilioRestException(400, "/Messages", msg="bad request", code=21211)
    messages = Messages(trace, create_error=error)
    with pytest.raises(DefinitiveTwilioSendError):
        send_once(db, uuid4(), "safe sms", production_settings, SimpleNamespace(messages=messages))
    assert messages.create_calls == 1
    assert db.status == FactStatus.FAILED


def test_twilio_server_error_is_ambiguous(production_settings):
    trace = []
    db = SendDB(trace)
    error = TwilioRestException(503, "/Messages", msg="upstream failure", code=20500)
    messages = Messages(trace, create_error=error)
    with pytest.raises(AmbiguousTwilioSendError):
        send_once(db, uuid4(), "safe sms", production_settings, SimpleNamespace(messages=messages))
    assert messages.create_calls == 1
    assert db.status == FactStatus.SEND_ATTEMPTED


@pytest.mark.parametrize(
    "twilio_status,expected",
    [
        ("delivered", FactStatus.DELIVERED),
        ("sent", FactStatus.SENT),
        ("failed", FactStatus.FAILED),
        ("undelivered", FactStatus.FAILED),
        ("queued", FactStatus.SUBMITTED),
    ],
)
def test_twilio_status_mapping(twilio_status, expected):
    assert app_status_for_twilio(twilio_status) == expected


def test_poll_delivered_updates_database(production_settings):
    settings = production_settings.model_copy(update={"twilio_status_poll_seconds": 3})
    trace = []
    db = SendDB(trace)
    messages = Messages(trace, fetch_statuses=["delivered"])
    clock = iter([0.0, 0.0])
    status = poll_delivery(
        db,
        uuid4(),
        "SM123",
        settings,
        SimpleNamespace(messages=messages),
        sleep=lambda _: None,
        monotonic=lambda: next(clock),
    )
    assert status == FactStatus.DELIVERED
    assert db.status == FactStatus.DELIVERED


def test_failed_poll_raises_from_send(production_settings):
    settings = production_settings.model_copy(update={"twilio_status_poll_seconds": 3})
    trace = []
    db = SendDB(trace)
    messages = Messages(
        trace,
        create_result=SimpleNamespace(sid="SM123", status="queued"),
        fetch_statuses=["undelivered"],
    )
    clock = iter([0.0, 0.0])
    with pytest.raises(TwilioDeliveryError):
        send_once(
            db,
            uuid4(),
            "safe sms",
            settings,
            SimpleNamespace(messages=messages),
            sleep=lambda _: None,
            monotonic=lambda: next(clock),
        )
    assert db.status == FactStatus.FAILED


def test_queued_after_deadline_remains_submitted(production_settings):
    settings = production_settings.model_copy(update={"twilio_status_poll_seconds": 1})
    trace = []
    db = SendDB(trace)
    messages = Messages(trace, fetch_statuses=["queued"])
    clock = iter([0.0, 0.0, 2.0])
    status = poll_delivery(
        db,
        uuid4(),
        "SM123",
        settings,
        SimpleNamespace(messages=messages),
        sleep=lambda _: None,
        monotonic=lambda: next(clock),
    )
    assert status == FactStatus.SUBMITTED


def test_reconciliation_lookup_failure_is_non_blocking():
    class BrokenDB:
        rolled_back = False

        def reconciliation_candidates(self, days):
            raise RuntimeError("database unavailable")

        def rollback(self):
            self.rolled_back = True

    db = BrokenDB()
    reconcile_recent(db, object())
    assert db.rolled_back is True


def test_reconciliation_does_not_regress_sent_to_submitted():
    class ReconcileDB:
        updated = None

        def reconciliation_candidates(self, days):
            return [{"id": uuid4(), "twilio_sid": "SM123", "status": "SENT"}]

        def update_twilio_status(self, fact_id, status, status_text, error_code):
            self.updated = (status, status_text)

    client = SimpleNamespace(
        messages=lambda sid: SimpleNamespace(
            fetch=lambda: SimpleNamespace(status="queued", error_code=None)
        )
    )
    db = ReconcileDB()
    reconcile_recent(db, client)
    assert db.updated == (FactStatus.SENT, "queued")
