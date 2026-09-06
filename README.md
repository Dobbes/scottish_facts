# Scotland Facts

[Privacy Policy](#privacy-policy) | [Terms and Conditions](#terms-and-conditions)

Scotland Facts is a scheduled Python job that researches one real Scotland fact on the web, rejects repetitive material, adds a short Cat-Facts-style suffix, and sends the result to one consenting recipient through Twilio. Supabase PostgreSQL stores the audit trail, source citations, embeddings, attempts, and delivery state.

```text
SCOTLAND FACTS: Scotland's national animal is the unicorn. Your compulsory Scottish education will continue tomorrow.
```

The complete message is one line, contains no URL or emoji, and is at most 300 Unicode characters.

## Privacy Policy

Effective September 6, 2026.

Scotland Facts is a private, invitation-only informational messaging program. It collects a recipient's mobile phone number only after that person directly agrees to receive the messages. The number is used solely to deliver Scotland Facts messages, provide messaging support, honor opt-out requests, prevent duplicate sends, and diagnose delivery problems.

Phone numbers are kept in restricted configuration secrets and are not stored in the Scotland Facts database or sent to OpenAI. Twilio and participating telecommunications carriers process phone numbers and message-delivery metadata only as needed to provide the messaging service. Scotland Facts does not sell, rent, or share mobile information with third parties or affiliates for marketing or promotional purposes. Opt-in data and consent are not shared with third parties except service providers required to operate the messaging program.

A phone number is retained in the program configuration only while its owner remains subscribed. Reply **STOP** to opt out. The number will then be removed from the recipient configuration. Reply **HELP** for help, or open a support request at [GitHub Issues](https://github.com/Dobbes/scottish_facts/issues). Twilio's handling and retention of service data is governed by Twilio's own privacy policy.

## Terms and Conditions

Effective September 6, 2026.

The Scotland Facts messaging program sends source-backed facts about Scotland with a short humorous suffix. Participation is invitation-only. Each recipient must directly provide affirmative consent before their number is configured. Consent is not a condition of any purchase.

By opting in, a recipient agrees to receive automated SMS messages from Scotland Facts. Message frequency is up to one message per day. Message and data rates may apply. Delivery is subject to carrier availability and is not guaranteed.

Reply **STOP** at any time to unsubscribe. After opting out, no further Scotland Facts messages will be sent unless the recipient later provides renewed consent and follows the carrier's opt-in process. Reply **HELP** for help, or open a support request at [GitHub Issues](https://github.com/Dobbes/scottish_facts/issues).

Scotland Facts is provided for informational and entertainment purposes. Although the application uses cited web research and automated validation, it does not guarantee that every message is complete or error-free. The program may be changed, suspended, or discontinued at any time.

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

There is no web server, frontend, inbound webhook, second database, or background worker.

## Integrity Controls

The research model returns only a factual sentence, requested category, and canonical subjects. Source URLs are never trusted from model-authored JSON; they are extracted from OpenAI `url_citation` annotations and `web_search_call` source metadata. The prompt treats web pages as untrusted evidence and explicitly ignores instructions embedded in pages.

The style model returns only a suffix. Application code constructs `SCOTLAND FACTS: {fact} {suffix}`, so the style stage cannot rewrite the accepted fact. Mechanical checks reject excess length, line breaks, URLs, emoji, and fake instructions using real carrier keywords such as `Reply STOP` or `Reply HELP`.

Three independent repetition controls are used:

- Exact duplicate detection normalizes Unicode, case, punctuation, quotes, dashes, and whitespace.
- Semantic duplicate detection embeds only the fact and compares it to delivery-history facts with pgvector cosine similarity. The default rejection threshold is `0.88`.
- Subject fatigue rejects an exact normalized subject used by an already or possibly submitted fact during the previous 14 days.

`DRY_RUN` and `FAILED` facts do not affect category ordering, duplicate history, or subject fatigue. Categories are selected deterministically, with never-used categories first and otherwise least-recently-used first.

## At-Most-Once Sending

The daily Eastern date creates a unique database run key such as `daily:2026-09-06`. A duplicate key is always a successful no-op, including when the earlier run failed. Dry runs use unique `dryrun:` keys.

After the complete SMS is validated, the fact is committed as `PENDING`. Immediately before Twilio message creation, it is changed to `SEND_ATTEMPTED` and that transaction is committed. Only then does the application make one `messages.create` call. It never automatically retries message creation.

This deliberately favors a missed message over a duplicate. If a timeout occurs after Twilio may have accepted the request, the fact remains `SEND_ATTEMPTED`, the run fails with `TWILIO_AMBIGUOUS_SEND`, and the same daily key prevents another attempt. A successful SID is stored as `SUBMITTED`; delivery is polled briefly and recent `SUBMITTED`/`SENT` messages are reconciled once on later daily runs.

## Database

`migrations/001_initial.sql` enables pgvector and creates:

- `generation_runs`: unique run keys, lifecycle, model names, attempt count, and safe failure diagnostics.
- `facts`: fact and SMS text, source metadata, subjects, a 1536-dimensional vector, send boundary timestamps, SID, and delivery state.
- `generation_attempts`: every returned research candidate and its acceptance or ordered rejection diagnostics.
- `schema_migrations`: migration versions applied in lexical order.

Operational, GIN, partial unique, and HNSW cosine indexes support the safety queries. The HNSW index is not required for correctness at small row counts.

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

`requirements.lock` records the exact environment used for repository validation. Normal installation uses the compatible ranges in `pyproject.toml`; a reproduction can install the lock first and then install this package without resolving dependencies.

```bash
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

## GitHub Actions

`.github/workflows/daily-fact.yml` installs Python 3.12, installs the package and dev dependencies, runs all tests, runs non-live doctor checks, and then chooses one path:

- Scheduled events run production at `10:15 AM America/New_York`.
- Manual events default `dry_run` to `true`.
- A manual event sends only when its operator explicitly sets `dry_run` to `false`.

The workflow has read-only repository permissions and `scotland-facts-send` concurrency with no in-progress cancellation. Database run-key uniqueness remains authoritative.

Add all provider values as GitHub Actions secrets. Do not place them in repository variables, workflow command arguments, logs, or files. See [USER_SETUP.md](USER_SETUP.md) for the account-owner deployment procedure.

## Security

- `.env` is ignored and `.env.example` contains empty values only.
- Pydantic `SecretStr` masks secrets in object representations.
- Logs redact PostgreSQL passwords and phone-like values; they never intentionally log recipient or sender numbers.
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
