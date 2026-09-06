from pathlib import Path


def test_workflow_contract():
    workflow = Path(".github/workflows/daily-fact.yml").read_text(encoding="utf-8")
    assert "cron: '15 10 * * *'" in workflow
    assert "timezone: 'America/New_York'" in workflow
    assert "workflow_dispatch:" in workflow
    assert "default: true" in workflow
    assert "group: scotland-facts-send" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "pytest" in workflow
    assert "run --dry-run" in workflow
    assert "run: python -m scotland_facts.cli run" in workflow
    assert "python-version: '3.12'" in workflow


def test_workflow_has_read_only_permissions_and_all_secrets():
    workflow = Path(".github/workflows/daily-fact.yml").read_text(encoding="utf-8")
    assert "contents: read" in workflow
    for name in (
        "OPENAI_API_KEY",
        "SUPABASE_DB_URL",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_API_KEY_SID",
        "TWILIO_API_KEY_SECRET",
        "TWILIO_FROM_NUMBER",
        "RECIPIENT_NUMBER",
    ):
        assert f"secrets.{name}" in workflow
