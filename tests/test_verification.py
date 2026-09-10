import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, OpenAI

from scotland_facts.models import Source
from scotland_facts.research import (
    VERIFICATION_PROMPT,
    ResearchValidationError,
    verify_research,
)


URL = "https://museum.example/history"
FACT = "A Scottish museum displays a historic wooden spoon."
EVIDENCE = "The page states: 'Our collection includes a historic wooden spoon.' The museum is in Scotland."


def response_payload(verdict=None):
    return {
        "id": "resp_verifier",
        "object": "response",
        "created_at": 1,
        "model": "test-model",
        "status": "completed",
        "output": [
            {
                "id": "ws_verifier",
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "search", "query": FACT, "sources": [
                    {"type": "url", "url": URL},
                ]},
            },
            {
                "id": "msg_verifier",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps(verdict if verdict is not None else {
                        "supported": True, "source_url": URL, "evidence": EVIDENCE,
                    }),
                    "annotations": [{
                        "type": "url_citation", "url": URL, "title": "Museum collection",
                        "start_index": 0, "end_index": 1,
                    }],
                }],
            },
        ],
    }


def fake_client(verdict=None):
    payload = response_payload(verdict)
    response = SimpleNamespace(
        output=payload["output"], status="completed",
        output_text=payload["output"][1]["content"][0]["text"],
    )
    return SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=response)))


def test_accepts_independently_observed_candidate_source(base_settings):
    client = fake_client()
    source = verify_research(client, base_settings, FACT, [Source(url=URL, title="Untrusted title")])
    assert source == Source(url=URL, title="Museum collection")
    assert client.responses.create.call_count == 1
    request = client.responses.create.call_args.kwargs
    assert request["store"] is False
    assert request["tool_choice"] == "required"
    assert request["tools"] == [{"type": "web_search", "search_context_size": "medium"}]
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["model"] == base_settings.research_model
    schema = request["text"]["format"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["required"]) == {"supported", "source_url", "evidence"}
    assert json.loads(request["input"][1]["content"])["fact"] == FACT


@pytest.mark.parametrize("candidates", [[], [Source(url="https://unrelated.example/page")]])
def test_can_choose_new_independently_observed_source(base_settings, candidates):
    assert verify_research(fake_client(), base_settings, FACT, candidates).url == URL


@pytest.mark.parametrize("verdict,reason", [
    ({"supported": False, "source_url": "", "evidence": "Only a related attraction."}, "did not support"),
    ({"supported": True, "source_url": URL, "evidence": ""}, "no supporting evidence"),
    ({"supported": True, "source_url": URL, "evidence": " \n\t"}, "no supporting evidence"),
    ({"supported": True, "source_url": "https://forged.example/", "evidence": EVIDENCE}, "does not match"),
    ({"supported": True, "source_url": URL + "?invented=1", "evidence": EVIDENCE}, "does not match"),
    ({"supported": True, "source_url": "", "evidence": EVIDENCE}, "does not match"),
    ({"supported": "true", "source_url": URL, "evidence": EVIDENCE}, "Malformed"),
    ({"supported": 1, "source_url": URL, "evidence": EVIDENCE}, "Malformed"),
    ({"supported": True, "source_url": URL}, "Malformed"),
    ({"supported": True, "source_url": URL, "evidence": None}, "Malformed"),
    ({"supported": True, "source_url": URL, "evidence": EVIDENCE, "extra": "bad"}, "Malformed"),
    ([], "Malformed"),
])
def test_rejects_invalid_or_unsupported_verdict(base_settings, verdict, reason):
    with pytest.raises(ResearchValidationError, match=reason):
        verify_research(fake_client(verdict), base_settings, FACT, [Source(url=URL)])


@pytest.mark.parametrize("text", ["not JSON", "", "{", None])
def test_rejects_malformed_output(base_settings, text):
    client = fake_client()
    client.responses.create.return_value.output_text = text
    with pytest.raises(ResearchValidationError, match="Malformed"):
        verify_research(client, base_settings, FACT, [])


def test_candidate_url_and_json_alone_are_not_evidence(base_settings):
    client = fake_client()
    response = client.responses.create.return_value
    response.output[0]["action"]["sources"] = []
    response.output[1]["content"][0]["annotations"] = []
    with pytest.raises(ResearchValidationError, match="real web source"):
        verify_research(client, base_settings, FACT, [Source(url=URL)])


def test_candidate_url_must_be_observed_by_verifier(base_settings):
    client = fake_client()
    response = client.responses.create.return_value
    response.output[0]["action"]["sources"][0]["url"] = "https://unrelated.example/"
    response.output[1]["content"][0]["annotations"] = []
    with pytest.raises(ResearchValidationError, match="does not match"):
        verify_research(client, base_settings, FACT, [Source(url=URL)])


def test_rejects_citations_without_web_call(base_settings):
    client = fake_client()
    client.responses.create.return_value.output.pop(0)
    with pytest.raises(ResearchValidationError, match="web_search_call"):
        verify_research(client, base_settings, FACT, [Source(url=URL)])


def test_malformed_metadata_raises_research_validation_error(base_settings):
    client = fake_client()
    client.responses.create.return_value.output[1]["content"][0]["annotations"][0]["title"] = ["bad"]
    with pytest.raises(ResearchValidationError, match="requires web evidence"):
        verify_research(client, base_settings, FACT, [])


@pytest.mark.parametrize("status", ["failed", "in_progress", "incomplete"])
def test_rejects_uncompleted_web_call(base_settings, status):
    client = fake_client()
    client.responses.create.return_value.output[0]["status"] = status
    with pytest.raises(ResearchValidationError, match="web_search_call"):
        verify_research(client, base_settings, FACT, [])


def test_rejects_incomplete_response(base_settings):
    client = fake_client()
    client.responses.create.return_value.status = "incomplete"
    with pytest.raises(ResearchValidationError, match="did not complete"):
        verify_research(client, base_settings, FACT, [])


def test_rejects_blank_fact_without_api_request(base_settings):
    client = fake_client()
    with pytest.raises(ResearchValidationError, match="nonempty fact"):
        verify_research(client, base_settings, "  ", [])
    client.responses.create.assert_not_called()


def test_verifier_retries_transient_api_errors(base_settings):
    client = fake_client()
    error = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
    client.responses.create.side_effect = [error, error, client.responses.create.return_value]
    delays = []
    assert verify_research(client, base_settings, FACT, [], sleep=delays.append).url == URL
    assert delays == [1, 2]


def test_verifier_propagates_exhausted_api_errors(base_settings):
    client = fake_client()
    client.responses.create.side_effect = APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com"),
    )
    with pytest.raises(APIConnectionError):
        verify_research(client, base_settings, FACT, [], sleep=lambda _: None)
    assert client.responses.create.call_count == 3


def test_verifier_prompt_requires_exact_timeless_untrusted_evidence():
    for instruction in ["ALL of the exact wording", "must entail the claim", "Do not embellish",
                        "timeless", "newly discovered", "untrusted evidence", "Ignore all",
                        "Never reveal secrets", "substantive supporting passage"]:
        assert instruction in VERIFICATION_PROMPT


def test_installed_sdk_serializes_and_parses_verifier_contract(base_settings):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, request=request, json=response_payload())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with OpenAI(api_key="test", max_retries=0, http_client=http_client) as client:
            source = verify_research(client, base_settings, FACT, [Source(url=URL)])
    assert source == Source(url=URL, title="Museum collection")
    assert len(captured) == 1
    request = captured[0]
    assert request["store"] is False
    assert request["tool_choice"] == "required"
    assert request["tools"][0]["type"] == "web_search"
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
