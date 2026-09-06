from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

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
    )


def app_status_for_twilio(status: str) -> FactStatus:
    return {
        "delivered": FactStatus.DELIVERED,
        "sent": FactStatus.SENT,
        "failed": FactStatus.FAILED,
        "undelivered": FactStatus.FAILED,
    }.get(status.lower(), FactStatus.SUBMITTED)


def send_once(
    db: Any,
    fact_id: UUID,
    sms_text: str,
    settings: Settings,
    client: Any,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[str, FactStatus]:
    db.mark_send_attempted(fact_id)
    try:
        message = client.messages.create(
            body=sms_text,
            from_=settings.secret("twilio_from_number"),
            to=settings.secret("recipient_number"),
            smart_encoded=True,
        )
    except TwilioRestException as exc:
        status = getattr(exc, "status", None)
        if isinstance(status, int) and 400 <= status < 500 and status != 408:
            db.mark_definitive_send_failure(fact_id, getattr(exc, "code", None))
            raise DefinitiveTwilioSendError(redact(exc)) from exc
        raise AmbiguousTwilioSendError(redact(exc)) from exc
    except Exception as exc:
        raise AmbiguousTwilioSendError(redact(exc)) from exc

    sid = getattr(message, "sid", None)
    if not sid:
        raise AmbiguousTwilioSendError("Twilio returned no Message SID")
    initial_status = str(getattr(message, "status", "accepted") or "accepted").lower()
    db.mark_submitted(fact_id, sid, initial_status)
    status = poll_delivery(db, fact_id, sid, settings, client, sleep=sleep, monotonic=monotonic)
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
) -> FactStatus:
    deadline = monotonic() + settings.twilio_status_poll_seconds
    latest = FactStatus.SUBMITTED
    while monotonic() < deadline:
        try:
            message = client.messages(sid).fetch()
        except Exception as exc:
            LOGGER.warning("Twilio delivery poll failed sid=%s error=%s", sid, redact(exc))
            break
        twilio_status = str(getattr(message, "status", "accepted") or "accepted").lower()
        latest = app_status_for_twilio(twilio_status)
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


def reconcile_recent(db: Any, client: Any) -> None:
    try:
        candidates = db.reconciliation_candidates(7)
    except Exception as exc:
        if hasattr(db, "rollback"):
            db.rollback()
        LOGGER.warning("Twilio reconciliation lookup failed error=%s", redact(exc))
        return
    for row in candidates:
        try:
            message = client.messages(row["twilio_sid"]).fetch()
            status_text = str(getattr(message, "status", "accepted") or "accepted").lower()
            status = app_status_for_twilio(status_text)
            if row.get("status") == FactStatus.SENT.value and status == FactStatus.SUBMITTED:
                status = FactStatus.SENT
            db.update_twilio_status(
                row["id"], status, status_text, getattr(message, "error_code", None)
            )
        except Exception as exc:
            if hasattr(db, "rollback"):
                db.rollback()
            LOGGER.warning(
                "Twilio reconciliation failed sid=%s error=%s", row["twilio_sid"], redact(exc)
            )
