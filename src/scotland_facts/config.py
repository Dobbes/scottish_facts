from __future__ import annotations

import os
import re
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from scotland_facts.logging_utils import register_secrets


class ConfigMode(StrEnum):
    DOCTOR = "doctor"
    DRY_RUN = "dry_run"
    PRODUCTION = "production"
    MIGRATE = "migrate"
    CALIBRATE = "calibrate"
    HISTORY = "history"
    RECONCILE = "reconcile"
    SUPPRESS = "suppress"
    RENEW = "renew"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_timezone: str = "America/New_York"
    research_model: str = "gpt-5.6-luna"
    style_model: str = "gpt-5.6-luna"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, gt=0)
    semantic_similarity_threshold: float = Field(default=0.88, ge=-1, le=1)
    recent_subject_window_days: int = Field(default=14, ge=1)
    max_research_attempts: int = Field(default=5, ge=1)
    max_style_attempts: int = Field(default=2, ge=1)
    fact_max_chars: int = Field(default=180, ge=1)
    style_suffix_max_chars: int = Field(default=90, ge=1)
    sms_max_chars: int = Field(default=300, ge=1)
    twilio_status_poll_seconds: int = Field(default=30, ge=0)
    twilio_http_timeout_seconds: int = Field(default=15, ge=1, le=60)
    sms_send_enabled: bool = False
    recipient_consent_confirmed: bool = False
    twilio_status_poll_interval_seconds: int = Field(default=2, ge=1)

    openai_api_key: SecretStr | None = None
    supabase_db_url: SecretStr | None = None
    twilio_account_sid: SecretStr | None = None
    twilio_api_key_sid: SecretStr | None = None
    twilio_api_key_secret: SecretStr | None = None
    twilio_from_number: SecretStr | None = None
    recipient_number: SecretStr | None = None
    father_in_law_number: SecretStr | None = None

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_embedding_contract(self) -> "Settings":
        register_secrets([value.get_secret_value() for value in self.__dict__.values()
                          if isinstance(value, SecretStr)])
        if self.embedding_model == "text-embedding-3-small" and self.embedding_dimensions != 1536:
            raise ValueError("text-embedding-3-small must use 1536 dimensions")
        return self

    def require(self, mode: ConfigMode) -> "Settings":
        required: dict[ConfigMode, tuple[str, ...]] = {
            ConfigMode.DOCTOR: (),
            ConfigMode.DRY_RUN: ("openai_api_key", "supabase_db_url"),
            ConfigMode.PRODUCTION: (
                "openai_api_key",
                "supabase_db_url",
                "twilio_account_sid",
                "twilio_api_key_sid",
                "twilio_api_key_secret",
                "twilio_from_number",
                "recipient_number",
            ),
            ConfigMode.MIGRATE: ("supabase_db_url",),
            ConfigMode.CALIBRATE: ("openai_api_key",),
            ConfigMode.HISTORY: ("supabase_db_url",),
            ConfigMode.SUPPRESS: ("supabase_db_url",),
            ConfigMode.RENEW: ("supabase_db_url",),
            ConfigMode.RECONCILE: (
                "supabase_db_url", "twilio_account_sid", "twilio_api_key_sid",
                "twilio_api_key_secret",
            ),
        }
        missing = [name.upper() for name in required[mode] if not getattr(self, name)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        if mode in {ConfigMode.DOCTOR, ConfigMode.DRY_RUN, ConfigMode.PRODUCTION}:
            self.recipient_slots()
            for name in ("twilio_from_number", "recipient_number", "father_in_law_number"):
                value = getattr(self, name)
                if value and not re.fullmatch(r"\+[1-9][0-9]{7,14}", value.get_secret_value()):
                    raise ValueError(f"{name.upper()} must use E.164 phone format")
        if mode == ConfigMode.PRODUCTION:
            self.require_sending()
        return self

    def require_sending(self) -> None:
        if not self.sms_send_enabled:
            raise ValueError("SMS_SEND_ENABLED must be true for production sending")
        if not self.recipient_consent_confirmed:
            raise ValueError("RECIPIENT_CONSENT_CONFIRMED must be true for all configured recipients")

    def recipient_slots(self) -> tuple[str, ...]:
        """Return stable, phone-free delivery identities; never silently duplicate a send."""
        if self.father_in_law_number and not self.recipient_number:
            raise ValueError("RECIPIENT_NUMBER is required when FATHER_IN_LAW_NUMBER is configured")
        slots = tuple(slot for slot, field in (
            ("primary", "recipient_number"), ("secondary", "father_in_law_number")
        ) if getattr(self, field))
        values = [self.recipient_secret(slot) for slot in slots]
        if len(values) != len(set(values)):
            raise ValueError("Configured recipient numbers must be distinct")
        if self.twilio_from_number and self.secret("twilio_from_number") in values:
            raise ValueError("A recipient number must not equal TWILIO_FROM_NUMBER")
        return slots

    def recipient_secret(self, slot: str) -> str:
        fields = {"primary": "recipient_number", "secondary": "father_in_law_number"}
        if slot not in fields:
            raise ValueError("Unknown recipient slot")
        return self.secret(fields[slot])

    def secret(self, name: str) -> str:
        value = getattr(self, name)
        if value is None:
            raise ValueError(f"Missing required setting: {name.upper()}")
        return value.get_secret_value()


ENV_FIELDS = {
    "SMS_SEND_ENABLED": "sms_send_enabled",
    "RECIPIENT_CONSENT_CONFIRMED": "recipient_consent_confirmed",
    "TWILIO_HTTP_TIMEOUT_SECONDS": "twilio_http_timeout_seconds",
    "APP_TIMEZONE": "app_timezone",
    "RESEARCH_MODEL": "research_model",
    "STYLE_MODEL": "style_model",
    "EMBEDDING_MODEL": "embedding_model",
    "EMBEDDING_DIMENSIONS": "embedding_dimensions",
    "SEMANTIC_SIMILARITY_THRESHOLD": "semantic_similarity_threshold",
    "RECENT_SUBJECT_WINDOW_DAYS": "recent_subject_window_days",
    "MAX_RESEARCH_ATTEMPTS": "max_research_attempts",
    "MAX_STYLE_ATTEMPTS": "max_style_attempts",
    "FACT_MAX_CHARS": "fact_max_chars",
    "STYLE_SUFFIX_MAX_CHARS": "style_suffix_max_chars",
    "SMS_MAX_CHARS": "sms_max_chars",
    "TWILIO_STATUS_POLL_SECONDS": "twilio_status_poll_seconds",
    "TWILIO_STATUS_POLL_INTERVAL_SECONDS": "twilio_status_poll_interval_seconds",
    "OPENAI_API_KEY": "openai_api_key",
    "SUPABASE_DB_URL": "supabase_db_url",
    "TWILIO_ACCOUNT_SID": "twilio_account_sid",
    "TWILIO_API_KEY_SID": "twilio_api_key_sid",
    "TWILIO_API_KEY_SECRET": "twilio_api_key_secret",
    "TWILIO_FROM_NUMBER": "twilio_from_number",
    "RECIPIENT_NUMBER": "recipient_number",
    "FATHER_IN_LAW_NUMBER": "father_in_law_number",
}


def load_settings(mode: ConfigMode = ConfigMode.DOCTOR) -> Settings:
    load_dotenv()
    values = {field: os.environ[name] for name, field in ENV_FIELDS.items() if os.environ.get(name)}
    register_secrets([str(value) for field, value in values.items()
                      if field in {"openai_api_key", "supabase_db_url", "twilio_account_sid",
                                   "twilio_api_key_sid", "twilio_api_key_secret",
                                    "twilio_from_number", "recipient_number", "father_in_law_number"}])
    operational_fields = {
        ConfigMode.SUPPRESS: {"supabase_db_url"},
        ConfigMode.RENEW: {"supabase_db_url", "sms_send_enabled", "recipient_consent_confirmed"},
        ConfigMode.RECONCILE: {
            "supabase_db_url", "twilio_account_sid", "twilio_api_key_sid",
            "twilio_api_key_secret", "twilio_http_timeout_seconds",
        },
    }
    if mode in operational_fields:
        values = {field: value for field, value in values.items()
                  if field in operational_fields[mode]}
    return Settings.model_validate(values).require(mode)
