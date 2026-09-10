# Security

## Report an issue privately

Email [brunslx@gmail.com](mailto:brunslx@gmail.com) with a description and affected
file or commit. Do not post credentials, phone numbers, or private consent records
in a public issue. Do not include a live secret in the report.

## Credential handling

- Store hosted provider credentials and phone numbers in GitHub Actions **secrets**.
- Use repository **variables** only for the two non-sensitive delivery switches.
- Local `.env` files, private-key files, virtual environments, and recovery notes
  are ignored by Git. `.env.example` contains placeholders only.
- Provider credentials are masked in settings representations and redacted from
  application logs. Recipient numbers are not stored in PostgreSQL or sent to OpenAI.
- Database tables are server-only: migrations enable row-level security and revoke
  API-role access. `doctor` checks deployed permissions and table ownership.

## Audit before publishing

```bash
python scripts/audit_secrets.py --history
git diff --cached --stat
git diff --cached
```

The read-only scanner checks tracked/unignored working files and, with `--history`,
all reachable Git blobs. It detects common provider tokens, private-key headers,
credential URLs, and international phone numbers. When a local `.env` exists, it
also checks sensitive values and common encodings without printing them.

Findings identify locations and rules. Test fixtures may be intentional matches.
This focused scan does not cover GitHub issues, Actions logs/artifacts, deleted
remote history, or unknown token formats; use GitHub's secret-scanning and push
protection features as an additional layer.

If a real credential is exposed, revoke or rotate it at the provider first. Removing
it from the latest file does not remove it from commit history or existing copies.
