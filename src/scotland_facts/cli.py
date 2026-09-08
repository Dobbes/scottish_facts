from __future__ import annotations

import argparse
import json
import sys

import psycopg
from openai import OpenAI
from pydantic import ValidationError

from scotland_facts.config import ConfigMode, Settings, load_settings
from scotland_facts.db import Database
from scotland_facts.embeddings import cosine_similarity, embed_text
from scotland_facts.logging_utils import configure_logging, redact
from scotland_facts.migrations import apply_migrations
from scotland_facts.orchestrator import WorkflowError, run_workflow
from scotland_facts.sms import make_twilio_client, reconcile_recent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scotland-facts")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="Run non-destructive environment checks")
    doctor.add_argument("--live", action="store_true", help="Validate OpenAI and Twilio connectivity")
    subparsers.add_parser("migrate", help="Apply database migrations")
    subparsers.add_parser("reconcile", help="Fetch unresolved delivery states without sending")
    subscription = subparsers.add_parser("subscription", help="Manually suppress or renew consent")
    subscription.add_argument("action", choices=("suppress", "renew"))
    subscription.add_argument("--confirm-renewed-consent", action="store_true")
    run = subparsers.add_parser("run", help="Run one daily workflow")
    run.add_argument("--dry-run", action="store_true", help="Generate and persist without Twilio")
    subparsers.add_parser("calibrate", help="Print embedding similarity calibration pairs")
    history = subparsers.add_parser("history", help="Print recent facts")
    history.add_argument("--limit", type=int, default=10)
    return parser


def doctor(settings: Settings, live: bool = False) -> int:
    failures: list[str] = []
    version_ok = sys.version_info >= (3, 12)
    print(f"Python >=3.12: {'OK' if version_ok else 'FAIL'} ({sys.version.split()[0]})")
    if not version_ok:
        failures.append("Python 3.12 or newer is required")

    secret_names = (
        "openai_api_key",
        "supabase_db_url",
        "twilio_account_sid",
        "twilio_api_key_sid",
        "twilio_api_key_secret",
        "twilio_from_number",
        "recipient_number",
    )
    for name in secret_names:
        print(f"{name.upper()}: {'present' if getattr(settings, name) else 'not set'}")
    print("Configuration: OK")
    print(f"SMS sending enabled: {settings.sms_send_enabled}")
    print(f"Recipient consent confirmed: {settings.recipient_consent_confirmed}")

    if settings.supabase_db_url:
        try:
            with psycopg.connect(settings.secret("supabase_db_url")) as conn:
                conn.execute("set search_path to public, extensions")
                conn.execute("select 1").fetchone()
                vector = bool(
                    conn.execute("select 1 from pg_extension where extname = 'vector'").fetchone()
                )
                tables = {
                    row[0]
                    for row in conn.execute(
                        """
                        select table_name from information_schema.tables
                        where table_schema = 'public' and table_name in
                          ('generation_runs', 'facts', 'generation_attempts', 'schema_migrations', 'subscription_state')
                        """
                    ).fetchall()
                }
                expected = {"generation_runs", "facts", "generation_attempts", "schema_migrations", "subscription_state"}
                structure_ok = vector and expected <= tables
                print(f"Database connection: OK")
                print(f"Database migration: {'OK' if structure_ok else 'MISSING'}")
                if not structure_ok:
                    failures.append("Database is connected but required migration objects are missing")
                else:
                    secured = conn.execute(
                        """
                        select bool_and(c.relrowsecurity
                            and pg_get_userbyid(c.relowner) = current_user
                            and not exists (
                                select 1 from aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
                                where a.grantee = 0
                            )
                            and not exists (
                                select 1 from pg_roles r
                                where r.rolname in ('anon', 'authenticated', 'service_role')
                                  and has_table_privilege(r.oid, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                            ))
                        from pg_class c join pg_namespace n on n.oid = c.relnamespace
                        where n.nspname = 'public' and c.relname = any(%s)
                        """, (list(expected),),
                    ).fetchone()[0]
                    print(f"Database server-only security: {'OK' if secured else 'FAIL'}")
                    if not secured:
                        failures.append("RLS/API privileges or runtime table ownership need attention")
        except Exception as exc:
            print(f"Database connection: FAIL ({redact(exc)})")
            failures.append("Database connection failed")
    else:
        print("Database connection: skipped (SUPABASE_DB_URL not set)")

    if live:
        missing_openai = not settings.openai_api_key
        twilio_names = (
            "twilio_account_sid",
            "twilio_api_key_sid",
            "twilio_api_key_secret",
            "twilio_from_number",
        )
        missing_twilio = [name.upper() for name in twilio_names if not getattr(settings, name)]
        if missing_openai:
            failures.append("OPENAI_API_KEY is required for doctor --live")
        else:
            try:
                client = OpenAI(api_key=settings.secret("openai_api_key"), max_retries=0)
                client.responses.create(
                    model=settings.research_model,
                    store=False,
                    input="Reply with the single word OK.",
                    max_output_tokens=16,
                )
                print("OpenAI live connectivity: OK")
            except Exception as exc:
                print(f"OpenAI live connectivity: FAIL ({redact(exc)})")
                failures.append("OpenAI live connectivity failed")
        if missing_twilio:
            failures.append(f"Missing Twilio live credentials: {', '.join(missing_twilio)}")
        else:
            try:
                client = make_twilio_client(settings)
                senders = client.incoming_phone_numbers.list(
                    phone_number=settings.secret("twilio_from_number"), limit=1
                )
                if not senders:
                    raise ValueError("Configured Twilio sender is not owned by this account")
                print("Twilio live connectivity: OK (no SMS sent)")
            except Exception as exc:
                print(f"Twilio live connectivity: FAIL ({redact(exc)})")
                failures.append("Twilio live connectivity failed")
    else:
        print("External API calls: skipped (use --live to validate without sending SMS)")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("Doctor: OK")
    return 0


def calibrate(settings: Settings) -> int:
    client = OpenAI(api_key=settings.secret("openai_api_key"), max_retries=0)
    pairs = (
        (
            "Scotland's national animal is the unicorn.",
            "The unicorn is Scotland's national animal.",
            "paraphrase",
        ),
        (
            "Edinburgh Castle stands on an extinct volcano.",
            "An extinct volcano supports Edinburgh Castle.",
            "paraphrase",
        ),
        (
            "The Forth Bridge opened in 1890.",
            "Scotland has more than 790 offshore islands.",
            "distinct",
        ),
        (
            "The word whisky comes from Gaelic for water of life.",
            "The Edinburgh Festival Fringe began in 1947.",
            "distinct",
        ),
    )
    print(f"Configured semantic threshold: {settings.semantic_similarity_threshold:.4f}")
    for left, right, label in pairs:
        left_vector = embed_text(client, settings, left)
        right_vector = embed_text(client, settings, right)
        print(f"{label:10} {cosine_similarity(left_vector, right_vector):.4f} | {left} / {right}")
    return 0


def print_history(settings: Settings, limit: int) -> int:
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    database = Database.connect(settings)
    try:
        for row in database.history(limit):
            safe = {key: str(value) if key == "generated_at" else value for key, value in row.items()}
            print(json.dumps(safe, ensure_ascii=True, default=str))
    finally:
        database.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    try:
        if args.command == "doctor":
            return doctor(load_settings(ConfigMode.DOCTOR), args.live)
        if args.command == "migrate":
            settings = load_settings(ConfigMode.MIGRATE)
            applied = apply_migrations(settings.secret("supabase_db_url"))
            print("Applied migrations: " + ", ".join(applied) if applied else "No unapplied migrations")
            return 0
        if args.command in {"reconcile", "subscription"}:
            mode = ConfigMode.RECONCILE if args.command == "reconcile" else ConfigMode(args.action)
            settings = load_settings(mode)
            if args.command == "subscription" and args.action == "renew":
                if not args.confirm_renewed_consent or not settings.recipient_consent_confirmed:
                    raise ValueError("Renewal requires --confirm-renewed-consent and RECIPIENT_CONSENT_CONFIRMED=true")
                if settings.sms_send_enabled:
                    raise ValueError("Disable SMS_SEND_ENABLED before renewing consent")
            database = Database.connect(settings)
            try:
                if args.command == "reconcile":
                    problems = reconcile_recent(database, make_twilio_client(settings))
                    print(f"Reconciliation complete; failures/errors/unresolved: {problems}; no SMS sent")
                    return 1 if problems else 0
                database.set_subscription_suppressed(args.action == "suppress")
                print("Subscription suppressed" if args.action == "suppress" else "Subscription renewed; sending remains disabled")
                return 0
            finally:
                database.close()
        if args.command == "run":
            mode = ConfigMode.DRY_RUN if args.dry_run else ConfigMode.PRODUCTION
            result = run_workflow(load_settings(mode), dry_run=args.dry_run)
            if result.noop:
                print(f"No-op: run key {result.run_key} already exists; no SMS attempted")
            else:
                print(result.sms_text)
                print(f"Source: {result.source_url}")
                print(f"Run: {result.run_key}; attempts: {result.attempts}; status: {result.status}")
            return 0
        if args.command == "calibrate":
            return calibrate(load_settings(ConfigMode.CALIBRATE))
        if args.command == "history":
            return print_history(load_settings(ConfigMode.HISTORY), args.limit)
    except (ValidationError, ValueError, WorkflowError, psycopg.Error) as exc:
        print(f"Error: {redact(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {redact(exc)}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
