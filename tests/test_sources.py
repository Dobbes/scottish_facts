from types import SimpleNamespace

import pytest

from scotland_facts.sources import SourceExtractionError, extract_sources, require_web_sources


def message_annotation(url="https://a.example/fact", title="A title"):
    return SimpleNamespace(
        type="message",
        content=[
            SimpleNamespace(
                type="output_text",
                annotations=[SimpleNamespace(type="url_citation", url=url, title=title)],
            )
        ],
    )


def search_call(sources=None):
    return SimpleNamespace(
        type="web_search_call", action=SimpleNamespace(sources=[] if sources is None else sources)
    )


def test_url_citation_extracted():
    sources, searched = extract_sources(SimpleNamespace(output=[search_call(), message_annotation()]))
    assert searched is True
    assert sources[0].url == "https://a.example/fact"
    assert sources[0].title == "A title"


def test_search_action_source_is_fallback():
    response = SimpleNamespace(
        output=[search_call([{"url": "https://b.example/page", "title": "B"}])]
    )
    assert require_web_sources(response)[0].url == "https://b.example/page"


def test_annotation_metadata_wins_for_duplicate_url():
    response = SimpleNamespace(
        output=[
            search_call([{"url": "https://a.example/fact", "title": "Search title"}]),
            message_annotation(title="Citation title"),
        ]
    )
    sources = require_web_sources(response)
    assert len(sources) == 1
    assert sources[0].title == "Citation title"


def test_multiple_sources_are_deduplicated_in_first_seen_order():
    response = SimpleNamespace(
        output=[
            message_annotation(),
            search_call(
                [
                    {"url": "https://a.example/fact", "title": "duplicate"},
                    {"url": "https://b.example/fact", "title": "second"},
                ]
            ),
        ]
    )
    assert [source.url for source in require_web_sources(response)] == [
        "https://a.example/fact",
        "https://b.example/fact",
    ]


def test_no_real_source_rejected():
    with pytest.raises(SourceExtractionError, match="real web source"):
        require_web_sources(SimpleNamespace(output=[search_call()]))


def test_no_web_search_call_rejected_even_with_annotation():
    with pytest.raises(SourceExtractionError, match="web_search_call"):
        require_web_sources(SimpleNamespace(output=[message_annotation()]))


def test_non_http_source_rejected():
    with pytest.raises(SourceExtractionError):
        require_web_sources(
            SimpleNamespace(output=[search_call([{"url": "file:///secret", "title": "bad"}])])
        )


@pytest.mark.parametrize("url", ["https://[broken", "https://:80", "not a URL", None])
def test_malformed_source_url_is_ignored(url):
    with pytest.raises(SourceExtractionError, match="real web source"):
        require_web_sources(SimpleNamespace(output=[search_call([{"url": url}])]))


@pytest.mark.parametrize("status", ["failed", "in_progress", "incomplete"])
def test_uncompleted_web_call_does_not_count_as_search(status):
    call = search_call([{"url": "https://a.example/fact"}])
    call.status = status
    with pytest.raises(SourceExtractionError, match="web_search_call"):
        require_web_sources(SimpleNamespace(output=[call, message_annotation()]))


def test_dictionary_response_extracts_metadata_not_json_text():
    response = {"output": [
        {"type": "web_search_call", "status": "completed", "action": {
            "sources": [{"url": "https://a.example/fact", "title": "Actual metadata"}],
        }},
        {"type": "message", "content": [{"type": "output_text", "text":
            '{"source_url": "https://forged.example/"}', "annotations": []}]},
    ]}
    sources = require_web_sources(response)
    assert [source.url for source in sources] == ["https://a.example/fact"]
