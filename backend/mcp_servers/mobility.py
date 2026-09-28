"""Vertical 4 (Person 4): prepare_ride, confirm_ride, get_ride_status, suggest_ride_for_appointment.

Rides are booked on the Udriver clone by the browser agent; there is no API. Same shape as the
other verticals (prepare -> confirm), with the family loop built in:
  - prepare_ride runs policy.check(kind="ride") on the destination. A place the family has not
    saved (the profile's home and saved places) needs their okay by text (invariants 1 and 3);
    a saved place gets a pending action and a read-back (invariant 2).
  - confirm_ride consumes the pending action and starts the browser job: pickup, destination,
    See prices, Request. When a driver is assigned (about 30 s) the driver's name, car, plate,
    and price are read off the trip page, recorded in `rides`, texted to the family, and spoken
    into the live call.
  - A family YES on a held ride books it the same way (ACTION_EXECUTORS["book_ride"]).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from browser_agent.udriver import parse_trip, spoken_plate, trip_booked
from core import activity, approvals, db, notify, pending, policy
from core.pending import PendingActionError
from core.speech import date_str, money_str, speak
from mcp_servers.orders import _call_loop, _caller_name, _runner, _speak_into_call
from webhooks.sms import ACTION_EXECUTORS

log = logging.getLogger(__name__)

mobility = FastMCP("mobility", instructions="Ride booking and ride status.")

PROFILE_GMAIL_ID = "caregiver-profile"
_last_action: dict[str, str] = {}  # user id -> the ride action id read back most recently


def _user(user_id: str) -> dict:
    rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
    return rows[0] if rows else {}


def _tz(user_id: str) -> ZoneInfo:
    return ZoneInfo(_user(user_id).get("timezone") or "America/New_York")


def _home(user_id: str) -> str:
    """Where rides start: the profile's saved home, else the user's address."""
    try:
        rows = db.get_client().table("emails").select("*").eq("user_id", user_id).eq("gmail_id", PROFILE_GMAIL_ID).limit(1).execute().data
        uber = (((rows[0].get("extracted") or {}).get("connectors") or {}).get("uber") or {}) if rows else {}
        if uber.get("home"):
            return str(uber["home"])
    except Exception:  # noqa: BLE001
        log.exception("could not read the saved home for %s", user_id)
    return str(_user(user_id).get("address") or "home")


def _next_appointment(user_id: str) -> Optional[dict]:
    """The soonest appointment that has not passed (an hour of grace), with its location."""
    rows = db.get_client().table("emails").select("*").eq("user_id", user_id).eq("classification", "appointment").execute().data
    now = datetime.now(timezone.utc)
    found = []
    for row in rows:
        extra = row.get("extracted") or {}
        if not isinstance(extra, dict) or not extra.get("starts_at"):
            continue
        try:
            starts = datetime.fromisoformat(str(extra["starts_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=timezone.utc)
        if starts < now - timedelta(hours=1):
            continue
        found.append({"title": extra.get("title") or row.get("subject") or "an appointment", "starts": starts,
                      "location": str(extra.get("location") or "").strip().rstrip(".")})
    found.sort(key=lambda a: a["starts"])
    return found[0] if found else None


def _search_term(place: str) -> str:
    """What to type into Udriver's search box: it matches on the place name, so drop the street part."""
    return (place or "").split(",")[0].strip() or place


# Spoken into the call the moment the family says yes (voice/injection.py reads payload.done_say),
# and by confirm_ride on a spoken yes. The progress lines below follow it; none repeats it.
FAMILY_YES_SAY = "I'm looking for a driver right now. We should have one in a few minutes."

# What the caller hears while the browser books the ride: (seconds since the job started, line).
# Each line is spoken once, in order, and only when the booking has run that long.
RIDE_PROGRESS = [
    (18, "Still looking for a driver. Just a moment more."),
    (36, "Almost there, thanks for your patience."),
    (54, "Still searching. I'll tell you the moment a driver is set."),
]


def _ride_progress(call_loop, user_id: str):
    """Speak each RIDE_PROGRESS line once, in order, as the booking passes that many seconds."""
    started = time.monotonic()
    spoken = {"n": 0}

    def on_progress(_reason: str) -> None:
        from voice.bridge import ACTIVE_SESSIONS

        session = ACTIVE_SESSIONS.get(user_id)
        if session is not None and getattr(session, "order_updates_paused", False):
            return
        elapsed = time.monotonic() - started
        while spoken["n"] < len(RIDE_PROGRESS) and elapsed >= RIDE_PROGRESS[spoken["n"]][0]:
            _speak_into_call(call_loop, user_id, RIDE_PROGRESS[spoken["n"]][1], behavior="queue")
            spoken["n"] += 1

    return on_progress


def _title_phrase(title: str) -> str:
    title = (title or "an appointment").strip()
    return f"appointment with {title}" if title.lower().startswith("dr") else title


# ---------------------------------------------------------------------------

@mobility.tool()
def suggest_ride_for_appointment(user_id: str) -> str:
    """Call this when the caller has an appointment coming up and may need a ride there; it says where and when and offers to book one."""
    try:
        appt = _next_appointment(user_id)
    except Exception:  # noqa: BLE001
        log.exception("could not read appointments for %s", user_id)
        return speak("I couldn't check your appointments just now. Want me to try again?", data={"category": "ride", "outcome": "error"})
    if not appt:
        return speak("I don't see an appointment coming up that you'd need a ride for.", data={"category": "ride", "outcome": "resolved"})
    when = date_str(appt["starts"].astimezone(_tz(user_id)))
    where = f" at {appt['location']}" if appt["location"] else ""
    say = f"Your {_title_phrase(appt['title'])} is {when}{where}. Want me to book you a ride there?"
    return speak(say, data={"category": "ride", "outcome": "resolved", "destination": appt["location"], "starts_at": appt["starts"].isoformat()})


@mobility.tool()
def prepare_ride(user_id: str, destination: str, pickup: str = "") -> str:
    """Prepare a ride from home to the place the caller named, such as the appointment place, and return the details to read back. A place the family has not saved is checked with them first."""
    destination = (destination or "").strip().rstrip(".")
    if not destination:
        return speak("Where would you like to go?", data={"category": "ride", "outcome": "resolved"})
    pickup = (pickup or "").strip() or _home(user_id)
    decision = policy.check(kind="ride", payee=destination, amount=0, user_id=user_id)
    payload = {"pickup": pickup, "destination": destination, "summary": f"book a ride from home to {destination}", "done_say": FAMILY_YES_SAY}
    if decision.needs_approval:
        approvals.request(user_id=user_id, action="book_ride", payload=payload, reason=decision.reason,
                          summary=f"a ride from home to {destination}")
        return speak(
            f"That's a new place, so I'd like to check with {decision.family_name} before booking the ride. I'm texting them now.",
            data={"category": "ride", "outcome": "needs_approval", "destination": destination},
        )
    action_id = pending.create("book_ride", user_id, **payload)
    _last_action[user_id] = action_id
    return speak(
        f"That's a ride from home to {destination}, leaving as soon as a driver is free. Should I book it?",
        action_id=action_id,
        data={"category": "ride", "outcome": "ready", "destination": destination},
    )


def _start_ride(user_id: str, payload: dict, call_loop) -> None:
    """Book on Udriver in the browser and report the driver when one is assigned."""
    pickup = str(payload.get("pickup") or _home(user_id))
    destination = str(payload.get("destination") or "the appointment")
    caller = _caller_name(user_id)
    notify.notify_family(user_id, f"{caller} asked for a ride from home to {destination}. Booking it now.")
    activity.log_event(user_id, "ride_requested", f"Booking a ride to {destination}.", {"category": "ride", "outcome": "booking"})
    goal = (
        f"Book a ride on Udriver from {pickup} to {destination}. "
        f"Type exactly \"{_search_term(pickup)}\" in 'Enter Location' and pick the suggestion that matches, "
        f"then type exactly \"{_search_term(destination)}\" in 'Enter Destination' and pick the suggestion that matches. "
        "Click See prices, wait for the ride options to load, then click Request for the standard UdriverX ride. "
        "The ride is booked only when a driver is assigned and the page shows the driver's name, car, and plate. Do not invent a place."
    )

    def on_done(job) -> None:
        status = getattr(job, "status", "")
        if status == "cancelled":
            return
        trip = parse_trip(getattr(job, "final_text", "") or "")
        success = status == "done"
        details = trip if trip_booked(trip) else {}
        try:
            db.get_client().table("rides").insert({
                "user_id": user_id,
                "pickup": pickup,
                "dropoff": destination,
                "price": details.get("price") or None,
                "status": "booked" if success else "failed",
                "external_id": getattr(job, "id", "") or "udriver",
                "driver": details.get("driver") or None,
                "car": details.get("car") or None,
                "plate": details.get("plate") or None,
            }).execute()
        except Exception:  # noqa: BLE001
            log.exception("failed to record ride for %s", user_id)
        activity.log_event(
            user_id, "ride",
            f"Ride booked to {destination}" + (f": {details['driver']}, {details['car']}, plate {details['plate']}" if details else "")
            if success else f"Ride to {destination} failed",
            {"category": "ride", "outcome": "booked" if success else "error", **({"price": details.get("price")} if details else {})},
        )
        if success and details:
            family = f"Ride booked for {caller}: {details['driver']} in a {details['car']}, plate {details['plate']}, from home to {destination}."
            if details.get("price"):
                family += f" {money_str(details['price'])}."
            line = f"Your ride is booked. {details['driver']} is coming in a {details['car']}, plate {spoken_plate(details['plate'])}."
            if details.get("price"):
                line += f" It's {money_str(details['price'])}."
        elif success:
            family = f"Ride booked for {caller} from home to {destination}."
            line = f"Your ride is booked. A driver is on the way to take you to {destination}."
        else:
            family = f"Sorry, the ride to {destination} didn't go through."
            line = f"I had trouble booking the ride to {destination}. Want me to try again?"
        notify.notify_family(user_id, family)
        _speak_into_call(call_loop, user_id, line, behavior="queue")

    _runner().submit(
        site="udriver", goal=goal, user_id=user_id, replay=False, page_name=destination, on_done=on_done,
        on_progress=_ride_progress(call_loop, user_id),
    )


@mobility.tool()
def confirm_ride(user_id: str, action_id: str = "") -> str:
    """Book the ride that was read back, after the caller clearly says yes. The action id may be left blank."""
    action_id = (action_id or "").strip() or _last_action.get(user_id, "")
    try:
        payload = pending.consume(action_id, "book_ride", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "ride", "outcome": "error"})
    _last_action.pop(user_id, None)
    _start_ride(user_id, payload, _call_loop())
    return speak(FAMILY_YES_SAY, data={"category": "ride", "outcome": "booking"})


@mobility.tool()
def get_ride_status(user_id: str) -> str:
    """Tell the user where their booked ride is when they ask about their ride."""
    try:
        rows = db.get_client().table("rides").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute().data
    except Exception:  # noqa: BLE001
        log.exception("could not read rides for %s", user_id)
        return speak("I couldn't check on your ride just now. Want me to try again?", data={"category": "ride", "outcome": "error"})
    if not rows or rows[0].get("status") in ("failed", "cancelled", "completed"):
        return speak("You don't have a ride booked right now. Would you like me to book one?", data={"category": "ride", "outcome": "resolved"})
    ride = rows[0]
    who = f"{ride['driver']} in a {ride['car']}, plate {spoken_plate(ride['plate'])}," if ride.get("driver") else "A driver"
    return speak(f"{who} is taking you to {ride['dropoff']}.", data={"category": "ride", "outcome": "resolved", "status": ride.get("status")})


def _execute_book_ride(approval) -> str:
    """Family replied YES to a held ride: book it the same way a spoken yes would."""
    payload = dict(approval.payload or {})
    _start_ride(approval.user_id, payload, _call_loop())
    return f"Approved. Booking the ride to {payload.get('destination', 'the appointment')} now; we'll text you the driver's details."


ACTION_EXECUTORS["book_ride"] = _execute_book_ride
