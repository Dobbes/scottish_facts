# Architecture and Operations

[Project overview](../README.md) | [Deployment guide](USER_SETUP.md) | [Campaign guide](RESUBMISSION.md)

Scotland Facts is operated by Elumsden Sole. Support: [brunslx@gmail.com](mailto:brunslx@gmail.com).

The public site is served from `docs/` at [dobbes.github.io/scottish_facts](https://dobbes.github.io/scottish_facts/). The home, privacy, terms, and enrollment pages were verified publicly accessible on September 9, 2026. See the [campaign guide](RESUBMISSION.md) for provider configuration.

Scotland Facts is a scheduled Python job that researches one real Scotland fact on the web, rejects repetitive material, adds a short Cat-Facts-style suffix, and sends the result to one consenting recipient through Twilio. Supabase PostgreSQL stores the audit trail, source citations, embeddings, attempts, and delivery state.

```text
SCOTLAND FACTS: Scotland's national animal is the unicorn. The unicorns have declined to comment. Reply STOP to opt out.
```

The complete message is one line, contains no URL or emoji, and is at most 300 Unicode characters.

## Privacy Policy

The complete [Privacy Policy](../docs/privacy/index.html) describes private consent records, restricted recipient configuration, manual removal and suppression, retained operational/provider data, and no marketing sharing of mobile information or consent (with a necessary service-provider exception). No automatic data deletion or inbound webhook is claimed.

## Terms and Conditions

The complete [Terms and Conditions](../docs/terms/index.html) cover voluntary automated SMS enrollment, up to one daily fact plus separate enrollment/requested service replies, rates, STOP, HELP, carrier limitations, and manual consent renewal. Support is [brunslx@gmail.com](mailto:brunslx@gmail.com); do not post personal information in public repository issues. The [verbal disclosure](../docs/enrollment/index.html) is not an online signup form. Enrollment confirmation is not implemented in the CLI; the guarded manual provider procedure is in [RESUBMISSION.md](RESUBMISSION.md).

## Architecture

```text
GitHub Actions (10:15 America/New_York)
                 |
                 v
          Python orchestrator
          /               \
         v                 v
OpenAI Responses API   Supabase PostgreSQL
web_search + JSON      runs, attempts, facts
citations + embedding  pgvector similarity
         \                 /
          v               v
         ordered candidate validation
                   |
                   v
          suffix-only style call
                   |
                   v
      persist PENDING -> commit SEND_ATTEMPTED
                   |
                   v
          exactly one Twilio create call
                   |
                   v
       short status poll + later reconciliation
```

There is no application web server, inbound webhook, second database, or background worker. The separate dependency-free `docs/` information site is suitable for GitHub Pages and does not collect enrollment data.

## Integrity Controls

The research model returns only a factual sentence, requested category, and canonical subjects. Source URLs are never trusted from model-authored JSON; they are extracted from OpenAI `url_citation` annotations and `web_search_call` source metadata. The prompt treats web pages as untrusted evidence and explicitly ignores instructions embedded in pages.

The style model selects one exact reviewed humorous suffix from `SAFE_SUFFIXES`. Application code constructs `SCOTLAND FACTS: {fact} {suffix} Reply STOP to opt out.`, so the style stage cannot rewrite the accepted fact or the fixed compliance footer. All unlisted suffixes are rejected, including fake nonsense reply commands, Unicode disguises, and alternate opt-out phrasing. The style request reserves the footer's character budget; the complete message is validated against the configured limit and a hard 300-character cap. All reviewed suffixes fit a default 180-character fact with the footer. Generated content is checked for control commands separately before the application appends the genuine instruction. HELP and other service responses remain provider-configured, not generated jokes.

Three independent repetition controls are used:

- Exact duplicate detection normalizes Unicode, case, punctuation, quotes, dashes, and whitespace.
- Semantic duplicate detection embeds only the fact and compares it to all persisted facts with pgvector cosine similarity. The default rejection threshold is `0.88`.
- Subject fatigue rejects an exact normalized subject used by any persisted fact during the previous 14 days.

All persisted facts, including `DRY_RUN`, `PENDING`, `FAILED`, and every delivery status, count toward global exact/semantic novelty, recent 14-day subjects, category ordering, prior research context, and recent SMS context. Rejected attempts do not count. Categories are selected deterministically, with never-used categories first and otherwise least-recently-used first.

In every mode, final novelty revalidation and fact insertion are atomic under a shared PostgreSQL transaction advisory lock in a short transaction. The final semantic check uses an exact cosine scan, not approximate HNSW results. A concurrent collision rejects the candidate and retries research within the existing attempt limit; external API calls stay outside the lock.

## At-Most-Once Sending

The daily Eastern date creates a unique database run key such as `daily:2026-09-06`. A duplicate key is always a successful no-op, including when the earlier run failed. Dry runs use unique `dryrun:` keys. A persisted preview consumes content novelty but never claims a production daily key or populates delivery fields.

After the complete SMS is validated, the fact is committed as `PENDING`. Immediately before Twilio message creation, it is changed to `SEND_ATTEMPTED` and that transaction is committed. Only then does the application make one `messages.create` call. It never automatically retries message creation.

This deliberately favors a missed message over a duplicate. If a timeout occurs after Twilio may have accepted the request, the fact remains `SEND_ATTEMPTED`, the run fails with `TWILIO_AMBIGUOUS_SEND`, and the same daily key prevents another attempt. Initial Twilio status and error code are persisted with the SID, including terminal failure or delivery. Polling does not discard known state when disabled or when fetching fails. Twilio HTTP requests have a configurable 15-second timeout and zero transport retries; the Actions job has a 15-minute timeout.

`SMS_SEND_ENABLED` and `RECIPIENT_CONSENT_CONFIRMED` both default to `false`. CLI, workflow, and the send boundary require both for production; dry runs are unaffected. A phone-free singleton subscription record blocks generation and sending after manual suppression or observed Twilio error `21610`. Configuration changes and carrier opt-in never automatically clear database suppression. See the explicit renewal procedure in [USER_SETUP.md](USER_SETUP.md).

`python -m scotland_facts.cli reconcile` only fetches unresolved delivery states, even while sending is disabled and without OpenAI or phone configuration. No seven-day cutoff is applied. Exit 1 means a late failure, lookup/fetch error, or unresolved/ambiguous delivery needs attention; exit 0 means all candidates were resolved without new failures (including no candidates). Failures are persisted on facts and logged, not retroactively hidden by changing the original run outcome. Production preflight blocks on failures, lookup/fetch errors, opt-outs, or SID-less ambiguity, but not on successfully fetched known-SID queued/sent messages awaiting delivery receipts. Those messages retain their truthful status and remain eligible for reconciliation. No resend is performed. SID-less ambiguous sends require manual Twilio inspection; never reset their send boundary or daily key to retry.

## Database

`migrations/001_initial.sql` enables pgvector and creates:

- `generation_runs`: unique run keys, lifecycle, model names, attempt count, and safe failure diagnostics.
- `facts`: fact and SMS text, source metadata, subjects, a 1536-dimensional vector, send boundary timestamps, SID, and delivery state.
- `generation_attempts`: every returned research candidate and its acceptance or ordered rejection diagnostics.
- `schema_migrations`: migration versions applied in lexical order.

Operational, GIN, partial unique, and HNSW cosine indexes remain in place, but final novelty enforcement uses the locked exact checks rather than approximate HNSW search or the status-scoped unique index alone. Existing duplicate audit rows are retained; this novelty policy requires no migration.

Apply incremental `002_subscription_and_api_security.sql` to existing installations. It adds `subscription_state`, enables RLS on all five server-only tables including `schema_migrations`, and revokes public and existing `anon`, `authenticated`, and `service_role` API privileges. Absent Supabase roles are skipped for generic PostgreSQL. Use the trusted table-owner PostgreSQL login for migrations and runtime; do not use API roles. RLS is not forced, so owner access is retained. `doctor` validates RLS, API role privileges, and runtime ownership. These checks must still be run against the deployment; local tests do not prove deployed security.

## Local Setup

Python 3.12 is the production version.

```bash
python -m venv .venv
# Activate the environment, then:
python -m pip install -e ".[dev]"
```

Copy `.env.example` to an ignored `.env` and supply only the credentials needed for the command. The application calls `load_dotenv()` before central configuration parsing; application modules do not read ad-hoc environment variables.

Apply migrations twice to verify idempotency:

```bash
python -m scotland_facts.cli migrate
python -m scotland_facts.cli migrate
```

Run non-costing checks and a real web-grounded dry run:

```bash
python -m scotland_facts.cli doctor
python -m scotland_facts.cli doctor --live
python -m scotland_facts.cli run --dry-run
```

`doctor` never sends an SMS. Its default mode performs no OpenAI or Twilio API call. `doctor --live` makes a minimal non-web OpenAI request and fetches Twilio account-compatible data without creating a message.

Other commands:

```bash
python -m scotland_facts.cli run
python -m scotland_facts.cli calibrate
python -m scotland_facts.cli history --limit 10
```

The production `run` command can send a real SMS. Use it only after consent, carrier registration, a successful dry run, and explicit confirmation of the recipient and sender values.

## Tests

```bash
pytest
python -m compileall -q src tests scripts
```

Tests use fake OpenAI, database, and Twilio boundaries and never send an SMS. Coverage includes source extraction, validation order, semantic duplicates, subject fatigue, run concurrency, suffix safety, status mapping, and commit-before-create behavior.

Optional PostgreSQL tests run with `pytest tests/test_db_integration.py` when `SCOTLAND_FACTS_TEST_DB_URL` is explicitly set to a migrated test database. They clone table definitions into a uniquely named private schema, exercise real concurrent acceptance and rollback, and remove only that schema afterward. They never call OpenAI or Twilio or modify existing public fact records. Without that variable, these tests are skipped.

`requirements.lock` records the exact environment used for repository validation. Both CI and daily delivery install this lock, then install the package without resolving dependencies. Normal local installation uses the compatible ranges in `pyproject.toml`; reproduce the hosted environment with:

```bash
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

## GitHub Actions

`.github/workflows/daily-fact.yml` installs Python 3.12, installs the package and dev dependencies, runs all tests, runs non-live doctor checks, and then chooses one path:

- Scheduled events run production at `10:15 AM America/New_York` only when both authorization/consent variables are `true`.
- Manual events default `dry_run` to `true`.
- A manual event sends only when its operator explicitly sets `dry_run` to `false` and both gates are `true`.

The workflow has read-only repository permissions and `scotland-facts-send` concurrency with no in-progress cancellation. Database run-key uniqueness remains authoritative.

Paused scheduled delivery adds an explicit warning and run summary. A manual production request with either switch off fails clearly rather than silently skipping the send. Credential-free `.github/workflows/ci.yml` runs tests on pushes and pull requests independently of daily delivery.

Add all provider values as GitHub Actions secrets. Only the non-secret `SMS_SEND_ENABLED` and `RECIPIENT_CONSENT_CONFIRMED` switches use repository variables, defaulting off. Never place provider values in repository variables, workflow command arguments, logs, or files. See [USER_SETUP.md](USER_SETUP.md) for the account-owner deployment procedure.

## Security

- `.env` is ignored and `.env.example` contains empty values only.
- Pydantic `SecretStr` masks secrets in object representations.
- Logs and traceback formatting redact configured secrets, their URL-encoded forms, PostgreSQL passwords, and phone-like values. Provider debug logging is disabled even with `--verbose`; redaction remains defense in depth, not a guarantee for arbitrary transformed secrets.
- Recipient data is used only at the Twilio boundary and is never persisted or sent to OpenAI.
- OpenAI storage is disabled for research and style calls.
- Twilio uses an API key SID and secret scoped to the account, not the main Auth Token.
- The public repository must be scanned for accidental credentials and phone numbers before each push.

## Known Limitations

- GitHub scheduled jobs can start later than the requested time; this is not a real-time SLA.
- GitHub may disable scheduled workflows in an inactive public repository after 60 days. Re-enable it in Actions after inactivity.
- V1 has no inbound command or reply handling.
- Without a status callback webhook, delivery state is polled briefly and reconciled on a later run rather than pushed instantly.
- Embedding similarity is heuristic. Use `calibrate` and production observations before adjusting the threshold.
- A network failure at the Twilio ambiguity boundary can intentionally lose one day's message to prevent duplicates.

## Portfolio Summary

This project demonstrates a fail-closed AI content pipeline: web-grounded structured research, extraction of real tool citation metadata, deterministic validation, PostgreSQL state and row-safe idempotency, pgvector semantic search, short-window subject fatigue, factual/style separation, at-most-once external side effects, delivery reconciliation, and a timezone-aware CI schedule.
