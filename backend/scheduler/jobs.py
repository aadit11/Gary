"""Due reminders (Phase 1). Morning briefings, retries, and family alerts land in Phase 2.

Every minute: for each active reminder whose time_of_day (in the user's timezone) matches the
current minute and that has no reminder_logs row for today, log it and place the call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import db

log = logging.getLogger(__name__)


def _user_tz(user_id: str, cache: dict) -> str:
    if user_id not in cache:
        rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
        cache[user_id] = (rows[0].get("timezone") if rows else None) or "America/New_York"
    return cache[user_id]


def due_reminders(now_utc: datetime | None = None) -> list[dict]:
    """Active reminders due this minute (user-local) without a log entry today."""
    now_utc = now_utc or datetime.now(timezone.utc)
    client = db.get_client()
    reminders = client.table("reminders").select("*").eq("active", True).execute().data
    tz_cache: dict = {}
    due = []
    for r in reminders:
        local = now_utc.astimezone(ZoneInfo(_user_tz(r["user_id"], tz_cache)))
        hhmm = str(r.get("time_of_day", ""))[:5]
        if hhmm != local.strftime("%H:%M"):
            continue
        if r.get("recurrence") == "weekdays" and local.weekday() >= 5:
            continue
        today_prefix = local.date().isoformat()
        logs = client.table("reminder_logs").select("*").eq("reminder_id", r["id"]).execute().data
        if any(str(l.get("scheduled_for", "")).startswith(today_prefix) for l in logs):
            continue
        due.append(r)
    return due


def run_due_reminders() -> int:
    from voice.twilio_routes import place_outbound_call

    count = 0
    for r in due_reminders():
        try:
            sid = place_outbound_call(r["user_id"], "reminder", reminder_id=r["id"])
            db.get_client().table("reminder_logs").insert(
                {"reminder_id": r["id"], "scheduled_for": db.now_iso(), "call_sid": sid or None, "attempt": 1}
            ).execute()
            if r.get("recurrence") == "once":
                db.get_client().table("reminders").update({"active": False}).eq("id", r["id"]).execute()
            count += 1
        except Exception:  # noqa: BLE001
            log.exception("reminder %s failed", r["id"])
    return count


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(run_due_reminders, "interval", seconds=60, id="due_reminders", max_instances=1)
    scheduler.start()
    log.info("scheduler started")
    return scheduler
