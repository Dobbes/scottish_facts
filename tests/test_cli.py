from types import SimpleNamespace

import scotland_facts.cli as cli
from scotland_facts.config import Settings


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
