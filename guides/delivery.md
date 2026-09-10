# Two-recipient delivery

Scotland Facts generates one daily fact and sends the same complete SMS separately
to each configured, consenting recipient. It is not a group text.

## Configuration

| Actions secret | Internal slot | Required |
| --- | --- | --- |
| `RECIPIENT_NUMBER` | `primary` | Yes for production |
| `FATHER_IN_LAW_NUMBER` | `secondary` | Optional |

Both values must be distinct E.164 phone numbers and different from the sender.
The application rejects duplicate destinations rather than sending twice.
The optional second secret is explicitly passed through the daily Actions workflow.
The shared `RECIPIENT_CONSENT_CONFIRMED` variable asserts current consent for
**every configured recipient**. `SMS_SEND_ENABLED` controls the whole installation.

`doctor` reports **Configured recipients: 2 (primary, secondary)** when both are
present, without printing either value. The active OpenAI key can remain exclusively
in GitHub Secrets; use a hosted dry run to validate the complete configuration.

## Upgrade an existing installation

1. Set `SMS_SEND_ENABLED=false` and wait for any in-flight run to finish.
2. Apply migrations with `python -m scotland_facts.cli migrate`; repeat to check
   idempotency. Migration `003_recipient_deliveries.sql` adds `sms_deliveries`.
3. Run `python -m scotland_facts.cli doctor` to verify all six server-only tables.
4. Add the optional second number as an Actions **secret**, and obtain its consent.
5. Run **Daily Scotland Fact → Run workflow → main**, keeping dry-run checked.
   Verify that doctor reports **2** recipients and **Run manual dry-run** succeeds.
6. Set `RECIPIENT_CONSENT_CONFIRMED=true` for both recipients, then
   `SMS_SEND_ENABLED=true`. The next daily schedule targets 10:15 AM Eastern.

Migration `003` preserves historical primary delivery status, SID, error, and send
boundary. It creates no historical secondary sends and no delivery rows for previews.
Existing daily run keys remain unchanged. Old application versions must not run
against the upgraded deployment: delivery writes now use the new ledger.

## Delivery ledger

Each production fact gets one `sms_deliveries` row per configured slot. All rows
are committed before the first Twilio create call. Each row has its own:

- unique `(fact_id, recipient_slot)` identity;
- `PENDING → SEND_ATTEMPTED` compare-and-set, committed before its create call;
- Message SID, provider status/error, and delivery timestamps.

The ledger contains only anonymous slots, not phone numbers or phone hashes.
RLS and revoked API-role privileges restrict it to the trusted PostgreSQL owner.
Legacy delivery columns on `facts` mirror **only the primary recipient** for
backwards-compatible history. `sms_deliveries` is authoritative for both recipients;
`history` includes a separate `deliveries` array so partial delivery is visible.

Reconciliation fetches outstanding ledger entries for both slots even if the
second number has since been removed from configuration. It needs only the stored
Message SID, not either destination number. A SID-less ambiguous attempt remains
an explicit manual-inspection blocker.

## Failure and retry behavior

A definite provider rejection, delivery failure, or ambiguous timeout for one
recipient is recorded independently. The job can attempt the other recipient once,
then reports overall failure if either attempt failed. Successfully submitted
messages are never replayed to recover another recipient's failure.

A database error or subscription suppression stops further sending. If execution
stops between recipients, an unattempted row remains `PENDING`; it is not automatically
resumed or sent as a catch-up. Re-running the same daily key is always a no-op,
including after partial failure. This deliberately favors a missed message over
a duplicate. Do not delete run keys or reset send boundaries.

Dry runs generate and persist a fact, consume novelty, and create **no delivery
rows**. They never initialize a Twilio send. A successful preview validates hosted
research/configuration, not actual delivery to either device.

## Consent, opt-outs, and changing recipients

Suppression is deliberately **shared**: a direct opt-out from either recipient or
an observed Twilio `21610` blocks the entire installation, including any remaining
send in that run. This version has no independent per-recipient suppression UI or
inbound webhook. The operator monitors incoming replies and support requests.

On an opt-out: disable both switches, run `subscription suppress`, and remove the
withdrawing recipient's secret. Reconcile existing deliveries. Before restarting,
confirm consent for every remaining configured recipient, keep sending disabled,
and run `subscription renew --confirm-renewed-consent` with consent confirmed.
Provider START/UNSTOP and removing a secret never clear application suppression.

Pause and resolve outstanding deliveries before changing the number assigned to
a slot. Slots identify configuration positions, not permanently identifiable people.
Keep consent/withdrawal records privately outside the repository and database.
