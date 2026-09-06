from __future__ import annotations

import pytest
from pydantic import ValidationError

from scotland_facts.config import ConfigMode, ENV_FIELDS, Settings, load_settings


def clear_settings_env(monkeypatch):
    monkeypatch.setattr("scotland_facts.config.load_dotenv", lambda: False)
    for name in ENV_FIELDS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_parse(monkeypatch):
    clear_settings_env(monkeypatch)
    settings = load_settings()
    assert settings.app_timezone == "America/New_York"
    assert settings.embedding_dimensions == 1536
    assert settings.semantic_similarity_threshold == 0.88


def test_missing_production_secret_fails(monkeypatch):
    clear_settings_env(monkeypatch)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        load_settings(ConfigMode.PRODUCTION)


def test_dry_run_does_not_require_twilio(monkeypatch):
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://example")
    assert load_settings(ConfigMode.DRY_RUN).twilio_api_key_sid is None


def test_embedding_dimension_mismatch_fails():
    with pytest.raises(ValidationError, match="1536"):
        Settings(embedding_dimensions=100)


def test_invalid_timezone_fails_configuration():
    with pytest.raises(ValidationError, match="Unknown IANA timezone"):
        Settings(app_timezone="Not/A_Real_Zone")


def test_secret_values_are_masked():
    settings = Settings(openai_api_key="super-secret")
    assert "super-secret" not in repr(settings)
