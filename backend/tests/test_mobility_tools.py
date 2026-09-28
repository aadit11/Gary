"""Rides on Udriver through the browser: policy on the destination, read-back, booking, family YES."""

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

import mcp_servers.mobility  # noqa: F401  (see test_orders_tools.py for why the module is fetched from sys.modules)
import mcp_servers.orders  # noqa: F401

from core import policy
from webhooks.sms import handle_reply

mobility = sys.modules["mcp_servers.mobility"]

HOME = "Geary Courtyard Apartments, 639 Geary Street"
NEW_PLACE = "Health System Pharmacy, 550 16th Street"

TRIP_PAGE = """[185] main ''
\t[329] heading 'Heading to Walgreens at Health System Pharmacy'
\t[330] button '8:12 PM'
\t[345] heading 'Alvaro'
\t[346] heading '9L13XK'
\t[347] heading 'Toyota Prius'
\t[350] heading '4.99'
\t[370] image 'PickUp Location'
\t[373] heading 'Geary Courtyard Apartments'
\t[374] heading '639 Geary Street, San Francisco'
\t[376] image 'search'
\t[379] heading 'Walgreens at Health System Pharmacy'
\t[380] heading '550 16th Street, San Francisco'
\t[385] heading '$ 13.30'
\t[388] button 'Cancel'
"""


class FakeJob:
    def __init__(self, status="done", result_text="DONE: ride booked", final_text="", id="job-1"):
        self.status = status
        self.result_text = result_text
        self.final_text = final_text
        self.id = id


class FakeBrowserRunner:
    def __init__(self):
        self.submitted = []
        self._last_on_done = None

    def submit(self, site, goal, user_id, on_done=None, on_progress=None, **kw):
        self.submitted.append({"site": site, "goal": goal, "user_id": user_id, **kw})
        self._last_on_done = on_done

    def cancel_for_user(self, user_id):
        pass

    def finish(self, job=None):
        self._last_on_done(job or FakeJob())


@pytest.fixture
def fake_runner(monkeypatch):
    runner = FakeBrowserRunner()

    class FakeAppState:
        browser_runner = runner

    class FakeApp:
        state = FakeAppState()

    class FakeMainModule:
        app = FakeApp()

    monkeypatch.setitem(sys.modules, "main", FakeMainModule())
    return runner


@pytest.fixture
def profile(fake_db, demo):
    """The caregiver profile with a saved home and two saved places."""
    return fake_db.table("emails").insert({
        "user_id": demo["user_id"],
        "gmail_id": "caregiver-profile",
        "sender": "caregiver",
        "subject": "Care profile",
        "classification": "other",
        "extracted": {"connectors": {"uber": {"home": HOME, "hospital": "Springfield General",
                                                "places": [{"label": "Doctor or hospital", "address": "Springfield General"},
                                                           {"label": "Dr. Patel", "address": "400 Medical Plaza, Springfield"}]}}},
    }).execute().data[0]


def _heard(monkeypatch):
    lines = []
    monkeypatch.setattr(mobility, "_speak_into_call", lambda loop, uid, msg, behavior="queue": lines.append(msg))
    return lines


def _out(s: str) -> dict:
    out = json.loads(s)
    assert "{" not in out["say"]
    return out


# --- policy: saved places ------------------------------------------------------

def test_known_place_matches_saved_places(demo, profile):
    uid = demo["user_id"]
    assert policy.is_known_place(uid, "Springfield General")
    assert policy.is_known_place(uid, "the Springfield General hospital")
    assert policy.is_known_place(uid, "400 Medical Plaza, Springfield")
    assert policy.is_known_place(uid, "12 Oak Lane")  # the user's address
    assert not policy.is_known_place(uid, NEW_PLACE)
    assert not policy.is_known_place(uid, "")


def test_ride_policy_needs_family_for_a_new_place(demo, profile):
    ok = policy.check(kind="ride", payee="Springfield General", amount=0, user_id=demo["user_id"])
    held = policy.check(kind="ride", payee=NEW_PLACE, amount=0, user_id=demo["user_id"])
    assert not ok.needs_approval
    assert held.needs_approval and "new place" in held.reason and held.family_name == "David"


# --- prepare / confirm ------------------------------------------------------------

def test_prepare_ride_to_saved_place_reads_back(demo, profile):
    out = _out(mobility.prepare_ride(demo["user_id"], "Springfield General"))
    assert out["action_id"] and out["say"] == "That's a ride from home to Springfield General, leaving as soon as a driver is free. Should I book it?"
    assert out["data"]["outcome"] == "ready"


def test_prepare_ride_to_new_place_asks_family(demo, profile, fake_db):
    out = _out(mobility.prepare_ride(demo["user_id"], NEW_PLACE))
    assert out["data"]["outcome"] == "needs_approval" and "David" in out["say"] and not out.get("action_id")
    rows = fake_db.table("approvals").select("*").eq("user_id", demo["user_id"]).execute().data
    assert rows[-1]["action"] == "book_ride" and rows[-1]["payload"]["destination"] == NEW_PLACE and rows[-1]["payload"]["pickup"] == HOME
    assert "looking for a driver" in rows[-1]["payload"]["done_say"] and "booked" not in rows[-1]["payload"]["done_say"]


def test_prepare_ride_without_destination_asks(demo, profile):
    out = _out(mobility.prepare_ride(demo["user_id"], "  "))
    assert "Where" in out["say"] and not out.get("action_id")


def test_confirm_ride_books_in_browser_and_reports_driver(demo, profile, fake_db, fake_runner, monkeypatch):
    heard = _heard(monkeypatch)
    uid = demo["user_id"]
    prepared = _out(mobility.prepare_ride(uid, "Springfield General"))
    out = _out(mobility.confirm_ride(uid, prepared["action_id"]))
    assert "booking your ride" in out["say"]
    job = fake_runner.submitted[-1]
    assert job["site"] == "udriver" and HOME in job["goal"] and "Springfield General" in job["goal"] and "Request" in job["goal"]
    fake_runner.finish(FakeJob(status="done", final_text=TRIP_PAGE))
    rows = fake_db.table("rides").select("*").eq("user_id", uid).execute().data
    assert len(rows) == 1 and rows[0]["status"] == "booked" and rows[0]["driver"] == "Alvaro" and rows[0]["plate"] == "9L13XK"
    assert rows[0]["car"] == "Toyota Prius" and rows[0]["price"] == 13.30 and rows[0]["dropoff"] == "Springfield General"
    assert heard[-1] == "Your ride is booked. Alvaro is coming in a Toyota Prius, plate 9 L 1 3 X K. It's $13.30."
    # the pending action was consumed: a second yes is rejected
    again = _out(mobility.confirm_ride(uid, prepared["action_id"]))
    assert again["data"]["outcome"] == "error"


def test_confirm_ride_blank_action_id_uses_the_last_read_back(demo, profile, fake_runner):
    uid = demo["user_id"]
    mobility.prepare_ride(uid, "Springfield General")
    out = _out(mobility.confirm_ride(uid))
    assert "booking your ride" in out["say"] and fake_runner.submitted[-1]["site"] == "udriver"


def test_confirm_ride_rejects_unknown_action_id(demo, profile, fake_runner):
    out = _out(mobility.confirm_ride(demo["user_id"], "not-real"))
    assert out["data"]["outcome"] == "error" and not fake_runner.submitted


def test_ride_failure_is_reported(demo, profile, fake_db, fake_runner, monkeypatch):
    heard = _heard(monkeypatch)
    uid = demo["user_id"]
    mobility.prepare_ride(uid, "Springfield General")
    mobility.confirm_ride(uid)
    fake_runner.finish(FakeJob(status="infeasible", result_text="could not"))
    rows = fake_db.table("rides").select("*").eq("user_id", uid).execute().data
    assert rows[-1]["status"] == "failed" and "trouble" in heard[-1]


def test_family_yes_books_the_held_ride(demo, profile, fake_db, fake_runner, monkeypatch):
    heard = _heard(monkeypatch)
    uid = demo["user_id"]
    mobility.prepare_ride(uid, NEW_PLACE)
    reply = handle_reply(demo["family_phone"], "YES")
    assert "Booking the ride" in reply
    job = fake_runner.submitted[-1]
    assert job["site"] == "udriver" and NEW_PLACE in job["goal"] and HOME in job["goal"]
    fake_runner.finish(FakeJob(status="done", final_text=TRIP_PAGE))
    rows = fake_db.table("rides").select("*").eq("user_id", uid).execute().data
    assert rows[-1]["status"] == "booked" and rows[-1]["driver"] == "Alvaro"
    assert "Alvaro" in heard[-1]


def test_family_no_books_nothing(demo, profile, fake_runner):
    mobility.prepare_ride(demo["user_id"], NEW_PLACE)
    reply = handle_reply(demo["family_phone"], "NO")
    assert "won't" in reply and not fake_runner.submitted


# --- status and appointments ---------------------------------------------------------

def test_get_ride_status(demo, profile, fake_db, fake_runner, monkeypatch):
    _heard(monkeypatch)
    uid = demo["user_id"]
    assert "don't have a ride" in _out(mobility.get_ride_status(uid))["say"]
    mobility.prepare_ride(uid, "Springfield General")
    mobility.confirm_ride(uid)
    fake_runner.finish(FakeJob(status="done", final_text=TRIP_PAGE))
    say = _out(mobility.get_ride_status(uid))["say"]
    assert "Alvaro" in say and "Toyota Prius" in say and "Springfield General" in say


def test_suggest_ride_for_appointment(demo, fake_db):
    uid = demo["user_id"]
    assert "don't see" in _out(mobility.suggest_ride_for_appointment(uid))["say"]
    starts = datetime.now(timezone.utc) + timedelta(hours=1)
    fake_db.table("emails").insert({
        "user_id": uid, "gmail_id": "appt-1", "sender": "clinic@example.com", "subject": "Appointment reminder — Dr. Patel",
        "classification": "appointment", "extracted": {"title": "Dr. Patel", "starts_at": starts.isoformat(), "location": NEW_PLACE + "."},
    }).execute()
    out = _out(mobility.suggest_ride_for_appointment(uid))
    assert out["say"].startswith("Your appointment with Dr. Patel is ") and NEW_PLACE in out["say"] and out["say"].endswith("Want me to book you a ride there?")
    assert out["data"]["destination"] == NEW_PLACE


def test_ride_progress_lines_are_spoken_once_in_order(demo, monkeypatch):
    heard = _heard(monkeypatch)
    clock = {"t": 1000.0}
    monkeypatch.setattr(mobility.time, "monotonic", lambda: clock["t"])
    on_progress = mobility._ride_progress(None, demo["user_id"])
    on_progress("step"); assert heard == []            # right away: nothing yet
    clock["t"] += 6; on_progress("step"); on_progress("step")
    assert heard == [mobility.RIDE_PROGRESS[0][1]]     # first line once, not twice
    clock["t"] += 60; on_progress("step")
    assert heard == [line for _, line in mobility.RIDE_PROGRESS]  # the rest, in order, each once


def test_family_yes_sentence_does_not_claim_a_booking(demo, profile, fake_runner, monkeypatch):
    from voice.injection import approval_sentence
    from core import approvals

    mobility.prepare_ride(demo["user_id"], NEW_PLACE)
    aid = approvals.latest_pending_for_phone(demo["family_phone"]).id
    handle_reply(demo["family_phone"], "YES")
    resolved = approvals.get(aid)
    resolved.outcome = "executed"
    line = approval_sentence(resolved)
    assert line.startswith("Good news, your son David said yes.") and "looking for a driver" in line
    assert "booked" not in line.lower() and "on the way" not in line.lower()
    assert all("booked" not in text.lower() for _, text in mobility.RIDE_PROGRESS)
