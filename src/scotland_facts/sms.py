from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client
from twilio.http.http_client import TwilioHttpClient

from scotland_facts.config import Settings
from scotland_facts.logging_utils import redact
from scotland_facts.models import FactStatus


LOGGER = logging.getLogger(__name__)


class TwilioSendError(RuntimeError):
    failure_code = "TWILIO_SEND_FAILED"


class AmbiguousTwilioSendError(TwilioSendError):
    failure_code = "TWILIO_AMBIGUOUS_SEND"


class DefinitiveTwilioSendError(TwilioSendError):
    failure_code = "TWILIO_REJECTED"


class TwilioDeliveryError(TwilioSendError):
    failure_code = "TWILIO_DELIVERY_FAILED"


def make_twilio_client(settings: Settings) -> Client:
    return Client(
        settings.secret("twilio_api_key_sid"),
        settings.secret("twilio_api_key_secret"),
        settings.secret("twilio_account_sid"),
        http_client=TwilioHttpClient(timeout=settings.twilio_http_timeout_seconds, max_retries=0),
    )


def app_status_for_twilio(status: str) -> FactStatus:
    return {
        "delivered": FactStatus.DELIVERED,
        "sent": FactStatus.SENT,
        "failed": FactStatus.FAILED,
        "undelivered": FactStatus.FAILED,
        "canceled": FactStatus.FAILED,
    }.get(status.lower(), FactStatus.SUBMITTED)


def send_once(
    db: Any,
    fact_id: UUID,
    sms_text: str,
    settings: Settings,
    client: Any,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    *,
    recipient_slot: str = "primary",
) -> tuple[str, FactStatus]:
    settings.require_sending()
    if recipient_slot not in settings.recipient_slots():
        raise ValueError("Delivery recipient is not configured")
    recipient = settings.recipient_secret(recipient_slot)
    db.require_subscription()
    db.mark_send_attempted(fact_id, recipient_slot)
    try:
        message = client.messages.create(
            body=sms_text,
            from_=settings.secret("twilio_from_number"),
            to=recipient,
            smart_encoded=True,
        )
    except TwilioRestException as exc:
        if str(getattr(exc, "code", None)) == "21610":
            db.set_subscription_suppressed(True)
        status = getattr(exc, "status", None)
        if isinstance(status, int) and 400 <= status < 500 and status != 408:
            db.mark_definitive_send_failure(fact_id, getattr(exc, "code", None))
            raise DefinitiveTwilioSendError(redact(exc)) from exc
        raise AmbiguousTwilioSendError(redact(exc)) from exc
    except Exception as exc:
        raise AmbiguousTwilioSendError(redact(exc)) from exc

    error_code = getattr(message, "error_code", None)
    if str(error_code) == "21610":
        db.set_subscription_suppressed(True)
    sid = getattr(message, "sid", None)
    if not sid:
        raise AmbiguousTwilioSendError("Twilio returned no Message SID")
    initial_status = str(getattr(message, "status", "accepted") or "accepted").lower()
    status = FactStatus.FAILED if error_code else app_status_for_twilio(initial_status)
    db.mark_submitted(fact_id, sid, initial_status, status, error_code)
    status = poll_delivery(db, fact_id, sid, settings, client, sleep=sleep,
                           monotonic=monotonic, initial_status=status)
    if status == FactStatus.FAILED:
        raise TwilioDeliveryError("Twilio reported failed or undelivered")
    return sid, status


def poll_delivery(
    db: Any,
    fact_id: UUID,
    sid: str,
    settings: Settings,
    client: Any,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    initial_status: FactStatus = FactStatus.SUBMITTED,
) -> FactStatus:
    if initial_status in {FactStatus.DELIVERED, FactStatus.FAILED}:
        return initial_status
    deadline = monotonic() + settings.twilio_status_poll_seconds
    latest = initial_status
    while monotonic() < deadline:
        try:
            message = client.messages(sid).fetch()
        except Exception as exc:
            LOGGER.warning("Twilio delivery poll failed sid=%s error=%s", sid, redact(exc))
            if str(getattr(exc, "code", None)) == "21610":
                db.set_subscription_suppressed(True)
            break
        twilio_status = str(getattr(message, "status", "accepted") or "accepted").lower()
        error_code = getattr(message, "error_code", None)
        if str(error_code) == "21610":
            db.set_subscription_suppressed(True)
        mapped = FactStatus.FAILED if error_code else app_status_for_twilio(twilio_status)
        if not (latest == FactStatus.SENT and mapped == FactStatus.SUBMITTED):
            latest = mapped
        db.update_twilio_status(
            fact_id, latest, twilio_status, getattr(message, "error_code", None)
        )
        if latest in {FactStatus.DELIVERED, FactStatus.FAILED}:
            return latest
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(settings.twilio_status_poll_interval_seconds, remaining))
    return latest


def reconcile_recent(db: Any, client: Any, *, count_unresolved: bool = True) -> int:
    """Report issues; production excludes known-SID deliveries awaiting receipts."""
    problems = 0
    try:
        candidates = db.reconciliation_candidates()
    except Exception as exc:
        if hasattr(db, "rollback"):
            db.rollback()
        LOGGER.warning("Twilio reconciliation lookup failed error=%s", redact(exc))
        return 1
    for row in candidates:
        if not row.get("twilio_sid"):
            problems += 1
            LOGGER.error("Ambiguous send requires manual provider inspection fact_id=%s; never retry", row["id"])
            continue
        try:
            message = client.messages(row["twilio_sid"]).fetch()
            status_text = str(getattr(message, "status", "accepted") or "accepted").lower()
            error_code = getattr(message, "error_code", None)
            if str(error_code) == "21610":
                db.set_subscription_suppressed(True)
            status = FactStatus.FAILED if error_code else app_status_for_twilio(status_text)
            if row.get("status") == FactStatus.SENT.value and status == FactStatus.SUBMITTED:
                status = FactStatus.SENT
            db.update_twilio_status(
                row["id"], status, status_text, getattr(message, "error_code", None)
            )
            if status == FactStatus.FAILED:
                problems += 1
                LOGGER.error("Late Twilio delivery failure sid=%s code=%s", row["twilio_sid"], error_code)
            elif status != FactStatus.DELIVERED:
                if count_unresolved:
                    problems += 1
                LOGGER.warning("Twilio delivery unresolved sid=%s status=%s", row["twilio_sid"], status)
        except Exception as exc:
            problems += 1
            if hasattr(db, "rollback"):
                db.rollback()
            if str(getattr(exc, "code", None)) == "21610":
                db.set_subscription_suppressed(True)
            LOGGER.warning(
                "Twilio reconciliation failed sid=%s error=%s", row["twilio_sid"], redact(exc)
            )
    return problems
