from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from scotland_facts.config import Settings
from scotland_facts.db import Database
from scotland_facts.dedupe import highest_semantic_match, normalize_fact
from scotland_facts.embeddings import embed_text
from scotland_facts.fatigue import find_recent_subject, normalize_subjects
from scotland_facts.logging_utils import redact
from scotland_facts.models import (
    AttemptRecord,
    FactStatus,
    RunStatus,
    RunType,
    WorkflowResult,
)
from scotland_facts.research import (
    ResearchValidationError,
    make_openai_client,
    parse_candidate,
    request_research,
    validate_candidate,
)
from scotland_facts.sms import TwilioSendError, make_twilio_client, reconcile_recent, send_once
from scotland_facts.sources import SourceExtractionError, require_web_sources
from scotland_facts.style import StyleValidationError, build_sms, request_suffix, validate_suffix


LOGGER = logging.getLogger(__name__)


class WorkflowError(RuntimeError):
    pass


def make_run_key(dry_run: bool, now: datetime | None = None, timezone: str = "America/New_York") -> str:
    local_now = now.astimezone(ZoneInfo(timezone)) if now else datetime.now(ZoneInfo(timezone))
    if dry_run:
        return f"dryrun:{local_now.strftime('%Y-%m-%dT%H%M%S')}:{uuid4()}"
    return f"daily:{local_now.date().isoformat()}"


def _reject(db: Any, run_id: UUID, record: AttemptRecord, code: str, reason: str) -> None:
    record.rejection_code = code
    record.rejection_reason = reason[:1000]
    db.record_attempt(run_id, record)
    LOGGER.info(
        "candidate rejected run_id=%s attempt=%s category=%s rejection_code=%s similarity=%s",
        run_id,
        record.attempt_number,
        record.category,
        code,
        record.similarity_score,
    )


def run_workflow(
    settings: Settings,
    dry_run: bool = False,
    *,
    db: Any | None = None,
    openai_client: Any | None = None,
    twilio_client: Any | None = None,
    now: datetime | None = None,
    sleep: Any = time.sleep,
    monotonic: Any = time.monotonic,
) -> WorkflowResult:
    if not dry_run:
        settings.require_sending()
    owns_db = db is None
    database = db or Database.connect(settings)
    run_type = RunType.DRY_RUN if dry_run else RunType.DAILY
    run_key = make_run_key(dry_run, now, settings.app_timezone)
    started = database.start_run(run_key, run_type, settings)
    if not started.owned:
        if owns_db:
            database.close()
        return WorkflowResult(
            run_id=started.id,
            run_key=run_key,
            status=RunStatus.NOOP,
            noop=True,
        )

    try:
        twilio = None
        if not dry_run:
            database.require_subscription()
            twilio = twilio_client or make_twilio_client(settings)
            if reconcile_recent(database, twilio, count_unresolved=False):
                raise ValueError("Delivery reconciliation needs attention; run reconcile")
            database.require_subscription()
        ai = openai_client or make_openai_client(settings)
        result = _execute_owned(
            database,
            settings,
            started.id,
            run_key,
            dry_run,
            ai,
            twilio,
            sleep,
            monotonic,
        )
        return result
    except WorkflowError:
        raise
    except Exception as exc:
        try:
            if hasattr(database, "rollback"):
                database.rollback()
            database.fail_run(started.id, "WORKFLOW_ERROR", redact(exc))
        except Exception:
            LOGGER.exception("Unable to persist workflow failure run_id=%s", started.id)
        raise WorkflowError(redact(exc)) from exc
    finally:
        if owns_db:
            database.close()


def _execute_owned(
    db: Any,
    settings: Settings,
    run_id: UUID,
    run_key: str,
    dry_run: bool,
    ai: Any,
    twilio: Any | None,
    sleep: Any,
    monotonic: Any,
) -> WorkflowResult:
    categories = db.category_order()
    recent_subjects = db.recent_subjects(settings.recent_subject_window_days)
    prior_facts = db.prior_facts(50)

    fact_id = None
    for attempt_number in range(1, settings.max_research_attempts + 1):
        category = categories[(attempt_number - 1) % len(categories)]
        record = AttemptRecord(attempt_number=attempt_number, category=category)
        try:
            response = request_research(
                ai, settings, category, recent_subjects, prior_facts, sleep=sleep
            )
        except Exception as exc:
            db.fail_run(run_id, "OPENAI_RESEARCH_ERROR", redact(exc))
            raise WorkflowError(redact(exc)) from exc

        try:
            candidate = parse_candidate(response)
        except ResearchValidationError as exc:
            _reject(db, run_id, record, "MALFORMED_OUTPUT", str(exc))
            continue

        record.candidate_fact = candidate.fact
        record.category = candidate.category
        try:
            validate_candidate(candidate, category, settings.fact_max_chars)
        except ResearchValidationError as exc:
            code = "CATEGORY_MISMATCH" if candidate.category != category else "INVALID_FACT"
            _reject(db, run_id, record, code, str(exc))
            continue
        fact_text = candidate.fact.strip()
        record.candidate_fact = fact_text

        try:
            sources = require_web_sources(response)
        except SourceExtractionError as exc:
            _reject(db, run_id, record, "NO_WEB_SOURCE", str(exc))
            continue
        record.source_url = sources[0].url
        record.source_title = sources[0].title
        record.sources = [source.model_dump() for source in sources]

        try:
            subjects = normalize_subjects(candidate.subjects)
        except ValueError as exc:
            _reject(db, run_id, record, "INVALID_SUBJECTS", str(exc))
            continue
        record.subjects = subjects

        repeated_subject = find_recent_subject(subjects, recent_subjects)
        if repeated_subject:
            _reject(
                db,
                run_id,
                record,
                "RECENT_SUBJECT",
                f"Subject recently used: {repeated_subject}",
            )
            continue

        normalized = normalize_fact(fact_text)
        record.normalized_fact = normalized
        exact_match = db.exact_duplicate(normalized)
        if exact_match:
            record.matched_fact_id = exact_match
            _reject(db, run_id, record, "EXACT_DUPLICATE", "Normalized fact already exists")
            continue

        try:
            embedding = embed_text(ai, settings, fact_text, sleep=sleep)
        except Exception as exc:
            db.fail_run(run_id, "OPENAI_EMBEDDING_ERROR", redact(exc))
            raise WorkflowError(redact(exc)) from exc
        duplicate, matched_id, similarity = highest_semantic_match(
            db.nearest_facts(embedding, 5), settings.semantic_similarity_threshold
        )
        record.similarity_score = similarity
        record.matched_fact_id = matched_id
        if duplicate:
            _reject(
                db,
                run_id,
                record,
                "SEMANTIC_DUPLICATE",
                f"Similarity {similarity:.4f} meets threshold",
            )
            continue

        recent_sms = db.recent_sms(10)
        sms_text: str | None = None
        style_errors: list[str] = []
        for _ in range(settings.max_style_attempts):
            try:
                suffix = request_suffix(ai, settings, fact_text, recent_sms, sleep=sleep)
                suffix = validate_suffix(suffix, settings.style_suffix_max_chars)
                sms_text = build_sms(fact_text, suffix, settings.sms_max_chars)
                break
            except StyleValidationError as exc:
                style_errors.append(redact(exc))
            except Exception as exc:
                _reject(db, run_id, record, "OPENAI_STYLE_ERROR", redact(exc))
                db.fail_run(run_id, "OPENAI_STYLE_ERROR", redact(exc))
                raise WorkflowError(redact(exc)) from exc
        if sms_text is None:
            _reject(db, run_id, record, "STYLE_EXHAUSTED", "; ".join(style_errors))
            db.fail_run(run_id, "STYLE_EXHAUSTED", "; ".join(style_errors)[-1000:])
            raise WorkflowError("Style generation exhausted without a valid suffix")

        fact_id = db.try_accept_fact(
            run_id, record, sms_text, embedding,
            FactStatus.DRY_RUN if dry_run else FactStatus.PENDING, settings,
        )
        if fact_id is not None:
            break
        _reject(db, run_id, record, record.rejection_code, record.rejection_reason)
        # A competing writer won after the speculative checks. Refresh context
        # before the next bounded research attempt rather than accepting stale novelty.
        recent_subjects = db.recent_subjects(settings.recent_subject_window_days)
        prior_facts = db.prior_facts(50)

    if fact_id is None:
        db.fail_run(run_id, "RESEARCH_EXHAUSTED", "No valid research candidate was produced")
        raise WorkflowError("Research exhausted without a valid candidate")

    if dry_run:
        db.complete_run(run_id)
        return WorkflowResult(
            run_id=run_id,
            run_key=run_key,
            status=RunStatus.SUCCEEDED,
            sms_text=sms_text,
            source_url=sources[0].url,
            attempts=attempt_number,
        )

    assert twilio is not None
    try:
        send_once(
            db,
            fact_id,
            sms_text,
            settings,
            twilio,
            sleep=sleep,
            monotonic=monotonic,
        )
    except TwilioSendError as exc:
        db.fail_run(run_id, exc.failure_code, redact(exc))
        raise WorkflowError(redact(exc)) from exc
    db.complete_run(run_id)
    return WorkflowResult(
        run_id=run_id,
        run_key=run_key,
        status=RunStatus.SUCCEEDED,
        sms_text=sms_text,
        source_url=sources[0].url,
        attempts=attempt_number,
    )
