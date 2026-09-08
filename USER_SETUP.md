# Scotland Facts Owner Setup

This is the current owner checklist for moving the completed code from local validation to production. Complete it in order. Do not place any credential or phone number in this repository, an issue, a commit message, or chat output.

## Current Status

For the rejected SMS campaign, start with [RESUBMISSION.md](RESUBMISSION.md). Scotland Facts is operated by Elumsden Sole, the exact registered identity confirmed by the owner on September 8, 2026. Public support: [brunslx@gmail.com](mailto:brunslx@gmail.com). The owner authorized commit, push, and GitHub Pages publication, not SMS sending, production enablement, or Twilio submission. Dedicated privacy, terms, and verbal-enrollment files exist under `docs/`; their intended Pages URLs are **not yet published or verified by this update**. GitHub CLI authentication currently blocks Pages configuration. Enrollment confirmation is **not implemented in the CLI**; adopt and verify the guarded manual provider procedure before claiming a confirmation flow.

The entries below describe prior project validation, not validation of this safety update. Migration `002`, deployed RLS/API permissions, current carrier approval, consent, inbound STOP/HELP behavior, and production delivery have NOT been checked by this update. Keep both delivery switches off until the updated checklist is complete.

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

The first command applies any missing migrations, including `002_subscription_and_api_security.sql` on an existing installation. The second must report:

```text
No unapplied migrations
```

Then run:

```powershell
& ".venv\Scripts\python.exe" -m scotland_facts.cli doctor
```

Doctor should report a successful database connection, migration structure, and server-only security. Use the trusted table-owner PostgreSQL login for both migration and runtime. RLS allows owner bypass but denies API clients; never use `anon`, `authenticated`, or `service_role` as this login.

In Supabase, verify:

- `schema_migrations` contains both `001_initial.sql` and `002_subscription_and_api_security.sql` once.
- `generation_runs`, `facts`, `generation_attempts`, and `subscription_state` exist.
- All five public tables have RLS enabled and no grants to PUBLIC or existing `anon`, `authenticated`, or `service_role` roles. Confirm actual REST/API access is denied using your deployment's API credentials, without exposing them in logs.
- The runtime owner can read/write these tables (verify via persisted dry run); no public-access RLS policies were added.
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
- understands real STOP opt-out and HELP support behavior, as configured in Twilio.

Use the complete [verbal enrollment disclosure](docs/enrollment/index.html), identifying Elumsden Sole as the operator of Scotland Facts and brunslx@gmail.com as support, after publishing its linked policies. Record dated affirmative consent privately outside this repository/database, including the sender, frequency, rates, STOP/HELP disclosure, policy/disclosure version, and affirmative response. Follow the separate confirmation procedure in [RESUBMISSION.md](RESUBMISSION.md). Set `RECIPIENT_CONSENT_CONFIRMED=true` only after consent evidence exists. This switch is an operator assertion, not automatic proof of consent. Leave `SMS_SEND_ENABLED=false` until explicit production authorization.

Store the recipient's E.164 number only as:

```text
RECIPIENT_NUMBER
```

Never store it in PostgreSQL, source code, documentation, screenshots, commits, issues, or logs.

## 11. Understand Twilio Control Keywords

Configure and verify Twilio's genuine opt-out and help handling for your sender/service before enabling delivery. Relevant provider keywords include:

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

No fake reply commands are allowed, including nonsense words such as HAGGIS. The model selects exact reviewed prose only. Each daily message now ends with fixed application-owned `Reply STOP to opt out.` text, separate from suffix validation and included in the complete 300-character budget. Give the full genuine disclosure at enrollment and configure provider responses as described in [RESUBMISSION.md](RESUBMISSION.md). Keyword availability and response customization depend on the actual sender and provider path; this list is not proof of deployed configuration. START/UNSTOP can clear a provider block but cannot automatically renew this application's subscription, even if the native response says otherwise.

There is no inbound webhook. The owner must monitor Twilio incoming messages and support requests at brunslx@gmail.com before every scheduled send. Configure the genuine HELP response with this support email. If monitoring cannot be maintained, keep sending disabled. Twilio's STOP handling provides the provider-side block; the application additionally persists suppression if it observes error `21610` during create, poll, or reconciliation. That is a fallback, not immediate inbound processing.

On STOP or any direct opt-out request:

1. Set `SMS_SEND_ENABLED=false` and `RECIPIENT_CONSENT_CONFIRMED=false` locally and in GitHub repository variables. Disable the workflow and let any in-flight job finish; an already submitted message cannot be recalled.
2. Run `python -m scotland_facts.cli subscription suppress` with database credentials. Verify success. If the database is unavailable, keep the workflow disabled and retry suppression when available.
3. Remove `RECIPIENT_NUMBER` from local configuration and GitHub Actions secrets. Never post the number in a support issue.
4. Retain only the private consent/withdrawal record needed for operations. The database suppression row stores no phone and applies to the whole single-recipient installation.

Renewal is never automatic, even after START/UNSTOP or a configuration change:

1. Keep sending disabled and obtain fresh affirmative consent, recorded privately. Follow Twilio's current carrier opt-in procedure; never bypass a provider block.
2. Reconcile and inspect outstanding deliveries before renewal. An old `21610` discovered later conservatively suppresses the entire subscription again.
3. Restore the verified recipient configuration and set `RECIPIENT_CONSENT_CONFIRMED=true` locally and in GitHub. Keep `SMS_SEND_ENABLED=false`.
4. Run `python -m scotland_facts.cli subscription renew --confirm-renewed-consent`. It requires confirmed consent and sending disabled. This is the only application command that clears suppression.
5. Repeat the dry-run/registration/owner authorization checks before setting `SMS_SEND_ENABLED=true` in the environment that will send.

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

Separately create the non-secret repository variables `SMS_SEND_ENABLED=false` and `RECIPIENT_CONSENT_CONFIRMED=false`. Only set them to `true` at the documented consent/authorization steps. Missing variables remain off. Match these switches in local `.env` when operating locally; GitHub variables do not control a local process.

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

Then explicitly authorize one production test by setting `SMS_SEND_ENABLED=true` and `RECIPIENT_CONSENT_CONFIRMED=true` in the sending environment. Both switches are enforced by application code, not just Actions conditions. Persisted suppression must also be clear. It can be run locally:

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

To pause, set `SMS_SEND_ENABLED=false` in GitHub variables and local configuration. Also disable the scheduled workflow:

```text
Actions -> Daily Scotland Fact -> Disable workflow
```

To resume, confirm consent, provider approval, monitoring, and credentials before enabling the workflow and setting `SMS_SEND_ENABLED=true`. A STOP suppression requires the explicit renewal procedure above, not merely enabling the workflow.

## 21. Change The Recipient

Pause all jobs, suppress the old subscription, and remove its recipient configuration first. Follow the full fresh-consent and explicit renewal procedure for the new recipient before changing `RECIPIENT_NUMBER` locally and in GitHub. The singleton suppression is deliberately not keyed by a stored phone; changing a number does not bypass it. Resolve old outstanding deliveries before changing recipients.

Do not edit source code or database rows with a phone number.

## 22. Operational Checks

Useful non-sending commands:

```powershell
& ".venv\Scripts\python.exe" -m scotland_facts.cli doctor
& ".venv\Scripts\python.exe" -m scotland_facts.cli doctor --live
& ".venv\Scripts\python.exe" -m scotland_facts.cli history --limit 10
& ".venv\Scripts\python.exe" -m scotland_facts.cli reconcile
& ".venv\Scripts\python.exe" -m scotland_facts.cli calibrate
```

`calibrate` incurs embedding API usage. `history` prints no phone data. Neither command sends SMS.

`reconcile` validates only database/Twilio credentials and the HTTP timeout; `subscription suppress` validates only database configuration. Malformed generation settings or send gates do not prevent these operational commands. Renewal additionally validates the consent and disabled-send prerequisites. None of these commands generates or sends. Reconciliation exit 1 reports newly observed failures, errors, or still-unresolved messages; exit 0 means no outstanding candidates or all candidates resolved without a new failure. Late failures remain on the fact's status/error fields even though the original generation run may have succeeded. Daily preflight blocks on failures, errors, opt-outs, or SID-less ambiguity, but known-SID queued/sent messages successfully fetched without errors do not block future days merely because delivery receipts are unavailable. Their statuses remain truthful and reconciliation continues. A claimed daily key remains a no-op even after remediation that day.

If a Twilio create call times out ambiguously, do not retry it. The fact remains `SEND_ATTEMPTED` because Twilio may have accepted it. SID-less ambiguous records are reported by `reconcile` and block production until manually investigated. Inspect Twilio Console by time/sender/recipient privately. With verified evidence, an owner may attach the existing Message SID and its correct status to the fact, or mark it failed only when non-acceptance is established. Do not reset it to PENDING, clear `send_attempted_at`, delete a daily run key, or create a replacement SMS. If acceptance cannot be established, keep sending paused. No age cutoff or automatic expiry dismisses unresolved messages.

## What To Complete Next

The immediate owner actions are (see [RESUBMISSION.md](RESUBMISSION.md) for precise fields, intended URLs, and provider templates):

1. Complete the authorized publication of the reviewed `docs/` site and check every public policy/enrollment URL while logged out. The owner has confirmed Elumsden Sole and public support brunslx@gmail.com; see RESUBMISSION.md for the authentication blocker.
2. Verify actual STOP/START/HELP responses, adopt a supported confirmation procedure, and resubmit the corrected campaign. Wait for approval; confirm private recipient consent and trial-recipient verification if applicable.
3. Apply migration `002`, verify deployed security, add credentials, and configure both gates initially off.
4. Run the GitHub Actions dry run.
5. Explicitly authorize one controlled production SMS only when ready.
