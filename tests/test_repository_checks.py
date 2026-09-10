"""Verify public-repository tooling without credentials or network access."""

from pathlib import Path
import re
import runpy
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_markdown_local_links_resolve_after_documentation_moves():
    documents = list(ROOT.glob("*.md")) + list((ROOT / "guides").glob("*.md"))
    documents = [path for path in documents if path.name != "RESUME.md"]
    for document in documents:
        for href in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", document.read_text(encoding="utf-8")):
            if ":" in href or href.startswith("#"):
                continue
            assert (document.parent / href.split("#", 1)[0]).exists(), (document.name, href)


def test_secret_scanner_reports_locations_without_values(capsys):
    audit = runpy.run_path(str(ROOT / "scripts/audit_secrets.py"))
    secret = b"runtime-generated-sensitive-value"
    data = b"example\n" + secret + b"\n" + b"-----BEGIN " + b"PRIVATE KEY-----"
    assert audit["scan"](data, "fixture.txt", {secret}) == 2
    output = capsys.readouterr().out
    assert secret.decode() not in output
    assert "fixture.txt:2: local-secret-value" in output
    assert "fixture.txt:3: private-key" in output


def test_public_ci_has_no_deployment_secrets():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"push", "pull_request"}
    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets." not in text
    assert "scotland_facts.cli run" not in text


def test_disabled_production_is_visible_and_manual_request_fails(tmp_path):
    workflow = yaml.load(
        (ROOT / ".github/workflows/daily-fact.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    step = next(step for step in workflow["jobs"]["daily-fact"]["steps"]
                if step["name"] == "Explain disabled production delivery")
    for event, exit_code in (("schedule", 0), ("workflow_dispatch", 1)):
        summary = tmp_path / f"{event}.md"
        result = subprocess.run(
            [sys.executable, "-c", step["run"]],
            env={"GITHUB_EVENT_NAME": event, "GITHUB_STEP_SUMMARY": str(summary)},
            capture_output=True, text=True,
        )
        assert result.returncode == exit_code
        assert "::warning::SMS delivery is paused" in result.stdout
        assert "No SMS will be sent" in summary.read_text()
