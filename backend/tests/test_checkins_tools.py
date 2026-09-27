import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mcp_servers.checkins import (
    confirm_caregiver_transfer,
    confirm_reminder,
    get_daily_briefing,
    get_upcoming_appointments,
    prepare_caregiver_transfer,
    summarize_for_family,
)
from scheduler.jobs import run_due_appointments, run_reminder_followups


def _say(raw: str) -> dict:
    return json.loads(raw)


def _appointment(fake_db, user_id: str, when: datetime, title: str = "doctor's visit") -> dict:
    return fake_db.table("emails").insert(
        {
            "user_id": user_id,
            "gmail_id": "appt-1",
            "sender": "clinic@example.com",
            "subject": title,
            "classification": "appointment",
            "extracted": {"title": title, "starts_at": when.isoformat()},
        }
    ).execute().data[0]


def test_briefing_mentions_bill_and_appointment(demo, fake_db):
    when = datetime.now(ZoneInfo("America/New_York")) + timedelta(days=1)
    when = when.replace(hour=14, minute=0, second=0, microsecond=0)
    _appointment(fake_db, demo["user_id"], when)
    out = _say(get_daily_briefing(demo["user_id"]))
    assert "City Electric" in out["say"] and "$84.20" in out["say"]
    assert "doctor's visit" in out["say"]
    assert out["data"]["category"] == "briefing"
    assert "{" not in out["say"]


def test_upcoming_appointment_wording(demo, fake_db):
    when = datetime.now(ZoneInfo("America/New_York")) + timedelta(days=1)
    when = when.replace(hour=14, minute=0, second=0, microsecond=0)
    _appointment(fake_db, demo["user_id"], when)
    out = _say(get_upcoming_appointments(demo["user_id"]))
    assert "doctor's visit" in out["say"] and "2 PM" in out["say"]
    assert out["data"]["outcome"] == "resolved"


def test_confirm_reminder_notifies_family(demo, fake_db, monkeypatch):
    sent = []
    monkeypatch.setattr("core.notify.notify_family", lambda *args, **kwargs: sent.append(args) or ["sid"])
    reminder = fake_db.table("reminders").insert(
        {"user_id": demo["user_id"], "message": "Take your morning pill.", "time_of_day": "08:00", "active": True}
    ).execute().data[0]
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    fake_db.table("reminder_logs").insert(
        {"reminder_id": reminder["id"], "scheduled_for": f"{today}T12:00:00+00:00", "attempt": 1}
    ).execute()
    out = _say(confirm_reminder(demo["user_id"]))
    assert out["data"]["category"] == "medication"
    assert "family" in out["say"]
    assert sent and "confirmed" in sent[0][1]
    assert fake_db.table("reminder_logs").select("*").execute().data[0]["confirmed"] is True


def test_transfer_rejected_without_pending_id(demo):
    out = _say(confirm_caregiver_transfer(demo["user_id"], ""))
    assert out["data"]["outcome"] == "error"
    assert "confirm" in out["say"]


def test_transfer_skipped_for_fictional_number(demo):
    prepared = _say(prepare_caregiver_transfer(demo["user_id"], "needs help with the sink"))
    out = _say(confirm_caregiver_transfer(demo["user_id"], prepared["action_id"]))
    assert out["data"]["outcome"] == "transfer_skipped"
    assert out["data"]["transfer"] is False
    assert "note" in out["say"]


def test_summary_refuses_long_digit_strings(demo):
    out = _say(summarize_for_family(demo["user_id"], "My card is 4111111111111111"))
    assert out["data"]["outcome"] == "safety_stop"
    assert "4111" not in out["say"]


def test_missed_reminder_retries_once_then_alerts_once(demo, fake_db, monkeypatch):
    calls = []
    alerts = []
    monkeypatch.setattr("voice.twilio_routes.place_outbound_call", lambda *args, **kwargs: calls.append(args) or "CA1")
    monkeypatch.setattr("scheduler.jobs.notify.notify_family", lambda *args, **kwargs: alerts.append(args) or [])
    reminder = fake_db.table("reminders").insert(
        {"user_id": demo["user_id"], "message": "Take your morning pill.", "time_of_day": "08:00", "active": True}
    ).execute().data[0]
    scheduled = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    fake_db.table("reminder_logs").insert(
        {"reminder_id": reminder["id"], "scheduled_for": scheduled, "attempt": 1, "answered": False, "confirmed": False, "family_alerted": False}
    ).execute()
    assert run_reminder_followups() == 1
    assert len(calls) == 1 and alerts == []
    assert fake_db.table("reminder_logs").select("*").execute().data[0]["attempt"] == 2
    assert run_reminder_followups() == 1
    assert len(alerts) == 1 and "did not confirm" in alerts[0][1]
    assert fake_db.table("reminder_logs").select("*").execute().data[0]["family_alerted"] is True
    assert run_reminder_followups() == 0
    assert len(alerts) == 1 and len(calls) == 1


def test_appointment_reminder_once_at_nine(demo, fake_db, monkeypatch):
    calls = []
    notes = []
    monkeypatch.setattr("voice.twilio_routes.place_outbound_call", lambda *args, **kwargs: calls.append((args, kwargs)) or "CA9")
    monkeypatch.setattr("scheduler.jobs.notify.notify_family", lambda *args, **kwargs: notes.append(args) or [])
    starts = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
    email = _appointment(fake_db, demo["user_id"], starts)
    nine = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    assert run_due_appointments(nine) == 1
    assert calls[0][0][1] == "appointment"
    assert "doctor's visit" in calls[0][1]["note"]
    assert notes and "doctor's visit" in notes[0][1]
    assert run_due_appointments(nine) == 0
    assert len(calls) == 1
    logged = fake_db.table("activity_log").select("*").eq("kind", "appointment_reminded").execute().data
    assert logged[0]["data"]["email_id"] == email["id"]
