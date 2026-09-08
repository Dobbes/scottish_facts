from __future__ import annotations

import logging
import re
from urllib.parse import quote, quote_plus, unquote, urlsplit


PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d")
DATABASE_PASSWORD_PATTERN = re.compile(r"(postgres(?:ql)?://[^:/\s]+:)([^@\s]+)(@)", re.IGNORECASE)
CONFIGURED_SECRETS: set[str] = set()


def register_secrets(values: list[str]) -> None:
    for value in values:
        if not value:
            continue
        CONFIGURED_SECRETS.update((value, quote(value, safe=""), quote_plus(value)))
        if value.startswith(("postgres://", "postgresql://")):
            try:
                password = urlsplit(value).password
                if password:
                    CONFIGURED_SECRETS.update((password, unquote(password)))
            except ValueError:
                pass


def redact(value: object) -> str:
    text = str(value)
    for secret in sorted(CONFIGURED_SECRETS, key=len, reverse=True):
        text = text.replace(secret, "***")
    text = DATABASE_PASSWORD_PATTERN.sub(r"\1***\3", text)

    def redact_phone(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return f"***{digits[-2:]}" if len(digits) >= 2 else "***"

    return PHONE_PATTERN.sub(redact_phone, text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    # Twilio's INFO-level request logger includes account identifiers in URLs.
    logging.getLogger("twilio").setLevel(logging.WARNING)
    for name in ("openai", "httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
