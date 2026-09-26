"""Vertical 1: briefing, appointments, medication confirmation, family summaries, caregiver transfer.

Money is never moved here. A family summary is a note, not a payment.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from core import activity, db, notify, pending
from core.pending import PendingActionError
from core.speech import date_str, money_str, speak

checkins = FastMCP("checkins", instructions="Daily check-ins, reminders, and the morning briefing.")

_SECRET = re.compile(r"\d{5,}")


def _user(user_id: str) -> dict:
    rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
    return rows[0] if rows else {"name": "there", "timezone": "America/New_York"}


def _first_name(user_id: str) -> str:
    return (_user(user_id).get("name") or "they").split(" ")[0]


def _today(user_id: str):
    tz = ZoneInfo(_user(user_id).get("timezone") or "America/New_York")
    return datetime.now(tz).date(), tz


def _extracted(row: dict) -> dict:
    raw = row.get("extracted") or {}
    return raw if isinstance(raw, dict) else {}


def _appointments(user_id: str) -> list[dict]:
    rows = (
        db.get_client()
        .table("emails")
        .select("*")
        .eq("user_id", user_id)
        .eq("classification", "appointment")
        .execute()
        .data
    )
    found = []
    for row in rows:
        extra = _extracted(row)
        found.append(
            {
                "id": row["id"],
                "title": extra.get("title") or row.get("subject") or "an appointment",
                "starts_at": extra.get("starts_at"),
            }
        )
    found.sort(key=lambda item: str(item.get("starts_at") or ""))
    return found


def _local_date(starts_at: str | None, tz: ZoneInfo):
    if not starts_at:
        return None
    try:
        value = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz).date()


def _bills_due(user_id: str) -> list[dict]:
    return (
        db.get_client()
        .table("bills")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "due")
        .order("due_date")
        .execute()
        .data
    )


def _open_reminder_log(user_id: str) -> dict | None:
    today, _tz = _today(user_id)
    reminders = db.get_client().table("reminders").select("*").eq("user_id", user_id).execute().data
    ids = {row["id"] for row in reminders}
    logs = db.get_client().table("reminder_logs").select("*").execute().data
    open_logs = [
        row
        for row in logs
        if row.get("reminder_id") in ids
        and str(row.get("scheduled_for", "")).startswith(today.isoformat())
        and not row.get("confirmed")
    ]
    if not open_logs:
        return None
    open_logs.sort(key=lambda row: str(row.get("scheduled_for") or ""))
    return open_logs[-1]


def _reminder_message(reminder_id: str) -> str:
    rows = db.get_client().table("reminders").select("*").eq("id", reminder_id).limit(1).execute().data
    return rows[0]["message"] if rows else "their reminder"


def _approver(user_id: str) -> dict | None:
    contacts = notify.family_contacts(user_id, approvers_only=True)
    return contacts[0] if contacts else None


@checkins.tool()
def get_daily_briefing(user_id: str) -> str:
    """Tell the user about today's bills, appointments, and any reminder still open."""
    try:
        today, tz = _today(user_id)
        tomorrow = today + timedelta(days=1)
        items: list[str] = []
        for appt in _appointments(user_id):
            when = _local_date(appt.get("starts_at"), tz)
            if when in (today, tomorrow):
                items.append(f"{appt['title']} on {date_str(appt.get('starts_at'))}")
                break
        bills = _bills_due(user_id)
        if bills:
            bill = bills[0]
            items.append(f"{money_str(bill['amount'])} to {bill['payee']} due {date_str(bill.get('due_date'))}")
        open_log = _open_reminder_log(user_id)
        if open_log:
            items.append(_reminder_message(open_log["reminder_id"]))
    except Exception:  # noqa: BLE001
        return speak("I couldn't check your day just now. Want me to try again?", data={"category": "briefing", "outcome": "error"})
    items = items[:3]
    if not items:
        say = "You have a clear day. Nothing coming up, and no bills I need to mention."
    elif len(items) == 1:
        say = f"Here is the one thing for you: {items[0]}."
    else:
        say = f"Here are a few things. {items[0]}. Also, {items[1]}."
        if len(items) == 3:
            say = f"{say} And {items[2]}."
    return speak(say, data={"category": "briefing", "outcome": "resolved"})


@checkins.tool()
def get_upcoming_appointments(user_id: str) -> str:
    """Call this immediately when the person asks what appointments they have or what is coming up."""
    try:
        today, tz = _today(user_id)
        upcoming = []
        for appt in _appointments(user_id):
            when = _local_date(appt.get("starts_at"), tz)
            if when is not None and when >= today:
                upcoming.append(appt)
    except Exception:  # noqa: BLE001
        return speak("I couldn't check your appointments just now. Want me to try again?", data={"category": "appointment", "outcome": "error"})
    if not upcoming:
        return speak("I don't see any appointments coming up.", data={"category": "appointment", "outcome": "resolved"})
    first = upcoming[0]
    say = f"You have {first['title']} on {date_str(first.get('starts_at'))}."
    if len(upcoming) > 1:
        say = f"{say} I can tell you about another one after this."
    return speak(say, data={"category": "appointment", "outcome": "resolved"})


@checkins.tool()
def confirm_reminder(user_id: str) -> str:
    """Mark today's reminder confirmed after the person clearly says they have done it or will do it now."""
    try:
        log_row = _open_reminder_log(user_id)
        if not log_row:
            return speak("I don't have a reminder waiting to confirm.", data={"category": "medication", "outcome": "resolved"})
        db.get_client().table("reminder_logs").update({"confirmed": True, "answered": True}).eq("id", log_row["id"]).execute()
        message = _reminder_message(log_row["reminder_id"])
        name = _first_name(user_id)
        notify.notify_family(user_id, f"{name} confirmed: {message}")
        activity.log_event(user_id, "reminder_confirmed", f"{name} confirmed a reminder", {"reminder_id": log_row["reminder_id"], "category": "medication"})
    except Exception:  # noqa: BLE001
        return speak("I couldn't mark that just now. Want me to try again?", data={"category": "medication", "outcome": "error"})
    return speak("I'll let your family know you confirmed.", data={"category": "medication", "outcome": "resolved"})


@checkins.tool()
def summarize_for_family(user_id: str, summary: str) -> str:
    """Send the caregiver one or two sentences about money or a request Gary will not handle. Never include account numbers."""
    text = " ".join(summary.split())
    if _SECRET.search(text):
        return speak(
            "Please don't tell me numbers like that. I don't need them, and I won't ask.",
            data={"category": "safety_stop", "outcome": "safety_stop"},
        )
    if len(text) > 240:
        text = text[:240].rsplit(" ", 1)[0]
    try:
        name = _first_name(user_id)
        notify.notify_family(user_id, f"{name}: {text}")
        activity.log_event(user_id, "family_summary", text, {"category": "money_screened"})
    except Exception:  # noqa: BLE001
        return speak("I couldn't reach your family just now. Want me to try again?", data={"category": "money_screened", "outcome": "error"})
    return speak("I sent your family a short note about that. I won't do anything with money from this call.", data={"category": "money_screened", "outcome": "summarized_to_family"})


@checkins.tool()
def prepare_caregiver_transfer(user_id: str, reason: str) -> str:
    """Offer to connect the call to the caregiver, and wait for a clear yes before transferring."""
    try:
        contact = _approver(user_id)
        family_name = contact["name"] if contact else "your family"
        action_id = pending.create("caregiver_transfer", user_id, reason=reason, family_name=family_name)
    except Exception:  # noqa: BLE001
        return speak("I couldn't set that up just now. Want me to try again?", data={"category": "caregiver_transfer", "outcome": "error"})
    return speak(
        f"I can connect you with {family_name} now. Should I?",
        action_id=action_id,
        data={"category": "caregiver_transfer"},
    )


@checkins.tool()
def confirm_caregiver_transfer(user_id: str, action_id: str) -> str:
    """Connect the call to the caregiver only after prepare_caregiver_transfer and a clear yes."""
    try:
        pending.consume(action_id, "caregiver_transfer", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "caregiver_transfer", "outcome": "error"})
    contact = _approver(user_id)
    if not contact or not notify._can_message(contact.get("phone") or ""):
        name = contact["name"] if contact else "your family"
        notify.notify_family(user_id, f"{_first_name(user_id)} asked to talk with you.")
        return speak(f"I left a note for {name}.", data={"category": "caregiver_transfer", "outcome": "transfer_skipped", "transfer": False})
    return speak(
        f"I'm connecting you with {contact['name']} now.",
        data={"category": "caregiver_transfer", "outcome": "transferred", "transfer": True, "phone": contact["phone"]},
    )
