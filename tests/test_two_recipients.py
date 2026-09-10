from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from twilio.base.exceptions import TwilioRestException

from conftest import FakeDatabase
from test_orchestrator import NOW, prepare, response
from test_sms import SendDB
from scotland_facts import orchestrator
from scotland_facts.config import ConfigMode, Settings, load_settings
from scotland_facts.logging_utils import redact
from scotland_facts.models import FactStatus
from scotland_facts.sms import send_once, reconcile_recent


@pytest.fixture
def two_settings(production_settings):
    return Settings(**{
        **production_settings.model_dump(),
        "father_in_law_number": "+1" + "2025550102",
    })


def test_optional_recipient_is_loaded_and_redacted(monkeypatch):
    from test_config import clear_settings_env
    clear_settings_env(monkeypatch)
    primary, secondary = "+1" + "2025550101", "+1" + "2025550102"
    monkeypatch.setenv("RECIPIENT_NUMBER", primary)
    monkeypatch.setenv("FATHER_IN_LAW_NUMBER", secondary)
    settings = load_settings()
    assert settings.recipient_slots() == ("primary", "secondary")
    assert settings.recipient_secret("secondary") == secondary
    assert primary not in repr(settings) and secondary not in repr(settings)
    assert secondary not in redact(f"Provider failed for {secondary}")


@pytest.mark.parametrize("problem", ["duplicate", "sender", "invalid", "missing-primary"])
def test_bad_recipient_configuration_fails_before_provider_call(two_settings, problem):
    value = {
        "duplicate": two_settings.recipient_number,
        "sender": two_settings.twilio_from_number,
        "invalid": SecretStr("not-a-number"),
        "missing-primary": two_settings.father_in_law_number,
    }[problem]
    settings = two_settings.model_copy(update={"father_in_law_number": value})
    if problem == "missing-primary":
        settings = settings.model_copy(update={"recipient_number": None})
    with pytest.raises(ValueError):
        settings.require(ConfigMode.DOCTOR)


class LedgerDB(FakeDatabase):
    """In-memory boundary double: separate state, real send_once/orchestration."""
    def __init__(self):
        super().__init__()
        self.rows = {}
        self.suppressed = False

    def prepare_deliveries(self, fact_id, slots):
        assert not self.rows
        deliveries = [(uuid4(), slot) for slot in slots]
        self.rows = {key: {"slot": slot, "status": FactStatus.PENDING} for key, slot in deliveries}
        return deliveries

    def require_subscription(self):
        if self.suppressed:
            raise ValueError("Subscription suppressed")

    def set_subscription_suppressed(self, value):
        self.suppressed = value

    def mark_send_attempted(self, delivery_id, slot):
        row = self.rows[delivery_id]
        assert row["slot"] == slot and row["status"] == FactStatus.PENDING
        row["status"] = FactStatus.SEND_ATTEMPTED

    def mark_submitted(self, delivery_id, sid, status, app_status, error_code=None):
        self.rows[delivery_id].update(status=app_status, sid=sid)

    def mark_definitive_send_failure(self, delivery_id, error_code):
        self.rows[delivery_id]["status"] = FactStatus.FAILED


@pytest.mark.parametrize("first_error", [None, "rejected", "timeout", "opt-out"])
def test_one_fact_individual_boundaries_and_no_replay(monkeypatch, two_settings, first_error):
    prepare(monkeypatch, [response(0)])
    database = LedgerDB()
    calls = []

    def create(**kwargs):
        # Both rows must be persisted before the first external side effect.
        assert len(database.rows) == 2
        calls.append(kwargs)
        if len(calls) == 1:
            if first_error == "timeout":
                raise TimeoutError("ambiguous create")
            if first_error in {"rejected", "opt-out"}:
                raise TwilioRestException(400, "/Messages", code=21610 if first_error == "opt-out" else 21211)
        return SimpleNamespace(sid=f"SM-test-{len(calls)}", status="queued", error_code=None)

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    args = dict(db=database, openai_client=object(), twilio_client=client, now=NOW)
    if first_error:
        with pytest.raises(orchestrator.WorkflowError):
            orchestrator.run_workflow(two_settings, **args)
    else:
        orchestrator.run_workflow(two_settings, **args)
    assert len(database.inserted) == 1
    assert len(calls) == (1 if first_error == "opt-out" else 2)
    assert calls[0]["to"] == two_settings.secret("recipient_number")
    if len(calls) == 2:
        assert calls[1]["to"] == two_settings.secret("father_in_law_number")
        assert calls[0]["body"] == calls[1]["body"]
    rows = {row["slot"]: row for row in database.rows.values()}
    assert rows["primary"]["status"] == {
        None: FactStatus.SUBMITTED, "timeout": FactStatus.SEND_ATTEMPTED,
        "rejected": FactStatus.FAILED, "opt-out": FactStatus.FAILED,
    }[first_error]
    assert rows["secondary"]["status"] == (FactStatus.PENDING if first_error == "opt-out" else FactStatus.SUBMITTED)
    database.owned = False
    assert orchestrator.run_workflow(two_settings, **args).noop
    assert len(calls) == (1 if first_error == "opt-out" else 2)


def test_two_recipient_preview_creates_no_delivery_rows(monkeypatch, two_settings):
    prepare(monkeypatch, [response(0)])
    database = LedgerDB()
    result = orchestrator.run_workflow(two_settings, dry_run=True, db=database,
                                       openai_client=object(), twilio_client=object(), now=NOW)
    assert result.sms_text
    assert database.rows == {}
    assert len(database.inserted) == 1


def test_missing_secondary_cannot_claim_primary_boundary(production_settings):
    trace = []
    with pytest.raises(ValueError, match="not configured"):
        send_once(SendDB(trace), uuid4(), "test", production_settings, object(), recipient_slot="secondary")
    assert trace == []


def test_reconciliation_keeps_recipient_states_independent():
    primary, secondary = uuid4(), uuid4()
    updates = []
    database = SimpleNamespace(
        reconciliation_candidates=lambda: [
            {"id": primary, "recipient_slot": "primary", "twilio_sid": "SM-one", "status": "SENT"},
            {"id": secondary, "recipient_slot": "secondary", "twilio_sid": "SM-two", "status": "SUBMITTED"},
        ],
        update_twilio_status=lambda *args: updates.append(args),
    )
    client = SimpleNamespace(messages=lambda sid: SimpleNamespace(fetch=lambda: SimpleNamespace(
        status="delivered" if sid == "SM-one" else "undelivered", error_code=None,
    )))
    assert reconcile_recent(database, client) == 1
    assert [(row[0], row[1]) for row in updates] == [(primary, FactStatus.DELIVERED), (secondary, FactStatus.FAILED)]
