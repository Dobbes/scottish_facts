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
SMS_FOOTER = "Reply STOP to opt out."
COMMAND_PATTERN = re.compile(
    rf"\b(?:reply|text|send|respond)\b(?:\s+(?:with|using))?"
    rf"(?:\s+(?:the\s+)?word)?[\s:;,\.\-\"'()\[\]]+(?:{'|'.join(RESERVED_KEYWORDS)})\b",
    re.IGNORECASE,
)

# Exact reviewed prose, not a blacklist that disguised commands can evade.
SAFE_SUFFIXES = (
    "Your compulsory education resumes tomorrow.",
    "The lessons never stop, apparently.",
    "Your imaginary tartan certificate is in the post.",
    "The bagpipe committee considers this progress.",
    "A small round of applause from the imaginary haggis council.",
    "Another fact for your increasingly specific quiz career.",
    "The unicorns have declined to comment.",
    "Your brain now has slightly more tartan in it.",
)

STYLE_SCHEMA = {
    "type": "object",
    "properties": {"suffix": {"type": "string", "enum": list(SAFE_SUFFIXES)}},
    "required": ["suffix"],
    "additionalProperties": False,
}

STYLE_PROMPT = """Select ONLY one exact suffix from allowed_suffixes for a daily SCOTLAND FACTS text.
Use absurdly enthusiastic, deadpan, silly rather than mean humor.
The real factual sentence is supplied separately and must not be rewritten, restated, contradicted, or embellished.
Return only a short suffix that follows it. Vary the structure and avoid recent endings.
The suffix must be at most 90 Unicode characters including spaces and punctuation.
Never invent or modify a suffix. Never give reply instructions, fake commands, or subscription controls.
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
    suffix_budget = min(
        settings.style_suffix_max_chars,
        min(settings.sms_max_chars, 300) - len(f"SCOTLAND FACTS: {fact_text}  {SMS_FOOTER}"),
    )
    allowed_suffixes = [suffix for suffix in SAFE_SUFFIXES if len(suffix) <= suffix_budget]
    if not allowed_suffixes:
        raise StyleValidationError("No reviewed suffix fits the complete SMS character budget")
    payload = {
        "allowed_suffixes": allowed_suffixes,
        "fact_for_context_only": fact_text,
        "recent_sms_endings_to_avoid": recent_sms[:10],
        "reserved_keywords": list(RESERVED_KEYWORDS),
        "maximum_suffix_characters": suffix_budget,
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
                    "schema": {
                        **STYLE_SCHEMA,
                        "properties": {"suffix": {"type": "string", "enum": allowed_suffixes}},
                    },
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
    if value not in SAFE_SUFFIXES:
        raise StyleValidationError("Suffix must be exact reviewed prose; no generated control commands")
    return value


def build_sms(fact_text: str, suffix: str, max_chars: int) -> str:
    prefix = "SCOTLAND FACTS:"
    content = f"{prefix} {fact_text} {suffix}".strip()
    # Only application-owned compliance text may introduce a control instruction.
    if COMMAND_PATTERN.search(content):
        raise StyleValidationError("Final SMS contains a real SMS control command")
    sms = f"{content} {SMS_FOOTER}"
    if not sms.startswith(f"{prefix} {fact_text}"):
        raise StyleValidationError("Accepted fact was not preserved verbatim")
    max_chars = min(max_chars, 300)
    if len(sms) > max_chars:
        raise StyleValidationError(f"Final SMS exceeds {max_chars} characters")
    if "\n" in sms or "\r" in sms:
        raise StyleValidationError("Final SMS must be one line")
    if URL_PATTERN.search(sms):
        raise StyleValidationError("Final SMS must not contain a URL")
    if emoji.emoji_list(sms):
        raise StyleValidationError("Final SMS must not contain emoji")
    return sms
