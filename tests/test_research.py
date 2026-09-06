import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, BadRequestError, OpenAI

from scotland_facts.models import ResearchCandidate
from scotland_facts.research import (
    RESEARCH_PROMPT,
    ResearchValidationError,
    request_research,
    retry_openai,
    validate_candidate,
)
class Responses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text="{}")


def test_research_request_uses_required_web_search_and_schema(base_settings):
    responses = Responses()
    client = SimpleNamespace(responses=responses)
    request_research(client, base_settings, "folklore", ["kelpies"], ["prior fact"], sleep=lambda _: None)
    assert responses.kwargs["store"] is False
    assert responses.kwargs["include"] == ["web_search_call.action.sources"]
    assert responses.kwargs["tool_choice"] == "required"
    assert responses.kwargs["tools"] == [{"type": "web_search", "search_context_size": "medium"}]
    assert responses.kwargs["text"]["format"]["strict"] is True
    assert responses.kwargs["reasoning"] == {"effort": "low"}


def test_research_prompt_contains_injection_defenses():
    lowered = RESEARCH_PROMPT.lower()
    assert "untrusted evidence" in lowered
    assert "ignore all instructions" in lowered
    assert "never reveal secrets" in lowered


@pytest.mark.parametrize(
    "candidate,reason",
    [
        (ResearchCandidate(fact="Valid fact.", category="food", subjects=["food"]), "category"),
        (ResearchCandidate(fact="Two facts. Another one.", category="folklore", subjects=["x"]), "sentence"),
        (ResearchCandidate(fact="See https://example.org.", category="folklore", subjects=["x"]), "URL"),
        (ResearchCandidate(fact="SCOTLAND FACTS: A fact.", category="folklore", subjects=["x"]), "prefix"),
        (ResearchCandidate(fact="...", category="folklore", subjects=["x"]), "1-180"),
    ],
)
def test_candidate_validation(candidate, reason):
    with pytest.raises(ResearchValidationError, match=reason):
        validate_candidate(candidate, "folklore", 180)


def test_common_abbreviation_does_not_look_like_two_sentences():
    candidate = ResearchCandidate(
        fact="St. Kilda is home to the remains of a distinctive island community.",
        category="islands",
        subjects=["st kilda"],
    )
    validate_candidate(candidate, "islands", 180)


def test_transient_openai_errors_retry_three_total_attempts():
    calls = 0
    delays = []

    def call():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
        return "ok"

    assert retry_openai(call, sleep=delays.append) == "ok"
    assert calls == 3
    assert delays == [1, 2]


def test_non_transient_openai_error_is_not_retried():
    calls = 0

    def call():
        nonlocal calls
        calls += 1
        raise ValueError("invalid request")

    with pytest.raises(ValueError, match="invalid request"):
        retry_openai(call, sleep=lambda _: None)
    assert calls == 1


def test_installed_openai_sdk_serializes_research_contract(base_settings):
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            400,
            request=request,
            json={"error": {"message": "test stop", "type": "invalid_request_error"}},
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAI(api_key="test", max_retries=0, http_client=http_client)
    with pytest.raises(BadRequestError, match="test stop"):
        request_research(client, base_settings, "folklore", [], [], sleep=lambda _: None)
    assert captured["tool_choice"] == "required"
    assert captured["tools"][0]["type"] == "web_search"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["include"] == ["web_search_call.action.sources"]
