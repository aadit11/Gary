"""Create and resolve family approvals (safety invariant 3).

    approval_id = approvals.request(user_id, "pay_bill", {"bill_id": ...}, reason)
    ... family replies YES/NO -> webhooks/sms.py -> approvals.resolve(approval_id, approved)

`register(callback)` lets other modules react when an approval resolves. Person 1 registers
voice/injection.py here so the live call hears the outcome.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from core import db, notify
from core.models import Approval

log = logging.getLogger(__name__)

_callbacks: list[Callable[[Approval], None]] = []


def register(callback: Callable[[Approval], None]) -> None:
    """Subscribe to resolved approvals. Callback receives the Approval model."""
    _callbacks.append(callback)


def _to_model(row: dict) -> Approval:
    return Approval(**{k: row.get(k) for k in Approval.model_fields if k in row})


def request(user_id: str, action: str, payload: dict[str, Any], reason: str, summary: str | None = None) -> str:
    """Create a pending approval and text the approver. Returns approval id."""
    approvers = notify.family_contacts(user_id, approvers_only=True)
    contact = approvers[0] if approvers else None
    row = {
        "user_id": user_id,
        "family_contact_id": contact["id"] if contact else None,
        "action": action,
        "payload": payload,
        "reason": reason,
        "status": "pending",
    }
    res = db.get_client().table("approvals").insert(row).execute()
    approval_id = res.data[0]["id"]

    what = summary or action.replace("_", " ")
    body = f"Gary here. A request needs your OK: {what}. Held because {reason}. Reply YES to allow or NO to stop it."
    if contact:
        notify.send_sms(contact["phone"], body)
    else:
        log.warning("No approver on file for user %s; approval %s created without SMS", user_id, approval_id)
    return approval_id


def get(approval_id: str) -> Approval | None:
    res = db.get_client().table("approvals").select("*").eq("id", approval_id).limit(1).execute()
    return _to_model(res.data[0]) if res.data else None


def latest_pending_for_phone(phone: str) -> Approval | None:
    """Find the newest pending approval whose approver has this phone number."""
    phone = notify.normalize_phone(phone)
    contacts = db.get_client().table("family_contacts").select("*").execute().data
    ids = [c["id"] for c in contacts if notify.normalize_phone(c.get("phone")) == phone]
    if not ids:
        return None
    res = (
        db.get_client()
        .table("approvals")
        .select("*")
        .in_("family_contact_id", ids)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return _to_model(res.data[0]) if res.data else None


def find_pending(user_id: str, action: str, **match: Any) -> Approval | None:
    """Newest pending approval for this user and action whose payload contains `match`."""
    rows = (
        db.get_client()
        .table("approvals")
        .select("*")
        .eq("user_id", user_id)
        .eq("action", action)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
        .data
    )
    for row in rows:
        payload = row.get("payload") or {}
        if all(str(payload.get(k)) == str(v) for k, v in match.items()):
            return _to_model(row)
    return None


def notify_resolved(approval: Approval) -> None:
    """Tell subscribers (the live call) that an approval resolved."""
    for cb in list(_callbacks):
        try:
            cb(approval)
        except Exception:  # noqa: BLE001
            log.exception("approval callback failed")


def resolve(approval_id: str, approved: bool, notify: bool = True) -> Approval | None:
    """Mark an approval approved/denied and, unless notify=False, tell subscribers.

    Pass notify=False when the approved action still has to run, then call notify_resolved()
    afterwards so the live call never hears about an action before it happened.
    """
    status = "approved" if approved else "denied"
    res = (
        db.get_client()
        .table("approvals")
        .update({"status": status, "resolved_at": db.now_iso()})
        .eq("id", approval_id)
        .eq("status", "pending")
        .execute()
    )
    if not res.data:
        return None
    approval = _to_model(res.data[0])
    if notify:
        notify_resolved(approval)
    return approval
