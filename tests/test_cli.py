from types import SimpleNamespace

import scotland_facts.cli as cli
from scotland_facts.config import Settings
import pytest


def test_live_doctor_uses_valid_minimal_openai_request_and_never_sends(monkeypatch):
    captured = {}

    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="OK")

    class IncomingPhoneNumbers:
        def list(self, **kwargs):
            captured["twilio"] = kwargs
            return [SimpleNamespace(sid="PNtest")]

    monkeypatch.setattr(
        cli, "OpenAI", lambda **kwargs: SimpleNamespace(responses=Responses())
    )
    monkeypatch.setattr(
        cli,
        "make_twilio_client",
        lambda settings: SimpleNamespace(incoming_phone_numbers=IncomingPhoneNumbers()),
    )
    settings = Settings(
        openai_api_key="test",
        twilio_account_sid="ACtest",
        twilio_api_key_sid="SKtest",
        twilio_api_key_secret="test",
        twilio_from_number="TEST_SENDER",
    )
    assert cli.doctor(settings, live=True) == 0
    assert captured["max_output_tokens"] == 16
    assert captured["store"] is False
    assert captured["twilio"] == {"phone_number": "TEST_SENDER", "limit": 1}


@pytest.mark.parametrize("problems,exit_code", [(0, 0), (1, 1)])
def test_reconcile_cli_is_non_sending_and_closes_database(monkeypatch, problems, exit_code):
    calls = []
    db = SimpleNamespace(close=lambda: calls.append("close"))
    monkeypatch.setattr(cli, "load_settings", lambda mode: Settings())
    monkeypatch.setattr(cli.Database, "connect", lambda settings: db)
    monkeypatch.setattr(cli, "make_twilio_client", lambda settings: object())
    monkeypatch.setattr(cli, "reconcile_recent", lambda database, client: problems)
    monkeypatch.setattr(cli, "run_workflow", lambda *a, **k: pytest.fail("must not generate"))
    assert cli.main(["reconcile"]) == exit_code
    assert calls == ["close"]


@pytest.mark.parametrize("consent,enabled,flag,expected", [
    (False, False, True, 1), (True, True, True, 1),
    (True, False, False, 1), (True, False, True, 0),
])
def test_explicit_subscription_renewal(monkeypatch, consent, enabled, flag, expected):
    calls = []
    settings = Settings(recipient_consent_confirmed=consent, sms_send_enabled=enabled)
    monkeypatch.setattr(cli, "load_settings", lambda mode: settings)
    monkeypatch.setattr(cli.Database, "connect", lambda settings: SimpleNamespace(
        set_subscription_suppressed=lambda value: calls.append(value), close=lambda: None))
    args = ["subscription", "renew"] + (["--confirm-renewed-consent"] if flag else [])
    assert cli.main(args) == expected
    assert calls == ([False] if expected == 0 else [])


def test_suppress_cli_needs_no_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "load_settings", lambda mode: Settings())
    monkeypatch.setattr(cli.Database, "connect", lambda settings: SimpleNamespace(
        set_subscription_suppressed=lambda value: calls.append(value), close=lambda: None))
    assert cli.main(["subscription", "suppress"]) == 0
    assert calls == [True]


@pytest.mark.parametrize("secured,expected", [(True, 0), (False, 1)])
def test_doctor_checks_deployment_security_without_provider_calls(monkeypatch, secured, expected):
    queries = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            queries.append(sql)
            if "information_schema.tables" in sql:
                return SimpleNamespace(fetchall=lambda: [(name,) for name in (
                    "facts", "generation_runs", "generation_attempts", "schema_migrations", "subscription_state", "sms_deliveries")])
            return SimpleNamespace(fetchone=lambda: (secured,) if "bool_and" in sql else (1,))

    monkeypatch.setattr(cli.psycopg, "connect", lambda url: Connection())
    assert cli.doctor(Settings(supabase_db_url="postgresql://localhost/test")) == expected
    query = next(sql for sql in queries if "bool_and" in sql)
    assert "relrowsecurity" in query and "has_table_privilege" in query
    assert "a.grantee = 0" in query


@pytest.mark.parametrize("command", [["subscription", "suppress"], ["reconcile"]])
def test_emergency_commands_use_real_filtered_loading(monkeypatch, command):
    from test_config import clear_settings_env

    clear_settings_env(monkeypatch)
    for name in ("SMS_SEND_ENABLED", "RECIPIENT_CONSENT_CONFIRMED", "APP_TIMEZONE", "EMBEDDING_DIMENSIONS"):
        monkeypatch.setenv(name, "invalid")
    for name in ("SUPABASE_DB_URL", "TWILIO_ACCOUNT_SID", "TWILIO_API_KEY_SID", "TWILIO_API_KEY_SECRET"):
        monkeypatch.setenv(name, "test-value")
    calls = []
    db = SimpleNamespace(
        set_subscription_suppressed=lambda value: calls.append(value),
        reconciliation_candidates=lambda: [], close=lambda: calls.append("close"))
    monkeypatch.setattr(cli.Database, "connect", lambda settings: db)
    monkeypatch.setattr(cli, "make_twilio_client", lambda settings: object())
    assert cli.main(command) == 0
    assert calls == ([True, "close"] if command[0] == "subscription" else ["close"])


@pytest.mark.parametrize("enabled,consent,expected", [
    ("false", "true", 0), ("true", "true", 1), ("false", "false", 1),
    ("invalid", "true", 1), ("false", "invalid", 1),
])
def test_renewal_real_loading_preserves_safety_prerequisites(monkeypatch, enabled, consent, expected):
    from test_config import clear_settings_env

    clear_settings_env(monkeypatch)
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://localhost/test")
    monkeypatch.setenv("SMS_SEND_ENABLED", enabled)
    monkeypatch.setenv("RECIPIENT_CONSENT_CONFIRMED", consent)
    monkeypatch.setenv("APP_TIMEZONE", "invalid")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "invalid")
    calls = []
    monkeypatch.setattr(cli.Database, "connect", lambda settings: SimpleNamespace(
        set_subscription_suppressed=lambda value: calls.append(value), close=lambda: None))
    assert cli.main(["subscription", "renew", "--confirm-renewed-consent"]) == expected
    assert calls == ([False] if expected == 0 else [])
