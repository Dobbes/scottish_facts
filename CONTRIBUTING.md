# Contributing

## Set up

Use Python 3.12 and a virtual environment:

```bash
python -m venv .venv
# Activate the environment, then:
python -m pip install -e ".[dev]"
python -m pytest
```

Unit and contract tests need no provider credentials. PostgreSQL integration tests
are skipped unless `SCOTLAND_FACTS_TEST_DB_URL` explicitly points to a migrated test
database. Those tests create and remove their own isolated schema.

## Make a change

Keep changes focused and add tests for meaningful behavior changes. In particular,
preserve the daily run key, commit-before-create send boundary, source provenance,
unchanged factual text, and fixed STOP footer. Read the
[architecture guide](guides/architecture.md) before changing orchestration or delivery.

```bash
python -m pytest
python -m compileall -q src tests scripts
python scripts/audit_secrets.py --history
git diff --check
```

Review audit findings; the redaction tests deliberately contain synthetic
credentials. The scanner does not print matched values.

## Submit

Describe the behavior change, how it was verified, and any migration or deployment
steps. Stage only intended files. Keep `.env`, phone numbers, private consent
records, provider logs, and local recovery notes out of commits and issues.

CI runs tests without deployment secrets on pushes and pull requests. The daily
delivery workflow is separate and defaults manual runs to dry-run mode.

Report security issues privately as described in [SECURITY.md](SECURITY.md).
