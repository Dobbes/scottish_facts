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
from scotland_facts.style import StyleValidationError


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
    monkeypatch.setattr(orchestrator, "reconcile_recent", lambda *args: db.trace.append("reconcile"))

    def fake_send(database, fact_id, sms, settings, client, **kwargs):
        database.trace.append("send_once")
        assert database.inserted[0][1][-1] == FactStatus.PENDING
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
    monkeypatch.setattr(orchestrator, "reconcile_recent", lambda *args: None)
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
