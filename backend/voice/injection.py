"""Push approval results into a live call. Registered with core.approvals.register() in main.py."""

from __future__ import annotations

import asyncio
import logging

from core import db
from core.models import Approval
from voice.bridge import ACTIVE_SESSIONS

log = logging.getLogger(__name__)


def approval_sentence(approval: Approval) -> str:
    name = "your family"
    if approval.family_contact_id:
        try:
            rows = db.get_client().table("family_contacts").select("*").eq("id", approval.family_contact_id).limit(1).execute().data
            if rows:
                rel = rows[0].get("relationship") or ""
                name = f"your {rel} {rows[0]['name']}" if rel else rows[0]["name"]
        except Exception:  # noqa: BLE001
            pass
    payload = approval.payload or {}
    what = payload.get("summary") or approval.action.replace("_", " ")
    if approval.status == "approved":
        if approval.outcome == "failed":
            return f"{name[0].upper() + name[1:]} said yes, but I couldn't finish it just now. I'll let them know."
        if approval.outcome == "executed" and payload.get("done_say"):
            return f"Good news, {name} said yes. {payload['done_say']}"
        return f"Good news, {name} said yes, so I'll go ahead and {what} now."
    return f"{name[0].upper() + name[1:]} said not to {what}, so I won't. That's just to keep you safe."


def on_approval_resolved(approval: Approval) -> None:
    session = ACTIVE_SESSIONS.get(approval.user_id)
    if session is None:
        log.info("approval %s resolved; user not on a call", approval.id)
        return
    text = approval_sentence(approval)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(session.inject(text))
    except RuntimeError:
        # Called from a worker thread: hop onto the session's loop.
        asyncio.run_coroutine_threadsafe(session.inject(text), session.loop)
