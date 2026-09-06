# Scotland Facts — Specification Audit

## Result

The original specification had the correct overall architecture but was not strict enough for a reliable one-shot coding-agent implementation.

The revised `CLI_SPEC.md` removes the major unresolved implementation decisions.

## Major issues found and resolved

1. **Style generation could change the fact**
   - Original design asked the style model to rewrite the entire SMS.
   - Revised design generates only a joke suffix.
   - Application code preserves the researched factual sentence verbatim.

2. **Twilio fake STOP joke could cause a real opt-out**
   - Twilio recognizes real control words such as STOP, UNSUBSCRIBE, CANCEL, HELP, etc.
   - Revised spec mechanically rejects fake instructions that use those commands.
   - Harmless fake words such as HAGGIS are allowed.

3. **At-most-once SMS behavior was underspecified**
   - A crash after Twilio accepts the message but before DB update can create duplicate-send risk.
   - Revised design commits `SEND_ATTEMPTED` before the Twilio call.
   - Twilio create is never automatically retried.
   - Same daily run key never sends twice.

4. **GitHub Actions schedule was left conditional**
   - Current GitHub Actions supports IANA timezones.
   - Revised spec requires:
     `cron: '15 10 * * *'`
     plus `timezone: 'America/New_York'`.

5. **Embedding implementation was ambiguous**
   - Revised spec fixes:
     - `text-embedding-3-small`
     - 1536 dimensions
     - cosine distance `<=>`
     - similarity = `1 - distance`
     - threshold 0.88
     - HNSW cosine index.

6. **Subject fatigue behavior was subjective**
   - Revised spec defines exact canonical subject tags.
   - Any exact normalized subject reused within 14 days is rejected.

7. **Category selection was not deterministic**
   - Revised spec makes application code select the least-recently-used category.
   - The LLM does not choose the category.

8. **Source handling trusted model output too much**
   - Revised spec removes source URLs from generated JSON.
   - The application extracts actual OpenAI `url_citation` annotations.

9. **Database access path was unspecified**
   - Revised spec uses direct PostgreSQL via `psycopg` rather than leaving Supabase-client/direct-SQL choice open.

10. **Migration ownership was incomplete**
    - Revised spec requires a `migrate` CLI command plus `schema_migrations`.

11. **Twilio credential strategy was weak**
    - Revised spec uses Twilio API keys for deployed production code rather than the main Auth Token.

12. **Twilio "sent" vs "delivered" was conflated**
    - Revised spec stores Twilio status and briefly polls the Message resource.
    - Later daily runs reconcile recent messages.

13. **Retry policy could produce duplicate SMS**
    - Revised spec allows retries for OpenAI/database reads.
    - Twilio message creation has no automatic retry.

14. **Dry-run behavior could contaminate production history**
    - Revised spec gives dry runs unique keys and excludes them from dedupe/fatigue/category history.

15. **No explicit prompt-injection handling**
    - Revised research prompt treats web content as untrusted evidence and ignores page instructions.

16. **The coding agent could stop after scaffolding**
    - Revised spec explicitly requires install, tests, fixes, doctor checks, migrations/dry-run when credentials are available, and accurate validation-state reporting.

## Accepted limitation

The repository remains public.

GitHub can disable scheduled workflows in a public repository after 60 days without repository activity. The owner explicitly accepted this behavior, so the specification documents it rather than redesigning the hosting architecture.

## One-shot readiness

With the revised specification, the remaining steps that cannot be completed autonomously are account-owner actions:

- creating external service accounts/projects,
- supplying API/database credentials,
- completing Twilio/carrier registration,
- adding GitHub Secrets,
- authorizing/performing the first real production SMS test.

No additional software architecture decisions should be required.
