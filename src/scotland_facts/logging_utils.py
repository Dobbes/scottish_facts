from __future__ import annotations

import logging
import re


PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d")
DATABASE_PASSWORD_PATTERN = re.compile(r"(postgres(?:ql)?://[^:/\s]+:)([^@\s]+)(@)", re.IGNORECASE)


def redact(value: object) -> str:
    text = str(value)
    text = DATABASE_PASSWORD_PATTERN.sub(r"\1***\3", text)

    def redact_phone(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return f"***{digits[-2:]}" if len(digits) >= 2 else "***"

    return PHONE_PATTERN.sub(redact_phone, text)


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Twilio's INFO-level request logger includes account identifiers in URLs.
    logging.getLogger("twilio").setLevel(logging.WARNING)
