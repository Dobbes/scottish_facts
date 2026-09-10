from __future__ import annotations

from collections import deque
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

import scotland_facts.orchestrator as orchestrator
from conftest import FakeDatabase, research_response
from scotland_facts.config import Settings
from scotland_facts.models import CATEGORIES, FactStatus, RunStatus
from scotland_facts.orchestrator import WorkflowError, run_workflow
from scotland_facts.sms import AmbiguousTwilioSendError
from scotland_facts.style import SMS_FOOTER, StyleValidationError


NOW = datetime(2026, 9, 6, 14, 15, tzinfo=ZoneInfo("UTC"))
FACTS = [
    "Scotland's national animal is the unicorn.",
    "The shortest scheduled flight in Scotland links Westray and Papa Westray.",
    "Edinburgh Castle stands on the plug of an extinct volcano.",
    "The Forth Bridge opened in 1890.",
    "Scotland has hundreds of offshore islands.",
]


def prepare(monkeypatch, responses, suffix="Your compulsory education resumes tomorrow."):
    queue = deque(responses)
    monkeypatch.setattr(orchestrator, "request_research", lambda *args, **kwargs: queue.popleft())
    monkeypatch.setattr(orchestrator, "embed_text", lambda *args, **kwargs: [0.0] * 1536)
    monkeypatch.setattr(orchestrator, "request_suffix", lambda *args, **kwargs: suffix)


def response(index, subjects=None):
    return research_response(FACTS[index], CATEGORIES[index], subjects or [f"subject {index}"])


def test_happy_path_dry_run_preserves_fact_and_never_touches_twilio(monkeypatch):
    db = FakeDatabase()
    prepare(monkeypatch, [response(0, ["unicorns", "scotland"])])
    result = run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert result.status == RunStatus.SUCCEEDED
    assert result.sms_text.startswith(f"SCOTLAND FACTS: {FACTS[0]} ")
    assert result.sms_text.endswith(SMS_FOOTER)
    assert len(result.sms_text) <= 300
    assert db.inserted[0][1][3] == result.sms_text
    assert db.inserted[0][1][-1] == FactStatus.DRY_RUN
    assert db.completed == [db.run_id]
    assert "send_once" not in db.trace


def test_fact_is_stripped_once_before_embedding_and_persistence(monkeypatch):
    db = FakeDatabase()
    padded = research_response(f"  {FACTS[0]}  ", CATEGORIES[0], ["unicorns"])
    prepare(monkeypatch, [padded])
    result = run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert result.sms_text.startswith(f"SCOTLAND FACTS: {FACTS[0]} ")
    assert db.inserted[0][1][1] == FACTS[0]


def test_recent_subject_rejects_first_then_accepts_second(monkeypatch):
    db = FakeDatabase()
    db.recent = ["unicorns"]
    prepare(monkeypatch, [response(0, ["Unicorns"]), response(1, ["orkney flights"])])
    result = run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert result.attempts == 2
    assert db.attempts[0].rejection_code == "RECENT_SUBJECT"
    assert db.attempts[1].accepted is True


def test_semantic_duplicate_rejects_first_then_accepts_second(monkeypatch):
    db = FakeDatabase()
    prior_id = uuid4()
    db.neighbor_results.extend([[(prior_id, 0.91)], [(uuid4(), 0.4)]])
    prepare(monkeypatch, [response(0), response(1)])
    result = run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert result.attempts == 2
    assert db.attempts[0].rejection_code == "SEMANTIC_DUPLICATE"
    assert db.attempts[0].matched_fact_id == prior_id


def test_malformed_output_then_recovers(monkeypatch):
    malformed = response(0)
    malformed.output_text = "not json"
    db = FakeDatabase()
    prepare(monkeypatch, [malformed, response(1)])
    result = run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert result.attempts == 2
    assert db.attempts[0].rejection_code == "MALFORMED_OUTPUT"


def test_five_failed_research_attempts_never_insert_or_send(monkeypatch):
    db = FakeDatabase()
    db.exact_matches.extend([uuid4() for _ in range(5)])
    prepare(monkeypatch, [response(index) for index in range(5)])
    with pytest.raises(WorkflowError, match="Research exhausted"):
        run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert len(db.attempts) == 5
    assert db.inserted == []
    assert db.failures[-1][0] == "RESEARCH_EXHAUSTED"


def test_style_failure_never_inserts_or_sends(monkeypatch):
    db = FakeDatabase()
    prepare(monkeypatch, [response(0)])
    monkeypatch.setattr(
        orchestrator,
        "request_suffix",
        lambda *args, **kwargs: (_ for _ in ()).throw(StyleValidationError("bad suffix")),
    )
    with pytest.raises(WorkflowError, match="Style generation exhausted"):
        run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert db.inserted == []
    assert db.failures[-1][0] == "STYLE_EXHAUSTED"


def test_production_happy_path_persists_pending_before_send(monkeypatch, production_settings):
    db = FakeDatabase()
    prepare(monkeypatch, [response(0)])
    monkeypatch.setattr(orchestrator, "reconcile_recent", lambda *args, **kwargs: db.trace.append("reconcile"))

    def fake_send(database, fact_id, sms, settings, client, **kwargs):
        database.trace.append("send_once")
        assert database.inserted[0][1][-1] == FactStatus.PENDING
        assert sms.endswith(SMS_FOOTER)
        assert len(sms) <= 300
        assert database.inserted[0][1][3] == sms
        return "SM123", FactStatus.SUBMITTED

    monkeypatch.setattr(orchestrator, "send_once", fake_send)
    result = run_workflow(
        production_settings,
        db=db,
        openai_client=object(),
        twilio_client=object(),
        now=NOW,
    )
    assert result.status == RunStatus.SUCCEEDED
    assert db.trace.index("insert_fact") < db.trace.index("send_once")


def test_twilio_exception_marks_run_failed(monkeypatch, production_settings):
    db = FakeDatabase()
    prepare(monkeypatch, [response(0)])
    monkeypatch.setattr(orchestrator, "reconcile_recent", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        orchestrator,
        "send_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(AmbiguousTwilioSendError("timeout")),
    )
    with pytest.raises(WorkflowError, match="timeout"):
        run_workflow(
            production_settings,
            db=db,
            openai_client=object(),
            twilio_client=object(),
            now=NOW,
        )
    assert db.failures[-1][0] == "TWILIO_AMBIGUOUS_SEND"


def test_no_web_source_is_recorded_as_rejection(monkeypatch):
    no_source = SimpleNamespace(
        output_text=response(0).output_text,
        output=[SimpleNamespace(type="web_search_call", action=SimpleNamespace(sources=[]))],
    )
    db = FakeDatabase()
    prepare(monkeypatch, [no_source, response(1)])
    run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert db.attempts[0].rejection_code == "NO_WEB_SOURCE"


def test_suppressed_subscription_blocks_before_generation(monkeypatch, production_settings):
    db = FakeDatabase()
    db.require_subscription = lambda: (_ for _ in ()).throw(ValueError("Subscription suppressed"))
    monkeypatch.setattr(orchestrator, "make_openai_client", lambda settings: pytest.fail("no OpenAI"))
    monkeypatch.setattr(orchestrator, "make_twilio_client", lambda settings: pytest.fail("no Twilio"))
    with pytest.raises(WorkflowError, match="suppressed"):
        run_workflow(production_settings, db=db, now=NOW)
    assert not db.attempts and not db.inserted


def test_disabled_gate_blocks_before_database(production_settings, monkeypatch):
    monkeypatch.setattr(orchestrator.Database, "connect", lambda settings: pytest.fail("no database"))
    with pytest.raises(ValueError, match="SMS_SEND_ENABLED"):
        run_workflow(production_settings.model_copy(update={"sms_send_enabled": False}))


@pytest.mark.parametrize("provider_status,app_status", [("queued", FactStatus.SUBMITTED), ("sent", FactStatus.SENT)])
def test_missing_delivery_receipt_does_not_block_later_days(monkeypatch, production_settings, provider_status, app_status):
    from datetime import timedelta
    from scotland_facts.sms import reconcile_recent

    db = FakeDatabase()
    db.reconciliation_candidates = lambda: [{"id": uuid4(), "twilio_sid": "SMold", "status": app_status.value}]
    updates = []
    db.update_twilio_status = lambda fact_id, status, text, code: updates.append((status, text))
    client = SimpleNamespace(messages=lambda sid: SimpleNamespace(
        fetch=lambda: SimpleNamespace(status=provider_status, error_code=None)))
    prepare(monkeypatch, [response(0), research_response(FACTS[1], CATEGORIES[0], ["orkney flights"])])
    sends = []
    monkeypatch.setattr(orchestrator, "send_once", lambda *args, **kwargs: sends.append("new daily send"))
    for day in (1, 2):
        result = run_workflow(production_settings, db=db, openai_client=object(),
                              twilio_client=client, now=NOW + timedelta(days=day))
        assert result.status == RunStatus.SUCCEEDED
    assert len(sends) == 2
    assert updates == [(app_status, provider_status)] * 2
    assert reconcile_recent(db, client) == 1  # Standalone observability is unchanged.


@pytest.mark.parametrize("issue", ["fetch_error", "failed", "optout", "ambiguous"])
def test_material_reconciliation_issues_still_block_generation(monkeypatch, production_settings, issue):
    db = FakeDatabase()
    db.reconciliation_candidates = lambda: [{
        "id": uuid4(), "twilio_sid": None if issue == "ambiguous" else "SMold", "status": "SENT"}]
    db.update_twilio_status = lambda *args: None
    suppressed = []
    db.set_subscription_suppressed = lambda value: suppressed.append(value)

    def fetch():
        if issue == "fetch_error":
            raise TimeoutError("fetch unavailable")
        return SimpleNamespace(status="failed", error_code=21610 if issue == "optout" else 30001)

    client = SimpleNamespace(messages=lambda sid: SimpleNamespace(fetch=fetch))
    monkeypatch.setattr(orchestrator, "make_openai_client", lambda settings: pytest.fail("no generation"))
    with pytest.raises(WorkflowError, match="reconciliation needs attention"):
        run_workflow(production_settings, db=db, twilio_client=client, now=NOW)
    assert not db.attempts and not db.inserted
    assert suppressed == ([True] if issue == "optout" else [])


def test_ordinary_text_fact_does_not_exhaust_style(monkeypatch):
    fact = "The Declaration of Arbroath is a medieval Latin text."
    db = FakeDatabase()
    prepare(monkeypatch, [research_response(fact, CATEGORIES[0], ["declaration of arbroath"])])
    result = run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert result.status == RunStatus.SUCCEEDED
    assert fact in result.sms_text
    assert not db.failures


@pytest.mark.parametrize("dry_run", [True, False])
def test_concurrent_acceptance_collision_refreshes_context_and_retries(monkeypatch, production_settings, dry_run):
    db = FakeDatabase()
    prepare(monkeypatch, [response(0), response(1)])
    original_accept = db.try_accept_fact
    acceptance_calls = []
    contexts = []

    def accept(run_id, record, sms, embedding, status, settings):
        acceptance_calls.append(record.candidate_fact)
        if len(acceptance_calls) == 1:
            record.rejection_code = "RECENT_SUBJECT"
            record.rejection_reason = "Another preview claimed this subject"
            db.recent = ["subject 0"]
            return None
        return original_accept(run_id, record, sms, embedding, status, settings)

    def research(ai, settings, category, recent, prior, **kwargs):
        contexts.append((list(recent), list(prior)))
        return response(len(contexts) - 1)

    db.try_accept_fact = accept
    db.prior_facts = lambda limit: [FACTS[0]] if acceptance_calls else []
    monkeypatch.setattr(orchestrator, "request_research", research)
    monkeypatch.setattr(orchestrator, "reconcile_recent", lambda *args, **kwargs: None)
    sends = []
    monkeypatch.setattr(orchestrator, "send_once", lambda *args, **kwargs: sends.append(args[2]))
    result = run_workflow(production_settings, dry_run=dry_run, db=db, openai_client=object(),
                          twilio_client=object(), now=NOW)
    assert result.attempts == 2
    assert len(db.inserted) == 1
    assert db.inserted[0][1][1] == FACTS[1]
    assert not db.attempts[0].accepted
    assert db.attempts[0].rejection_code == "RECENT_SUBJECT"
    assert db.attempts[1].accepted
    assert contexts[1] == (["subject 0"], [FACTS[0]])
    assert len(sends) == (0 if dry_run else 1)


def test_acceptance_collisions_exhaust_without_inserting_or_sending(monkeypatch):
    db = FakeDatabase()
    prepare(monkeypatch, [response(i) for i in range(5)])
    def reject(run_id, record, *args):
        record.rejection_code = "SEMANTIC_DUPLICATE"
        record.rejection_reason = "Concurrent paraphrase"
        return None
    db.try_accept_fact = reject
    with pytest.raises(WorkflowError, match="Research exhausted"):
        run_workflow(Settings(), dry_run=True, db=db, openai_client=object(), now=NOW)
    assert len(db.attempts) == 5
    assert all(not record.accepted for record in db.attempts)
    assert not db.inserted
