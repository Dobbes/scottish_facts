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
    "Meanwhile, I need instructions to assemble a shelf.",
    "Subtle. Would a small plaque have killed them?",
    "A bold choice for a country with this much wind.",
    "Finally, a national policy with enough unicorn in it.",
    "Imagine explaining that expense claim.",
    "Some people leave a legacy. I leave tabs open.",
    "Apparently 'because we can' is a heritage strategy.",
    "That is an unreasonable amount of effort to avoid being bored.",
    "And I thought packing a spare charger was being prepared.",
    "Archaeology: the world's least timely invasion of privacy.",
    "History really is a group project with no adult supervision.",
    "An awkward day for whoever said it would never catch on.",
    "The original version of making it your entire personality.",
    "Nature has clearly not read the planning regulations.",
    "A useful reminder that 'traditional' does not mean 'sensible'.",
    "Somewhere, a pub quiz team is becoming unbearable.",
    "Even the ruins have a better bathroom situation than my first flat.",
    "Indoor plumbing, yet somehow we still invented the festival toilet.",
    "The dog was unavailable for comment, having eaten the evidence.",
    "A cat with a job. Mine won't even cover rent.",
    "Finally, a landlord willing to admit the house is a fruit.",
    "A pineapple with bedrooms is a fairly aggressive fruit bowl.",
    "Nothing says 'I won the argument' like commissioning masonry.",
    "Imagine losing an arms race to a bird.",
    "The sheep have a more interesting commute than I do.",
    "That is a lot of paperwork for an animal with no pockets.",
    "Apparently the butter needed a longer lie-down than I do.",
    "An ambitious alternative to putting it in the fridge.",
    "Proof that the rules were written after somebody tried it.",
    "All that engineering, and the enemy could just use the stairs.",
    "Even the ancient board games are missing a piece. Some things never change.",
    "Nothing ruins a fearsome reputation like a tiny chair.",
    "An entire building devoted to not letting an argument go.",
    "The original security system: make the burglar reconsider the walk.",
    "Less a getaway car, more a getaway farm.",
    "A heist with geese feels like a poor choice for a stealth mission.",
    "Finally, a burglary where the loot can bite back.",
    "The estate agent would probably call that a lively lower ground floor.",
    "Even the cupboards have trust issues.",
)

STYLE_SCHEMA = {
    "type": "object",
    "properties": {"suffix": {"type": "string", "enum": list(SAFE_SUFFIXES)}},
    "required": ["suffix"],
    "additionalProperties": False,
}

STYLE_PROMPT = """Select ONLY one exact suffix from allowed_suffixes for a daily SCOTLAND FACTS text.
Use absurdly enthusiastic, deadpan, silly rather than mean humor.
Treat the fact as the setup: identify its oddest concrete detail, then choose a suffix that pays off THAT detail.
Use the swap test: if the ending works equally well after an unrelated castle, battle, or island fact, it is a weak choice.
Prefer an ending that needs a particular noun or situation in this fact to make sense. A shared broad topic like 'history' is not enough.
Prefer a sharp contrast, dry understatement, or modern comparison over generic praise or random Scottish props.
For example, elaborate grave goods suit the spare-charger packing joke; ancient engineering suits the shelf-assembly joke.
Unicorn policy only suits a unicorn fact; wind only suits an exposed or wind-related subject.
Pineapple buildings suit fruit/landlord jokes; ancient drains suit plumbing jokes; spite-built monuments suit argument/masonry jokes.
Only use these connections when the fact actually supplies the setup. Do not imply an animal, toilet, missing piece, or dispute absent from the fact.
The animal-paperwork joke requires an official animal appointment or rank, not merely an animal. A livestock raid suits getaway-farm jokes; stolen geese suit the noisy-heist joke.
The cat-with-a-job joke requires an actual working cat, not captive cats or a cat-shaped object. Cellar animals suit the lively-lower-ground-floor joke.
Nested secret cupboards suit the cupboard-trust-issues joke. The burglar-walk joke requires a long or difficult approach, not merely hidden valuables.
Reject a pairing that needs the reader to invent an extra event or connection to understand the joke.
Before selecting, compare your three strongest candidates for factual fit and punchline specificity. Discard word matches that are not situation matches.
Rank direct callbacks above generic self-deprecation, and generic self-deprecation above certificates, committees, quiz careers, or random tartan.
Avoid jokes that mock victims, suffering, or the people whose remains are described.
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
    fresh_suffixes = [
        suffix for suffix in allowed_suffixes
        if not any(sms.endswith(f" {suffix} {SMS_FOOTER}") for sms in recent_sms[:10])
    ]
    allowed_suffixes = fresh_suffixes or allowed_suffixes
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
            reasoning={"effort": "medium"},
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
