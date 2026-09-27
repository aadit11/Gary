"""notify_family() and SMS helpers (Twilio).

When Twilio credentials are missing, send_sms logs the message and returns "" so the rest
of the system keeps working for teammates without creds.
"""

from __future__ import annotations

import logging
import re

from config import settings
from core import db

log = logging.getLogger(__name__)


def normalize_phone(raw: str | None) -> str:
    """Return E.164 (+1XXXXXXXXXX) for US numbers; other inputs are returned with digits and leading +."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits


def _twilio():
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_phone_number):
        return None
    from twilio.rest import Client  # lazy so tests never import it

    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _can_message(phone: str) -> bool:
    """False for empty, non-US, or fictional numbers. Those must not create a Twilio message."""
    digits = phone.lstrip("+")
    if len(digits) != 11 or not digits.startswith("1"):
        return False
    return digits[1:4] not in {"500", "555"}


def addresses(to: str) -> tuple[str, str]:
    """Return (to, from) Twilio addresses for the configured family channel."""
    to = normalize_phone(to)
    if settings.family_channel.lower() == "whatsapp":
        return f"whatsapp:{to}", settings.twilio_whatsapp_from
    return to, settings.twilio_phone_number


def send_sms(to: str, body: str) -> str:
    """Send one message on the family channel (SMS or WhatsApp).

    Returns the Twilio message SID, or "" when not configured, the number is invalid, or on failure.
    """
    plain = normalize_phone(to)
    if not _can_message(plain):
        log.info("Message not sent (invalid number %s): %s", plain, body)
        return ""
    to_addr, from_addr = addresses(to)
    client = _twilio()
    if client is None:
        log.info("Message (not sent, Twilio not configured) to %s: %s", to_addr, body)
        return ""
    try:
        msg = client.messages.create(to=to_addr, from_=from_addr, body=body)
        return msg.sid or ""
    except Exception:  # noqa: BLE001
        log.exception("Message send failed to %s", to_addr)
        return ""


def family_contacts(user_id: str, approvers_only: bool = False) -> list[dict]:
    q = db.get_client().table("family_contacts").select("*").eq("user_id", user_id)
    if approvers_only:
        q = q.eq("can_approve", True)
    return q.execute().data


def notify_family(user_id: str, message: str, approvers_only: bool = False) -> list[str]:
    """Text every family contact for the user. Returns the message SIDs that were sent."""
    sids = []
    for c in family_contacts(user_id, approvers_only=approvers_only):
        sid = send_sms(c["phone"], message)
        if sid:
            sids.append(sid)
    return sids
