"""log_event(): write one row to activity_log for the family dashboard.

Never pass full email bodies or tokens in `data`. Keep it to IDs, amounts, payees, statuses.
"""

from __future__ import annotations

import logging
from typing import Any

from core import db

log = logging.getLogger(__name__)


def log_event(user_id: str, kind: str, summary: str, data: dict[str, Any] | None = None) -> str:
    """Return the new activity_log row id. Never raises; logging must not break a call."""
    row = {"user_id": user_id, "kind": kind, "summary": summary, "data": data or {}}
    try:
        res = db.get_client().table("activity_log").insert(row).execute()
        return res.data[0]["id"]
    except Exception:  # noqa: BLE001
        log.exception("activity_log insert failed: %s %s", kind, summary)
        return ""
