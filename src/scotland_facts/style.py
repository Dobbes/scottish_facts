from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import emoji
from pydantic import ValidationError

from scotland_facts.config import Settings
from scotland_facts.models import StyleSuffix
from scotland_facts.research import URL_PATTERN, retry_openai


RESERVED_KEYWORDS = (
    "STOP",
    "STOPALL",
    "UNSUBSCRIBE",
    "CANCEL",
    "END",
    "REVOKE",
    "OPTOUT",
    "QUIT",
    "START",
    "UNSTOP",
    "HELP",
    "INFO",
)
COMMAND_PATTERN = re.compile(
    rf"\b(?:reply|text|send|respond)\b(?:\s+(?:with|using))?[\s:;,\.\-\"'()\[\]]+(?:{'|'.join(RESERVED_KEYWORDS)})\b",
    re.IGNORECASE,
)

STYLE_SCHEMA = {
    "type": "object",
    "properties": {"suffix": {"type": "string"}},
    "required": ["suffix"],
    "additionalProperties": False,
}

STYLE_PROMPT = """You write ONLY the short joke/subscription suffix for a daily automated SCOTLAND FACTS text.
Use classic Cat Facts prank energy: absurdly enthusiastic, deadpan, fake automated subscription, mildly intrusive, and silly rather than mean.
The real factual sentence is supplied separately and must not be rewritten, restated, contradicted, or embellished.
Return only a short suffix that follows it. Vary the structure and avoid recent endings.
The suffix must be at most 90 Unicode characters including spaces and punctuation.
Fake commands may use harmless nonsense words such as HAGGIS, BAGPIPE, THISTLE, or KILT.
Never instruct the recipient to reply with a real Twilio keyword: STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, REVOKE, OPTOUT, QUIT, START, UNSTOP, HELP, or INFO.
Do not use URLs, emoji, names, or line breaks. Prefer one sentence."""


class StyleValidationError(ValueError):
    pass


def request_suffix(
    client: Any,
    settings: Settings,
    fact_text: str,
    recent_sms: list[str],
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    payload = {
        "fact_for_context_only": fact_text,
        "recent_sms_endings_to_avoid": recent_sms[:10],
        "reserved_keywords": list(RESERVED_KEYWORDS),
        "maximum_suffix_characters": settings.style_suffix_max_chars,
    }
    response = retry_openai(
        lambda: client.responses.create(
            model=settings.style_model,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "style_suffix",
                    "strict": True,
                    "schema": STYLE_SCHEMA,
                }
            },
            input=[
                {"role": "developer", "content": STYLE_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
            ],
        ),
        sleep=sleep,
    )
    try:
        return StyleSuffix.model_validate_json(response.output_text).suffix
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        raise StyleValidationError(f"Malformed style output: {exc}") from exc


def validate_suffix(suffix: str, max_chars: int) -> str:
    value = suffix.strip()
    if not value or len(value) > max_chars:
        raise StyleValidationError(f"Suffix must be 1-{max_chars} characters")
    if value.upper().startswith("SCOTLAND FACTS:"):
        raise StyleValidationError("Suffix must not contain the SMS prefix")
    if "\n" in value or "\r" in value:
        raise StyleValidationError("Suffix must be one line")
    if URL_PATTERN.search(value):
        raise StyleValidationError("Suffix must not contain a URL")
    if emoji.emoji_list(value):
        raise StyleValidationError("Suffix must not contain emoji")
    if COMMAND_PATTERN.search(value):
        raise StyleValidationError("Suffix contains a real SMS control command")
    return value


def build_sms(fact_text: str, suffix: str, max_chars: int) -> str:
    prefix = "SCOTLAND FACTS:"
    sms = f"{prefix} {fact_text} {suffix}".strip()
    if not sms.startswith(f"{prefix} {fact_text}"):
        raise StyleValidationError("Accepted fact was not preserved verbatim")
    if len(sms) > max_chars:
        raise StyleValidationError(f"Final SMS exceeds {max_chars} characters")
    if "\n" in sms or "\r" in sms:
        raise StyleValidationError("Final SMS must be one line")
    if URL_PATTERN.search(sms):
        raise StyleValidationError("Final SMS must not contain a URL")
    if emoji.emoji_list(sms):
        raise StyleValidationError("Final SMS must not contain emoji")
    if COMMAND_PATTERN.search(sms):
        raise StyleValidationError("Final SMS contains a real SMS control command")
    return sms
