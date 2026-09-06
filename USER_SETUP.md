# Scotland Facts Owner Setup

This is the current owner checklist for moving the completed code from local validation to production. Complete it in order. Do not place any credential or phone number in this repository, an issue, a commit message, or chat output.

## Current Status

Already complete:

- Application, migration, CLI, tests, workflow, and documentation are implemented.
- Clean Python 3.12 installation succeeds.
- All local tests and static checks pass.
- Live OpenAI web research, citations, embeddings, and style generation have been validated.
- The public GitHub repository is populated and local `main` tracks `origin/main`.
- Supabase is configured, the migration is repeatable, and persisted dry-runs succeed.
- `DATABASE VALIDATED` has been achieved.
- Twilio API-key authentication and ownership of the configured sender are validated.
- `EXTERNAL INTEGRATIONS VALIDATED` has been achieved.
- No real SMS has been sent.

Still required from the owner:

- Complete current carrier registration for the Twilio sender.
- Confirm recipient consent.
- Store credentials in local `.env` and GitHub Actions secrets.
- Authorize the first production SMS explicitly after dry-run validation.

## 1. Verify The GitHub Repository

The public repository is already created and populated:

```text
https://github.com/Dobbes/scottish_facts
```

The local `main` branch tracks `origin/main`. Verify it when needed with:

```bash
git status --short --branch
git remote -v
```

Credentials and local environment files are not tracked. Continue to audit every future staged change before pushing.

## 2. Confirm The OpenAI Project

OpenAI integration was validated during implementation, and the following live paths have passed:

- Responses API
- required web search
- structured JSON output
- URL citation/source extraction
- 1536-dimensional embeddings
- suffix-only style generation

Confirm the OpenAI project has billing and usage limits appropriate for daily operation. Preserve the key securely. You will later add it to GitHub as:

```text
OPENAI_API_KEY
```

Do not paste the key into any tracked file.

## 3. Create The Supabase Project

Create one Supabase project for Scotland Facts.

In the Supabase dashboard, obtain a server-side PostgreSQL connection URI. Prefer the connection string Supabase currently recommends for external persistent Python processes, with TLS/SSL enabled. A direct or session-pooler connection may be needed for initial extension/DDL operations if the transaction pooler rejects `CREATE EXTENSION`.

The value becomes:

```text
SUPABASE_DB_URL
```

The URI contains a database password. Never put it in source code, documentation, command-line arguments, screenshots, or GitHub repository variables.

## 4. Create A Local `.env`

Create an ignored `.env` based on `.env.example`. Add only the real values you currently have:

```dotenv
OPENAI_API_KEY=your-real-value
SUPABASE_DB_URL=your-real-value
```

Leave Twilio fields empty until those credentials exist. `.env` and `.env.*` are ignored, while `.env.example` remains tracked with empty placeholders.

Confirm `.env` is ignored before continuing:

```bash
git check-ignore -v .env
git status --short
```

The first command must identify `.gitignore`. The second command must not list `.env`.

## 5. Apply And Verify The Database Migration

On this Windows machine, use the validated Python 3.12 virtual environment:

```powershell
& ".venv\Scripts\python.exe" -m scotland_facts.cli migrate
& ".venv\Scripts\python.exe" -m scotland_facts.cli migrate
```

The first command should apply `001_initial.sql`. The second must report:

```text
No unapplied migrations
```

Then run:

```powershell
& ".venv\Scripts\python.exe" -m scotland_facts.cli doctor
```

Doctor should report a successful database connection and migration structure.

In Supabase, verify:

- `schema_migrations` contains `001_initial.sql` once.
- `generation_runs`, `facts`, and `generation_attempts` exist.
- The `vector` extension exists in the `extensions` schema.
- `facts.embedding` is `extensions.vector(1536)`.
- The facts table has the HNSW cosine, GIN subjects, status, category, date, and partial normalized-fact indexes.
- No recipient phone number column or value exists.

If migration fails through a transaction-mode pooler, use the direct or session-pooler PostgreSQL URI recommended by the current Supabase dashboard for the migration. After migration, the application can use the server-side pooler URI recommended for normal jobs.

## 6. Run The First Persisted Dry Run

Run:

```powershell
& ".venv\Scripts\python.exe" -m pytest
& ".venv\Scripts\python.exe" -m scotland_facts.cli run --dry-run
```

The dry run performs real OpenAI web research but never initializes or calls Twilio message creation.

Expected terminal output includes:

- final `SCOTLAND FACTS:` message,
- primary source URL,
- dry-run key,
- attempt count,
- successful status.

In Supabase, inspect the new rows:

- `generation_runs.run_type` is `DRY_RUN`.
- `generation_runs.status` is `SUCCEEDED`.
- `generation_attempts` contains each candidate and any rejection diagnostics.
- `facts.status` is `DRY_RUN`.
- `fact_text` appears unchanged immediately after `SCOTLAND FACTS:` in `sms_text`.
- `source_url`, `source_title`, and `sources` contain real extracted web metadata.
- `embedding` has 1536 dimensions.
- The final SMS is one line and no longer than 300 characters.

Dry-run facts intentionally do not influence production duplicate checks, category recency, or subject fatigue.

After this succeeds, tell the implementation operator that Supabase and the persisted dry-run are ready. This is the point where `DATABASE VALIDATED` can be recorded.

## 7. Create The Twilio Sender

Create or use a Twilio account and obtain an SMS-capable sender for the recipient's country and carrier.

Record these values securely:

```text
TWILIO_ACCOUNT_SID
TWILIO_FROM_NUMBER
```

Use the actual sender format required by Twilio. For a phone-number sender and recipient, use E.164 formatting. A non-sensitive shape is:

```text
+1XXXXXXXXXX
```

## 8. Create A Twilio API Key

Create a Twilio API key authorized for Programmable Messaging. Save both values when the secret is shown:

```text
TWILIO_API_KEY_SID
TWILIO_API_KEY_SECRET
```

The application intentionally uses the API key SID and secret scoped to `TWILIO_ACCOUNT_SID`. Do not substitute the account's main Auth Token as the normal deployed credential.

## 9. Complete Current Carrier Registration

Follow the current Twilio Console instructions for the sender type, destination country, and use case. United States messaging may require A2P 10DLC registration, toll-free verification, or another current carrier process.

Describe the use case truthfully:

- personal or hobby automation,
- one known consenting recipient,
- one factual entertainment SMS each day,
- no purchased list or unsolicited marketing.

Do not attempt to bypass carrier registration, filtering, consent, or opt-out controls. Wait until Twilio shows the sender as ready before the controlled production test.

## 10. Confirm Recipient Consent

Confirm that the intended recipient:

- expects one Scotland Facts message each day,
- agrees to receive automated messages from the Twilio sender,
- understands normal messaging rates may apply,
- knows not to follow joke commands as if they were real carrier commands.

Store the recipient's E.164 number only as:

```text
RECIPIENT_NUMBER
```

Never store it in PostgreSQL, source code, documentation, screenshots, commits, issues, or logs.

## 11. Understand Twilio Control Keywords

The application mechanically rejects fake instructions that use real Twilio control keywords, including:

```text
STOP
STOPALL
UNSUBSCRIBE
CANCEL
END
REVOKE
OPTOUT
QUIT
START
UNSTOP
HELP
INFO
```

Do not encourage the recipient to send these words as part of the joke. A harmless generated command may say `Reply HAGGIS`, because it does not collide with a real control keyword.

If the recipient accidentally opts out, use the current opt-in mechanism shown in the Twilio Console and Twilio documentation. Do not add a custom bypass to this application.

## 12. Add Twilio Values Locally

Add the following real values to the ignored local `.env`:

```dotenv
TWILIO_ACCOUNT_SID=your-real-value
TWILIO_API_KEY_SID=your-real-value
TWILIO_API_KEY_SECRET=your-real-value
TWILIO_FROM_NUMBER=your-real-value
RECIPIENT_NUMBER=your-real-value
```

Run the non-sending live connectivity check:

```powershell
& ".venv\Scripts\python.exe" -m scotland_facts.cli doctor --live
```

This may incur a minimal OpenAI request. It validates Twilio account-compatible data but never creates an SMS.

After this succeeds, tell the implementation operator that Twilio connectivity is ready. This is the point where `EXTERNAL INTEGRATIONS VALIDATED` can be recorded.

## 13. Add GitHub Actions Secrets

In the GitHub repository, open:

```text
Settings -> Secrets and variables -> Actions
```

Create repository secrets with these exact names:

```text
OPENAI_API_KEY
SUPABASE_DB_URL
TWILIO_ACCOUNT_SID
TWILIO_API_KEY_SID
TWILIO_API_KEY_SECRET
TWILIO_FROM_NUMBER
RECIPIENT_NUMBER
```

Use GitHub Actions secrets, not repository variables. Do not add model defaults as secrets unless you intentionally want to override them.

## 14. Audit Future Repository Changes

Before every future commit, verify ignored and tracked content:

```bash
git status --short --ignored
git check-ignore -v .env .venv RESUME.md
git grep -n -I -E "(OPENAI_API_KEY|SUPABASE_DB_URL|TWILIO_API_KEY_SECRET|RECIPIENT_NUMBER)=" -- ':!*.example'
```

Review every match from the last command. There should be no assignment containing a real value. Workflow references such as `${{ secrets.OPENAI_API_KEY }}` are expected and safe.

Also inspect staged content before committing:

```bash
git add .
git diff --cached --stat
git diff --cached
```

Confirm none of these are staged:

- `.env` or `.env.*` other than `.env.example`,
- `.venv`, caches, or generated package metadata,
- `RESUME.md`,
- private key/certificate files,
- provider credentials,
- database URLs or passwords,
- sender or recipient phone numbers,
- screenshots containing account details.

Only then commit and push the intended update using your preferred Git workflow.

## 15. Run The GitHub Actions Dry Run

Open:

```text
Actions -> Daily Scotland Fact -> Run workflow
```

Leave:

```text
dry_run = true
```

Confirm:

- package installation succeeds,
- all tests pass,
- doctor passes,
- the dry run succeeds,
- Supabase contains new `DRY_RUN` records,
- no SMS arrives.

Manual workflow dispatch intentionally defaults to dry-run.

## 16. Authorize One Controlled Production Test

Do not run production merely because all credentials exist. A real SMS requires explicit owner authorization.

Before authorizing, confirm:

- the persisted dry run succeeded,
- Twilio/carrier registration is complete,
- sender and recipient values were checked directly in the provider consoles,
- recipient consent is current,
- no production run has already occurred on the current Eastern date.

Then explicitly authorize one production test. It can be run locally:

```powershell
& ".venv\Scripts\python.exe" -m scotland_facts.cli run
```

or through GitHub Actions with:

```text
dry_run = false
```

The production run key is `daily:YYYY-MM-DD` using `America/New_York`. Any second production invocation that day must no-op, even if the first run failed.

## 17. Confirm Production Delivery

After the controlled test, verify all three locations.

Recipient device:

- exactly one message arrived,
- the fact is intact and readable,
- the complete SMS is no longer than 300 characters.

Twilio Console:

- exactly one Message resource was created,
- SID and final carrier status are visible,
- no unexpected retry or duplicate exists.

Supabase:

- `send_attempted_at` is set,
- `twilio_sid` is stored after successful creation,
- `twilio_status` is stored,
- application status is `SUBMITTED`, `SENT`, or `DELIVERED` as appropriate,
- the run is `SUCCEEDED` if Twilio returned a SID and did not immediately report failure.

When actual delivery is confirmed, `PRODUCTION DELIVERY VERIFIED` can be recorded.

## 18. Verify Idempotency

After the controlled production test, invoke production once more on the same Eastern calendar date:

```powershell
& ".venv\Scripts\python.exe" -m scotland_facts.cli run
```

Expected behavior:

- exit code zero,
- concise no-op message,
- no OpenAI generation,
- no new Twilio Message resource,
- no second SMS.

This behavior also applies when the existing daily run failed. The application does not send late catch-up messages.

## 19. Normal Scheduled Operation

The workflow is scheduled for:

```text
10:15 AM America/New_York
```

GitHub's timezone-aware schedule follows Eastern daylight-saving changes. Scheduled workflows run from the default branch and may start later during GitHub service load; this is not a real-time SLA.

GitHub may disable scheduled workflows in a public repository after 60 days without repository activity. If delivery stops after inactivity, check the Actions tab and re-enable the workflow.

## 20. Pause Or Resume Delivery

To pause:

```text
Actions -> Daily Scotland Fact -> Disable workflow
```

To resume, return to the same workflow and select `Enable workflow`. Confirm that recipient consent and all provider credentials are still valid before enabling it.

## 21. Change The Recipient

Update only the `RECIPIENT_NUMBER` GitHub Actions secret and, if testing locally, the ignored `.env` value. Confirm the new recipient's consent before enabling delivery.

Do not edit source code or database rows with a phone number.

## 22. Operational Checks

Useful non-sending commands:

```powershell
& ".venv\Scripts\python.exe" -m scotland_facts.cli doctor
& ".venv\Scripts\python.exe" -m scotland_facts.cli doctor --live
& ".venv\Scripts\python.exe" -m scotland_facts.cli history --limit 10
& ".venv\Scripts\python.exe" -m scotland_facts.cli calibrate
```

`calibrate` incurs embedding API usage. `history` prints no phone data. Neither command sends SMS.

If a Twilio create call times out ambiguously, do not manually retry that day's run. The application deliberately leaves the fact as `SEND_ATTEMPTED` because Twilio may have accepted it. The next Eastern calendar day proceeds normally.

## What To Complete Next

The immediate owner actions are:

1. Confirm recipient consent and verify the recipient if the Twilio account remains in trial mode.
2. Complete current carrier registration for the Twilio sender.
3. Add `RECIPIENT_NUMBER` locally and add all seven GitHub Actions secrets.
4. Run the GitHub Actions dry run.
5. Explicitly authorize one controlled production SMS only when ready.
