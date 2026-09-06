from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from scotland_facts.models import Source


class SourceExtractionError(ValueError):
    pass


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _items(value: Any) -> Iterable[Any]:
    return value if isinstance(value, (list, tuple)) else ()


def _valid_web_url(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def extract_sources(response: Any) -> tuple[list[Source], bool]:
    annotations: list[Source] = []
    search_sources: list[Source] = []
    web_search_performed = False

    for item in _items(_get(response, "output", [])):
        item_type = _get(item, "type")
        if item_type == "web_search_call":
            web_search_performed = True
            action = _get(item, "action", {})
            for raw_source in _items(_get(action, "sources", [])):
                if isinstance(raw_source, str):
                    url, title = raw_source, None
                else:
                    url = _get(raw_source, "url")
                    title = _get(raw_source, "title")
                if _valid_web_url(url):
                    search_sources.append(Source(url=url, title=title or None))
        if item_type != "message":
            continue
        for part in _items(_get(item, "content", [])):
            if _get(part, "type") not in {"output_text", "text"}:
                continue
            for annotation in _items(_get(part, "annotations", [])):
                if _get(annotation, "type") != "url_citation":
                    continue
                url = _get(annotation, "url")
                if _valid_web_url(url):
                    annotations.append(Source(url=url, title=_get(annotation, "title") or None))

    combined: list[Source] = []
    seen: set[str] = set()
    for source in [*annotations, *search_sources]:
        if source.url not in seen:
            combined.append(source)
            seen.add(source.url)
    return combined, web_search_performed


def require_web_sources(response: Any) -> list[Source]:
    sources, searched = extract_sources(response)
    if not searched:
        raise SourceExtractionError("Response did not contain a web_search_call")
    if not sources:
        raise SourceExtractionError("Response did not contain a real web source")
    return sources
