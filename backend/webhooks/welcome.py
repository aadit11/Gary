"""POST /notify/welcome: text the approver that Gary will send approval requests to this number.

The web app calls this right after onboarding saves the caregiver's number, so the caregiver
sees a first text from Gary before any real approval is needed. It takes only a user id (no
phone, no message body), so it cannot be used to send arbitrary texts, and one user can trigger
it at most once every 30 seconds.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from core import activity, db, notify

log = logging.getLogger(__name__)
router = APIRouter(prefix="/notify", tags=["notify"])

COOLDOWN_S = 30
_last_sent: dict[str, float] = {}


class WelcomeRequest(BaseModel):
    user_id: str


def welcome_text(person_name: str, caregiver_name: str) -> str:
    person = (person_name or "").split(" ")[0] or "your family member"
    you = (caregiver_name or "").split(" ")[0] or "there"
    return (
        f"Hi {you}, this is Gary, {person}'s phone helper. When {person} asks me for something that "
        f"needs your okay, I'll text you here. Reply YES to allow it or NO to stop it."
    )


def send_welcome(user_id: str) -> dict:
    """Pure logic (also used by tests). Returns {sent, reason, channel, to?, name?}."""
    users = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
    if not users:
        raise HTTPException(status_code=404, detail="unknown user")
    result: dict = {"sent": False, "reason": "", "channel": settings.family_channel.lower()}
    approvers = notify.family_contacts(user_id, approvers_only=True)
    if not approvers:
        result["reason"] = "no_approver"
        return result
    contact = approvers[0]
    phone = notify.normalize_phone(contact.get("phone"))
    result.update(to=phone[-4:], name=contact.get("name") or "")
    # A bad number is reported before a missing Twilio setup, so the form can flag it anywhere.
    if not notify.can_message(phone):
        result["reason"] = "invalid_number"
        return result
    if not notify.is_configured():
        result["reason"] = "not_configured"
        return result
    now = time.monotonic()
    if now - _last_sent.get(user_id, 0.0) < COOLDOWN_S:
        result["reason"] = "cooldown"
        return result
    _last_sent[user_id] = now
    sid = notify.send_sms(phone, welcome_text(users[0].get("name") or "", contact.get("name") or ""))
    if not sid:
        result["reason"] = "send_failed"
        return result
    activity.log_event(
        user_id,
        "family_welcomed",
        f"Sent {contact.get('name') or 'the family contact'} a hello text",
        {"channel": result["channel"]},
    )
    result.update(sent=True, reason="sent")
    return result


@router.post("/welcome")
async def welcome(req: WelcomeRequest) -> dict:
    return send_welcome(req.user_id)
