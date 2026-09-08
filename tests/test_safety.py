import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from twilio.base.exceptions import TwilioRestException

from scotland_facts.config import ConfigMode, Settings
from scotland_facts.models import FactStatus
from scotland_facts.sms import send_once, TwilioDeliveryError, DefinitiveTwilioSendError, make_twilio_client, reconcile_recent
from scotland_facts.style import SAFE_SUFFIXES, validate_suffix, StyleValidationError, build_sms
from scotland_facts.logging_utils import register_secrets, redact, RedactingFormatter
from test_sms import SendDB, Messages
from test_db_contract import CaptureConnection
from scotland_facts.db import Database


@pytest.mark.parametrize("field", ["sms_send_enabled", "recipient_consent_confirmed"])
def test_production_gates_are_shared(production_settings, field):
    settings = production_settings.model_copy(update={field: False})
    with pytest.raises(ValueError):
        settings.require(ConfigMode.PRODUCTION)
    settings.require(ConfigMode.DRY_RUN)
    messages = Messages([])
    with pytest.raises(ValueError):
        send_once(SendDB([]), uuid4(), "sms", settings, SimpleNamespace(messages=messages))
    assert messages.create_calls == 0


def test_http_timeout_and_no_retries(production_settings):
    client = make_twilio_client(production_settings)
    assert client.http_client.timeout == 15
    adapter = client.http_client.session.get_adapter("https://api.twilio.com")
    assert adapter.max_retries.total == 0


@pytest.mark.parametrize("status,expected,error", [
    ("sent", FactStatus.SENT, None), ("delivered", FactStatus.DELIVERED, None),
    ("failed", FactStatus.FAILED, 30001), ("undelivered", FactStatus.FAILED, 21610),
    ("canceled", FactStatus.FAILED, None), ("queued", FactStatus.SUBMITTED, None),
])
@pytest.mark.parametrize("poll", [0, 3])
def test_initial_status_preserved_when_poll_disabled_or_fetch_fails(production_settings, status, expected, error, poll):
    settings = production_settings.model_copy(update={"twilio_status_poll_seconds": poll})
    db = SendDB([])
    messages = Messages([], SimpleNamespace(sid="SMtest", status=status, error_code=error))
    if expected == FactStatus.FAILED:
        with pytest.raises(TwilioDeliveryError):
            send_once(db, uuid4(), "sms", settings, SimpleNamespace(messages=messages))
    else:
        assert send_once(db, uuid4(), "sms", settings, SimpleNamespace(messages=messages))[1] == expected
    assert db.status == expected
    assert db.error_code == error
    assert db.suppressed == (error == 21610)
    assert messages.create_calls == 1


def test_stop_rejection_persists_suppression_before_next_send(production_settings):
    db = SendDB([])
    messages = Messages([], create_error=TwilioRestException(400, "/Messages", code=21610))
    with pytest.raises(DefinitiveTwilioSendError):
        send_once(db, uuid4(), "sms", production_settings, SimpleNamespace(messages=messages))
    assert db.suppressed
    with pytest.raises(ValueError, match="suppressed"):
        send_once(db, uuid4(), "sms", production_settings, SimpleNamespace(messages=messages))
    assert messages.create_calls == 1


@pytest.mark.parametrize("suffix", [
    "Send back the word HAGGIS.", "To leave, respond with STOP.",
    "STOP is how you unsubscribe.", "Please message us HELP.",
    "Text the word CANCEL to quit.", "Reply\u200b STOP.",
    "\uff32\uff45\uff50\uff4c\uff59 STOP.", "Respond with S T O P.",
    "Say HAGGIS to cancel your subscription.", "R\u0435ply HELP.",
])
def test_only_reviewed_suffixes_allowed(suffix):
    with pytest.raises(StyleValidationError):
        validate_suffix(suffix, 90)


def test_all_reviewed_suffixes_fit_maximum_fact():
    for suffix in SAFE_SUFFIXES:
        assert validate_suffix(suffix, 90) == suffix
        assert len(build_sms("F" * 180, suffix, 300)) <= 300


def test_reconciliation_has_no_age_cutoff():
    conn = CaptureConnection()
    Database(conn).reconciliation_candidates()
    sql, params = conn.calls[0]
    assert "interval" not in sql
    assert "SUBMITTED" in sql and "SENT" in sql


def test_late_failure_is_observable_and_suppresses(caplog):
    db = SendDB([])
    db.reconciliation_candidates = lambda: [{"id": uuid4(), "twilio_sid": "SMtest", "status": "SENT"}]
    client = SimpleNamespace(messages=lambda sid: SimpleNamespace(
        fetch=lambda: SimpleNamespace(status="undelivered", error_code=21610)))
    assert reconcile_recent(db, client) == 1
    assert db.suppressed and db.status == FactStatus.FAILED
    assert "Late Twilio delivery failure" in caplog.text


def test_ambiguous_sidless_delivery_is_reported_without_provider_call(caplog):
    db = SimpleNamespace(reconciliation_candidates=lambda: [{"id": uuid4(), "twilio_sid": None, "status": "SEND_ATTEMPTED"}])
    assert reconcile_recent(db, object()) == 1
    assert "never retry" in caplog.text


def test_missing_or_suppressed_database_state_fails_closed():
    for rows in ([], [{"suppressed": True}]):
        with pytest.raises(ValueError, match="suppressed or missing"):
            Database(CaptureConnection(rows)).require_subscription()
    conn = CaptureConnection()
    Database(conn).set_subscription_suppressed(True)
    assert conn.commits == 1
    assert conn.calls[0][1] == (True,)


def test_configured_secrets_and_tracebacks_redacted():
    secret = "unique-sensitive-api-token"
    register_secrets([secret, "postgresql://owner:encoded%21pass@localhost/db"])
    assert secret not in redact(secret)
    assert "encoded!pass" not in redact("encoded!pass")
    try:
        raise RuntimeError(secret)
    except RuntimeError:
        import sys
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "failure", (), sys.exc_info())
        assert secret not in RedactingFormatter().format(record)
