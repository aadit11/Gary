"""Prepare/confirm pending-action helper (safety invariant 2: read-back enforced in code).

    action_id = pending.create("pay_bill", user_id, bill_id=bill_id)      # in prepare_*
    payload   = pending.consume(action_id, "pay_bill", user_id)           # in confirm_*

`consume` raises PendingActionError for anything that is unknown, expired, already used,
the wrong action type, or a different user. confirm_* tools must catch it and speak a
friendly sentence; they must never execute without a successful consume.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from config import settings
from core import db


class PendingActionError(Exception):
    """Raised when a pending action cannot be confirmed. `.say` is safe to speak."""

    def __init__(self, say: str):
        super().__init__(say)
        self.say = say


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | datetime | None) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def create(action_type: str, user_id: str, ttl_seconds: int | None = None, **payload: Any) -> str:
    """Store a prepared action and return its id for the confirm_* tool."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.pending_ttl_seconds
    row = {
        "user_id": user_id,
        "action_type": action_type,
        "payload": payload,
        "expires_at": (_now() + timedelta(seconds=ttl)).isoformat(),
        "used_at": None,
    }
    res = db.get_client().table("pending_actions").insert(row).execute()
    return res.data[0]["id"]


def consume(action_id: str, action_type: str, user_id: str) -> dict[str, Any]:
    """Validate and mark a pending action used, returning its payload. Raises PendingActionError."""
    if not action_id:
        raise PendingActionError("I don't have anything ready to confirm. Let's start that over.")
    client = db.get_client()
    res = client.table("pending_actions").select("*").eq("id", action_id).limit(1).execute()
    if not res.data:
        raise PendingActionError("I couldn't find that request. Let's start over.")
    row = res.data[0]

    if str(row.get("user_id")) != str(user_id):
        raise PendingActionError("That request doesn't belong to this call. Let's start over.")
    if row.get("action_type") != action_type:
        raise PendingActionError("That's not the request I have ready. Let's start over.")
    if row.get("used_at"):
        raise PendingActionError("I've already taken care of that one.")
    expires_at = _parse(row.get("expires_at"))
    if expires_at is None or expires_at < _now():
        raise PendingActionError("That request has expired. Let's go through it again.")

    # Mark used atomically: only succeeds if nobody else consumed it first.
    upd = (
        client.table("pending_actions")
        .update({"used_at": _now().isoformat()})
        .eq("id", action_id)
        .is_("used_at", "null")
        .execute()
    )
    if not upd.data:
        raise PendingActionError("I've already taken care of that one.")
    return dict(row.get("payload") or {})
