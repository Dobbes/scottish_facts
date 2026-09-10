from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scotland_facts.config import Settings
from scotland_facts.models import CATEGORIES, RunStart


@pytest.fixture
def base_settings() -> Settings:
    return Settings()


@pytest.fixture
def production_settings() -> Settings:
    return Settings(
        sms_send_enabled=True,
        recipient_consent_confirmed=True,
        openai_api_key="test-openai-key",
        supabase_db_url="postgresql://localhost/test",
        twilio_account_sid="test-account-sid",
        twilio_api_key_sid="test-api-key-sid",
        twilio_api_key_secret="test-secret",
        twilio_from_number="+1" + "2025550100",
        recipient_number="+1" + "2025550101",
        twilio_status_poll_seconds=0,
    )


def research_response(fact: str, category: str, subjects: list[str]) -> SimpleNamespace:
    import json

    return SimpleNamespace(
        output_text=json.dumps({"fact": fact, "category": category, "subjects": subjects}),
        output=[
            SimpleNamespace(type="web_search_call", action=SimpleNamespace(sources=[])),
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        annotations=[
                            SimpleNamespace(
                                type="url_citation",
                                url="https://example.org/scotland",
                                title="Example source",
                            )
                        ],
                    )
                ],
            ),
        ],
    )


class FakeDatabase:
    def require_subscription(self):
        pass

    def __init__(self) -> None:
        self.run_id = uuid4()
        self.owned = True
        self.attempts = []
        self.inserted = []
        self.failures = []
        self.completed = []
        self.recent = []
        self.exact_matches: deque[object | None] = deque()
        self.neighbor_results: deque[list[tuple[object, float]]] = deque()
        self.trace = []

    def start_run(self, run_key, run_type, settings):
        self.trace.append("start_run")
        return RunStart(id=self.run_id, owned=self.owned, run_key=run_key)

    def category_order(self):
        return list(CATEGORIES)

    def recent_subjects(self, days):
        return list(self.recent)

    def prior_facts(self, limit=50):
        return []

    def recent_sms(self, limit=10):
        return []

    def exact_duplicate(self, normalized):
        return self.exact_matches.popleft() if self.exact_matches else None

    def nearest_facts(self, embedding, limit=5):
        return self.neighbor_results.popleft() if self.neighbor_results else []

    def record_attempt(self, run_id, attempt):
        self.attempts.append(attempt.model_copy(deep=True))

    def insert_fact(self, *args):
        fact_id = uuid4()
        self.inserted.append((fact_id, args))
        self.trace.append("insert_fact")
        return fact_id

    def try_accept_fact(self, run_id, record, sms_text, embedding, status, settings):
        fact_id = self.insert_fact(
            run_id, record.candidate_fact, record.normalized_fact, sms_text,
            record.category, record.subjects, record.source_url, record.source_title,
            record.sources, embedding, status,
        )
        record.accepted = True
        self.record_attempt(run_id, record)
        return fact_id

    def complete_run(self, run_id, status=None):
        self.completed.append(run_id)

    def prepare_deliveries(self, fact_id, slots):
        self.trace.append("prepare_deliveries")
        return [(uuid4(), slot) for slot in slots]

    def fail_run(self, run_id, code, reason):
        self.failures.append((code, reason))

    def reconciliation_candidates(self, days=7):
        return []

    def close(self):
        self.trace.append("close")
