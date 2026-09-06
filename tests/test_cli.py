from types import SimpleNamespace

import scotland_facts.cli as cli
from scotland_facts.config import Settings


def test_live_doctor_uses_valid_minimal_openai_request_and_never_sends(monkeypatch):
    captured = {}

    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="OK")

    class Accounts:
        def __call__(self, sid):
            return self

        def fetch(self):
            return SimpleNamespace(sid="ACtest")

    monkeypatch.setattr(
        cli, "OpenAI", lambda **kwargs: SimpleNamespace(responses=Responses())
    )
    monkeypatch.setattr(
        cli,
        "make_twilio_client",
        lambda settings: SimpleNamespace(api=SimpleNamespace(accounts=Accounts())),
    )
    settings = Settings(
        openai_api_key="test",
        twilio_account_sid="ACtest",
        twilio_api_key_sid="SKtest",
        twilio_api_key_secret="test",
    )
    assert cli.doctor(settings, live=True) == 0
    assert captured["max_output_tokens"] == 16
    assert captured["store"] is False
