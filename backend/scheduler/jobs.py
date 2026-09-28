"""Due reminders, one retry, a caregiver alert, and same-day appointment calls.

Every minute: for each active reminder whose time_of_day (in the user's timezone) matches the
current minute and that has no reminder_logs row for today, log it and place the call.
A weekly reminder only fires on the weekday saved in the caregiver profile.
A reminder that is still unanswered after 15 minutes is called once more. If it is still
unconfirmed after that, the caregiver gets one message. Appointments are called at 9:00 local.
Regular bills also text the caregiver at 9:00 local. They are reminders only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import activity, db, notify
from core.speech import date_str

log = logging.getLogger(__name__)

RETRY_AFTER = timedelta(minutes=15)
ALERT_AFTER = timedelta(minutes=30)
PROFILE_GMAIL_ID = "caregiver-profile"
EXPENSE_LABELS = {
    "rent": "rent",
    "utilities": "utilities",
    "groceries": "groceries",
    "pharmacy": "pharmacy",
    "phone": "phone",
    "insurance": "insurance",
}


def _user_tz(user_id: str, cache: dict) -> str:
    if user_id not in cache:
        rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
        cache[user_id] = (rows[0].get("timezone") if rows else None) or "America/New_York"
    return cache[user_id]


def _care_profiles(client) -> dict[str, dict]:
    rows = client.table("emails").select("*").eq("gmail_id", PROFILE_GMAIL_ID).execute().data
    found: dict[str, dict] = {}
    for row in rows:
        extra = row.get("extracted") or {}
        if isinstance(extra, dict):
            found[row["user_id"]] = extra
    return found


def due_reminders(now_utc: datetime | None = None) -> list[dict]:
    """Active reminders due this minute (user-local) without a log entry today."""
    now_utc = now_utc or datetime.now(timezone.utc)
    client = db.get_client()
    reminders = client.table("reminders").select("*").eq("active", True).execute().data
    profiles = _care_profiles(client)
    tz_cache: dict = {}
    due = []
    for r in reminders:
        local = now_utc.astimezone(ZoneInfo(_user_tz(r["user_id"], tz_cache)))
        hhmm = str(r.get("time_of_day", ""))[:5]
        if hhmm != local.strftime("%H:%M"):
            continue
        if r.get("recurrence") == "weekdays" and local.weekday() >= 5:
            continue
        if r.get("recurrence") == "weekly":
            days = (profiles.get(r["user_id"]) or {}).get("weekly_days") or {}
            day = days.get(r["id"]) if isinstance(days, dict) else None
            try:
                chosen = int(day) if day is not None else None
            except (TypeError, ValueError):
                chosen = None
            if chosen is None or chosen != local.weekday():
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


def _parse_time(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _first_name(user_id: str) -> str:
    rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
    if not rows:
        return "They"
    return (rows[0].get("name") or "They").split(" ")[0]


def run_reminder_followups(now_utc: datetime | None = None) -> int:
    """Retry an unanswered reminder once, then tell the caregiver if it stays unconfirmed."""
    from voice.twilio_routes import place_outbound_call

    now_utc = now_utc or datetime.now(timezone.utc)
    client = db.get_client()
    count = 0
    for row in client.table("reminder_logs").select("*").execute().data:
        if row.get("confirmed") or row.get("family_alerted"):
            continue
        scheduled = _parse_time(row.get("scheduled_for"))
        if scheduled is None:
            continue
        age = now_utc - scheduled
        attempt = int(row.get("attempt") or 1)
        answered = bool(row.get("answered"))
        reminder_rows = client.table("reminders").select("*").eq("id", row["reminder_id"]).limit(1).execute().data
        if not reminder_rows:
            continue
        reminder = reminder_rows[0]
        if attempt == 1 and not answered and age >= RETRY_AFTER:
            try:
                place_outbound_call(reminder["user_id"], "reminder", reminder_id=reminder["id"])
                client.table("reminder_logs").update({"attempt": 2}).eq("id", row["id"]).execute()
                count += 1
            except Exception:  # noqa: BLE001
                log.exception("reminder retry %s failed", row["id"])
            continue
        should_alert = (attempt >= 2 and age >= ALERT_AFTER) or (answered and age >= RETRY_AFTER)
        if not should_alert:
            continue
        name = _first_name(reminder["user_id"])
        notify.notify_family(reminder["user_id"], f"{name} did not confirm: {reminder['message']}")
        client.table("reminder_logs").update({"family_alerted": True}).eq("id", row["id"]).execute()
        activity.log_event(
            reminder["user_id"],
            "reminder_unconfirmed",
            f"{name} did not confirm a reminder",
            {"reminder_id": reminder["id"], "category": "medication", "outcome": "unconfirmed"},
        )
        count += 1
    return count


def run_due_appointments(now_utc: datetime | None = None) -> int:
    """At 9:00 local, call about today's appointment and text the caregiver once."""
    from voice.twilio_routes import place_outbound_call

    now_utc = now_utc or datetime.now(timezone.utc)
    client = db.get_client()
    tz_cache: dict = {}
    count = 0
    emails = client.table("emails").select("*").eq("classification", "appointment").execute().data
    for email in emails:
        extra = email.get("extracted") or {}
        if not isinstance(extra, dict):
            continue
        starts = _parse_time(extra.get("starts_at"))
        if starts is None:
            continue
        tz = ZoneInfo(_user_tz(email["user_id"], tz_cache))
        local_now = now_utc.astimezone(tz)
        if local_now.strftime("%H:%M") != "09:00":
            continue
        if starts.astimezone(tz).date() != local_now.date():
            continue
        day = local_now.date().isoformat()
        prior = client.table("activity_log").select("*").eq("user_id", email["user_id"]).eq("kind", "appointment_reminded").execute().data
        if any((row.get("data") or {}).get("email_id") == email["id"] and (row.get("data") or {}).get("local_date") == day for row in prior):
            continue
        title = extra.get("title") or email.get("subject") or "an appointment"
        when = date_str(starts.astimezone(tz))
        note = f"{title} on {when}"
        if extra.get("location"):
            note += f" at {str(extra['location']).rstrip('.')}"
        try:
            place_outbound_call(email["user_id"], "appointment", note=note)
            name = _first_name(email["user_id"])
            notify.notify_family(email["user_id"], f"{name} has {note}.")
            activity.log_event(
                email["user_id"],
                "appointment_reminded",
                note,
                {"email_id": email["id"], "local_date": day, "category": "appointment", "outcome": "resolved"},
            )
            count += 1
        except Exception:  # noqa: BLE001
            log.exception("appointment reminder %s failed", email["id"])
    return count


def run_due_expenses(now_utc: datetime | None = None) -> int:
    """At 9:00 local, text the caregiver once about each regular bill due today."""
    now_utc = now_utc or datetime.now(timezone.utc)
    client = db.get_client()
    tz_cache: dict = {}
    count = 0
    for row in client.table("emails").select("*").eq("gmail_id", PROFILE_GMAIL_ID).execute().data:
        extra = row.get("extracted") or {}
        if not isinstance(extra, dict) or extra.get("notify_expenses") is False:
            continue
        tz = ZoneInfo(_user_tz(row["user_id"], tz_cache))
        local_now = now_utc.astimezone(tz)
        if local_now.strftime("%H:%M") != "09:00":
            continue
        day = local_now.date().isoformat()
        prior = client.table("activity_log").select("*").eq("user_id", row["user_id"]).eq("kind", "expense_reminded").execute().data
        name = _first_name(row["user_id"])
        for expense in extra.get("expenses") or []:
            if not isinstance(expense, dict) or not expense.get("active"):
                continue
            try:
                due_day = int(expense.get("due_day"))
            except (TypeError, ValueError):
                continue
            if due_day != local_now.day:
                continue
            category = str(expense.get("category") or "")
            if any((item.get("data") or {}).get("category") == category and (item.get("data") or {}).get("local_date") == day for item in prior):
                continue
            label = EXPENSE_LABELS.get(category, category.replace("_", " "))
            message = f"{name}'s {label} is due today. This is a reminder only."
            notify.notify_family(row["user_id"], message)
            activity.log_event(
                row["user_id"],
                "expense_reminded",
                message,
                {"category": category, "local_date": day, "outcome": "reminder_only"},
            )
            count += 1
    return count


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(run_due_reminders, "interval", seconds=60, id="due_reminders", max_instances=1)
    scheduler.add_job(run_reminder_followups, "interval", seconds=60, id="reminder_followups", max_instances=1)
    scheduler.add_job(run_due_appointments, "interval", seconds=60, id="due_appointments", max_instances=1)
    scheduler.add_job(run_due_expenses, "interval", seconds=60, id="due_expenses", max_instances=1)
    scheduler.start()
    log.info("scheduler started")
    return scheduler
