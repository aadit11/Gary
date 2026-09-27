"""Inbound SMS webhook: family replies YES/NO to approval texts.

Twilio posts form fields (From, Body). We find the newest pending approval for that phone,
resolve it, run the approved action, and reply with TwiML. Person 1 registers
voice/injection.py via core.approvals.register() so the live call hears the result.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from fastapi import APIRouter, Form
from pydantic import BaseModel
from fastapi.responses import Response

from core import activity, approvals, notify
from core.models import Approval

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_YES = re.compile(r"^\s*(yes|y|ok|okay|approve|approved|allow|sure)\b", re.I)
_NO = re.compile(r"^\s*(no|n|deny|denied|stop|cancel|don'?t)\b", re.I)


def _twiml(text: str) -> Response:
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Response(content=f"<Response><Message>{safe}</Message></Response>", media_type="application/xml")


# Executors run when an approval is approved. Verticals register theirs at import time:
#   from webhooks.sms import ACTION_EXECUTORS; ACTION_EXECUTORS["pay_bill"] = my_fn
# Each takes the Approval and returns a short sentence for the family text.
ACTION_EXECUTORS: dict[str, Callable[[Approval], str]] = {}


def _execute(approval: Approval) -> str:
    """Run the approved action, set approval.outcome, and return the family reply."""
    fn = ACTION_EXECUTORS.get(approval.action)
    if fn is None:
        log.warning("No executor for approved action %s (approval %s)", approval.action, approval.id)
        activity.log_event(approval.user_id, "approval_approved", f"Approved: {approval.action}", {"approval_id": approval.id})
        return "Got it, approved."
    try:
        text = fn(approval)
        approval.outcome = "executed"
        return text
    except Exception:  # noqa: BLE001
        log.exception("executor failed for %s", approval.action)
        approval.outcome = "failed"
        return "Approved, but something went wrong carrying it out. We'll follow up."


def handle_reply(from_phone: str, body: str) -> str:
    """Pure logic (also used by tests). Returns the text to send back."""
    phone = notify.normalize_phone(from_phone)
    approval = approvals.latest_pending_for_phone(phone)
    if approval is None:
        return "Thanks. There's nothing waiting for your approval right now."

    if _YES.match(body or ""):
        resolved = approvals.resolve(approval.id, approved=True, notify=False)
        if resolved is None:
            return "That request was already handled."
        text = _execute(resolved)
        approvals.notify_resolved(resolved)
        return text
    if _NO.match(body or ""):
        resolved = approvals.resolve(approval.id, approved=False)
        if resolved is None:
            return "That request was already handled."
        activity.log_event(resolved.user_id, "approval_denied", f"Denied: {resolved.action}", {"approval_id": resolved.id})
        return "Understood, we won't go ahead with it."
    return "Please reply YES to allow it or NO to stop it."


def resolve_by_id(approval_id: str, approved: bool) -> str:
    """Same outcome as a YES/NO text, for the family dashboard's Approve/Deny buttons."""
    if approved:
        resolved = approvals.resolve(approval_id, approved=True, notify=False)
        if resolved is None:
            return "That request was already handled."
        text = _execute(resolved)
        approvals.notify_resolved(resolved)
        return text
    resolved = approvals.resolve(approval_id, approved=False)
    if resolved is None:
        return "That request was already handled."
    activity.log_event(resolved.user_id, "approval_denied", f"Denied: {resolved.action}", {"approval_id": resolved.id})
    return "Understood, we won't go ahead with it."


class Decision(BaseModel):
    approved: bool


@router.post("/approvals/{approval_id}")
async def decide(approval_id: str, decision: Decision) -> dict:
    """Family dashboard: approve or deny a held request (runs the action and tells the caller)."""
    return {"message": resolve_by_id(approval_id, decision.approved)}


@router.post("/sms")
async def inbound_sms(From: str = Form(""), Body: str = Form("")) -> Response:  # noqa: N803 (Twilio field names)
    return _twiml(handle_reply(From, Body))
