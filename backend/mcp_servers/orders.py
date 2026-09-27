"""Vertical 3 (Person 3): get_favorite_orders, search_food_and_groceries, prepare_order,
confirm_order, find_home_service, prepare_service_booking, confirm_service_booking.

Two flows, one shape (search/find -> prepare -> confirm), per the build plan:
  Food/groceries : search_food_and_groceries -> prepare_order -> confirm_order
  Home services  : find_home_service -> prepare_service_booking -> confirm_service_booking

Every prepare_*/confirm_* re-fetches the authoritative item, favorite, or provider server-side
by id rather than trusting a name/price the model supplies, the same way prepare_bill_payment
takes only a bill_id. policy.check() runs on both money-moving prepare_* tools.

Every speak() carries data.category/data.outcome, matching mcp_servers/checkins.py: the bridge
reads these for the tool_called activity log and the call's last_category/last_outcome.

Food orders are placed on the DashDish clone by Muse (the Meta model) in the browser agent.
There is no fixed menu. confirm_order never blocks the call: it tells the caregiver the
request has started, then speaks each new step of Muse's reasoning while the order is placed
(about half a minute). The final result is spoken into the live call if the user is still
on the phone. Home service bookings hit the mock API directly and are fast enough to
confirm synchronously.

NOTE for Person 1: voice/agent_settings.py's SERVERS_BY_REASON does not include "orders" for
any reason yet (not even "inbound"), so these tools aren't reachable on a live call until
that's added.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import re
import time
from typing import Optional

from mcp.server.fastmcp import FastMCP

from core import activity, approvals, db, notify, pending, policy
from core.pending import PendingActionError
from core.speech import date_str, money_str, speak
from clients import mock_services

log = logging.getLogger(__name__)

orders = FastMCP("orders", instructions="Food and grocery orders, and home service bookings.")


# ---------------------------------------------------------------------------
# Favorites ("order my usual")
# ---------------------------------------------------------------------------

@orders.tool()
def get_favorite_orders(user_id: str) -> str:
    """List the user's saved usual orders when they ask to order their usual."""
    try:
        rows = db.get_client().table("favorites").select("*").eq("user_id", user_id).execute().data
    except Exception:  # noqa: BLE001
        log.exception("get_favorite_orders failed")
        return speak("I couldn't check your favorites just now. Want me to try again?", data={"category": "favorites", "outcome": "error"})

    if not rows:
        return speak(
            "I don't have any usual orders saved for you yet. Tell me what you'd like and I can save it.",
            data={"category": "favorites", "outcome": "resolved"},
        )

    names = [r["label"] for r in rows[:3]]
    if len(names) == 1:
        say = f"Your usual is {names[0]}. Want me to order that?"
    else:
        say = "Your favorites are " + ", ".join(names[:-1]) + f", and {names[-1]}. Which one would you like?"

    data = [{"id": r["id"], "label": r["label"], "vendor": r["vendor"], "total": float(r["total"] or 0)} for r in rows]
    return speak(say, data={"category": "favorites", "outcome": "resolved", "favorites": data})


def _get_favorite(user_id: str, favorite_id: str) -> Optional[dict]:
    res = db.get_client().table("favorites").select("*").eq("id", favorite_id).eq("user_id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


# ---------------------------------------------------------------------------
# Food & groceries
# ---------------------------------------------------------------------------

def _caller_name(user_id: str) -> str:
    try:
        rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
        if rows and rows[0].get("name"):
            return str(rows[0]["name"]).split(" ")[0]
    except Exception:  # noqa: BLE001
        log.exception("could not read the caller's name")
    return "They"


def _spoken_step(reason: str) -> str:
    """One plain sentence from Muse's latest reasoning, with no browser commands."""
    text = re.sub(r"```.*?```", "", reason or "", flags=re.S).strip()
    text = text.split("\n")[0].strip()
    if not text or re.search(r"\b(click|fill|press|noop|send_msg_to_user)\s*\(", text):
        return ""
    sentence = re.split(r"(?<=[.!?])\s", text)[0].strip()
    if len(sentence) > 160:
        sentence = sentence[:160].rsplit(" ", 1)[0]
    if len(sentence) < 8:
        return ""
    return sentence if sentence[-1] in ".!?" else sentence + "."


def _speak_into_call(
    call_loop: Optional[asyncio.AbstractEventLoop],
    user_id: str,
    message: str,
    behavior: str = "queue",
) -> None:
    if call_loop is None:
        return
    from voice.bridge import ACTIVE_SESSIONS

    session = ACTIVE_SESSIONS.get(user_id)
    if session is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(session.inject(message, behavior=behavior), call_loop)
    except Exception:  # noqa: BLE001
        log.exception("failed to speak into the live call for %s", user_id)


def _stop_active_order(user_id: str) -> None:
    """Stop an order already being placed so its updates stop talking over the call."""
    import sys

    main = sys.modules.get("main")
    app = getattr(main, "app", None)
    runner = getattr(getattr(app, "state", None), "browser_runner", None)
    cancel = getattr(runner, "cancel_for_user", None)
    if callable(cancel):
        cancel(user_id)


def _call_loop() -> Optional[asyncio.AbstractEventLoop]:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _progress_callback(call_loop: Optional[asyncio.AbstractEventLoop], user_id: str, fallback: str):
    spoken = {"at": 0.0, "line": ""}

    def on_progress(reason: str) -> None:
        from voice.bridge import ACTIVE_SESSIONS

        session = ACTIVE_SESSIONS.get(user_id)
        if session is not None and getattr(session, "order_updates_paused", False):
            return
        line = _spoken_step(reason) or fallback
        now = time.monotonic()
        if line == spoken["line"] or now - spoken["at"] < 8:
            return
        spoken["at"] = now
        spoken["line"] = line
        _speak_into_call(call_loop, user_id, line, behavior="queue")

    return on_progress


# restaurant name, lowercased, for one user -> checking | open | closed | missing | error
_restaurant_status: dict[tuple[str, str], str] = {}
_pending_dish: dict[tuple[str, str], str] = {}


def _restaurant_key(user_id: str, restaurant: str) -> tuple[str, str]:
    return (user_id, restaurant.casefold())


def _eligibility(status: str, result_text: str) -> str:
    if status == "cancelled":
        return "cancelled"
    upper = (result_text or "").upper()
    if re.search(r"\bCLOSED\b", upper) or "NOT ACCEPTING" in upper:
        return "closed"
    if re.search(r"\bMISSING\b", upper) or "COULDN'T FIND" in upper or "COULD NOT FIND" in upper:
        return "missing"
    if status == "done" and re.search(r"\bOPEN\b", upper):
        return "open"
    return "error"


def _eligibility_say(restaurant: str, state: str, dish: str) -> str:
    if state == "open" and dish:
        return f"{restaurant} is open for delivery. That's {dish} from {restaurant}, delivered to your home. Should I place it?"
    if state == "open":
        return f"{restaurant} is open for delivery. What would you like?"
    if state == "closed":
        return f"{restaurant} is closed right now, so I can't order from there. Want a different restaurant?"
    if state == "missing":
        return f"I couldn't find {restaurant} on DoorDash. Want a different restaurant?"
    return f"I couldn't check {restaurant} just now. Want me to try again?"


def _begin_restaurant_check(user_id: str, restaurant: str, dish: str = "") -> None:
    """Look the restaurant up on DoorDash before anyone is asked for a dish."""
    key = _restaurant_key(user_id, restaurant)
    _stop_active_order(user_id)
    _restaurant_status[key] = "checking"
    _pending_dish[key] = dish.strip()
    call_loop = _call_loop()
    goal = (
        f"Look up {restaurant} on DoorDash. Do not add anything to the cart and do not place an order. "
        "Search for the restaurant and open its page. "
        f'If its menu is available for delivery, finish with send_msg_to_user("DONE: OPEN. {restaurant} can take a delivery order."). '
        f'If the page says closed, unavailable, or not accepting orders, finish with send_msg_to_user("DONE: CLOSED. {restaurant} is closed."). '
        f'If it is not listed, finish with send_msg_to_user("DONE: MISSING. {restaurant} is not on DoorDash.").'
    )

    def on_done(job) -> None:
        if _restaurant_status.get(key) != "checking":
            return
        state = _eligibility(getattr(job, "status", ""), getattr(job, "result_text", ""))
        if state == "cancelled":
            return
        _restaurant_status[key] = state
        saved = _pending_dish.get(key, "")
        activity.log_event(
            user_id,
            "restaurant_checked",
            f"{restaurant} is {state}.",
            {"category": "food_order", "outcome": state},
        )
        _speak_into_call(call_loop, user_id, _eligibility_say(restaurant, state, saved), behavior="queue")

    app_module = importlib.import_module("main")
    app_module.app.state.browser_runner.submit(
        site="dashdish",
        goal=goal,
        user_id=user_id,
        replay=False,
        lookup=True,
        park=True,
        page_name=restaurant,
        on_done=on_done,
        on_progress=_progress_callback(call_loop, user_id, f"I'm still checking whether {restaurant} is open."),
    )


@orders.tool()
def search_food_and_groceries(user_id: str, restaurant: str = "", dish: str = "") -> str:
    """Check a named restaurant on DoorDash before asking what to order. Ask which restaurant if they only named a dish."""
    restaurant = (restaurant or "").strip()
    dish = (dish or "").strip()
    if not restaurant and not dish:
        return speak(
            "Which restaurant should I use, and what would you like from there?",
            data={"category": "food_order", "outcome": "resolved"},
        )
    if not restaurant:
        return speak(
            f"Which restaurant should I order {dish} from?",
            data={"category": "food_order", "outcome": "resolved", "item": dish},
        )
    try:
        _begin_restaurant_check(user_id, restaurant, dish)
    except Exception:  # noqa: BLE001
        log.exception("restaurant check failed to start")
        return speak(
            f"I couldn't check {restaurant} just now. Want me to try again?",
            data={"category": "food_order", "outcome": "error"},
        )
    if dish:
        say = f"I'm checking whether {restaurant} is open before I take the {dish}."
    else:
        say = f"I'm checking whether {restaurant} is open for delivery. I'll tell you what I find."
    return speak(
        say,
        data={"category": "food_order", "outcome": "checking", "restaurant": restaurant, "item": dish},
    )


@orders.tool()
def prepare_order(user_id: str, restaurant: str = "", item: str = "", favorite_id: Optional[str] = None) -> str:
    """Read back a DoorDash order once the restaurant is open and you have the dish, or a saved favorite."""
    if favorite_id:
        _stop_active_order(user_id)
        favorite = _get_favorite(user_id, favorite_id)
        if not favorite:
            return speak(
                "I couldn't find that favorite anymore. Want to tell me what you'd like instead?",
                data={"category": "food_order", "outcome": "error"},
            )
        item_name, vendor = favorite["label"], favorite["vendor"] or "DoorDash"
        price = float(favorite["total"] or 0)
    else:
        restaurant = restaurant.strip()
        item = item.strip()
        if not restaurant:
            ask = f"Which restaurant should I order {item} from?" if item else "Which restaurant should I use, and what would you like from there?"
            return speak(ask, data={"category": "food_order", "outcome": "error"})
        state = _restaurant_status.get(_restaurant_key(user_id, restaurant), "")
        if state != "open":
            if state == "checking":
                ask = f"I'm still checking whether {restaurant} is open. I'll ask about the food if it can take an order."
            elif state == "closed":
                ask = f"{restaurant} is closed right now, so I can't order from there. Want a different restaurant?"
            elif state == "missing":
                ask = f"I couldn't find {restaurant} on DoorDash. Want a different restaurant?"
            elif state == "error":
                ask = f"I couldn't check {restaurant} just now. Want me to try again?"
            else:
                try:
                    _begin_restaurant_check(user_id, restaurant, item)
                    ask = f"Let me check whether {restaurant} is open before I take that order."
                except Exception:  # noqa: BLE001
                    log.exception("restaurant check failed to start")
                    ask = f"I couldn't check {restaurant} just now. Want me to try again?"
            return speak(ask, data={"category": "food_order", "outcome": state or "checking", "restaurant": restaurant})
        if not item:
            return speak(
                f"What would you like from {restaurant}?",
                data={"category": "food_order", "outcome": "error", "restaurant": restaurant},
            )
        _stop_active_order(user_id)
        item_name, vendor, price = item, restaurant, 0.0

    decision = policy.check(kind="order", payee=vendor, amount=price, user_id=user_id, message_text=item_name)
    if decision.needs_approval:
        approvals.request(
            user_id=user_id,
            action="place_order",
            payload={"item_name": item_name, "vendor": vendor, "price": price, "favorite_id": favorite_id},
            reason=decision.reason,
            summary=f"{item_name} from {vendor}",
        )
        return speak(
            f"That one's a bit unusual, so I'm checking with {decision.family_name} first. I'll let you know.",
            data={"category": "food_order", "outcome": "needs_approval"},
        )

    action_id = pending.create(
        "place_order",
        user_id,
        item_name=item_name,
        vendor=vendor,
        price=price,
        favorite_id=favorite_id,
    )
    if price:
        readback = f"That's {item_name} from {vendor} for {money_str(price)}, delivered to your home. Should I place it?"
    else:
        readback = f"That's {item_name} from {vendor}, delivered to your home. I'll use the price shown at the store. Should I place it?"
    return speak(readback, action_id=action_id, data={"category": "food_order"})


@orders.tool()
def confirm_order(user_id: str, action_id: str) -> str:
    """Place a previously prepared food or grocery order after the user says yes."""
    try:
        payload = pending.consume(action_id, "place_order", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "food_order", "outcome": "error"})

    item_name = payload["item_name"]
    vendor = payload.get("vendor") or "DoorDash"
    app_module = importlib.import_module("main")  # deferred: main imports mcp_servers, which imports this file
    runner = app_module.app.state.browser_runner
    staying = False
    has_parked = getattr(runner, "has_parked", None)
    if callable(has_parked):
        staying = bool(has_parked(user_id))
    if staying:
        goal = (
            f"You are already on the {vendor} menu. Stay on this page. "
            f"Find {item_name} and place the delivery order. "
            "Do not go back to the home page and do not search for the restaurant again. "
            "Do not invent a dish that is not shown."
        )
    else:
        goal = (
            f"On DoorDash, open {vendor} and order {item_name}. "
            "Choose a real item that is on the page, then place the delivery order. Do not invent a dish that is not shown."
        )
    flow_key = payload.get("favorite_id")

    # Captured now, while we're still on the FastAPI event loop (the MCP adapter awaits this
    # tool). Progress and on_done fire later on the browser agent's worker thread, which has
    # no event loop of its own, so they hop back onto this one to speak into the live call.
    try:
        call_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
    except RuntimeError:
        call_loop = None
        log.warning("confirm_order for %s has no running event loop; result won't be spoken into a live call", user_id)

    caller = _caller_name(user_id)
    notify.notify_family(
        user_id,
        f"{caller} asked to place an order for {item_name}. The request to place it has been started.",
    )
    activity.log_event(
        user_id,
        "order_requested",
        f"Started an order for {item_name}.",
        {"category": "food_order", "outcome": "placing"},
    )

    on_progress = _progress_callback(call_loop, user_id, "I'm still working on your order.")

    def on_done(job) -> None:
        if getattr(job, "status", None) == "cancelled":
            log.info("order for %s stopped because they asked for something else", user_id)
            return
        success = getattr(job, "status", None) == "done"

        try:
            db.get_client().table("orders").insert({
                "user_id": user_id,
                "vendor": payload["vendor"],
                "items": [{"name": payload["item_name"], "price": payload["price"]}],
                "total": payload["price"],
                "status": "placed" if success else "failed",
            }).execute()
        except Exception:  # noqa: BLE001
            log.exception("failed to record order for %s", user_id)

        activity.log_event(
            user_id,
            "order",
            f"Order placed: {payload['item_name']} from {payload['vendor']}"
            if success else
            f"Order to {payload['vendor']} failed",
            {"category": "food_order", "outcome": "placed" if success else "error"},
        )
        notify.notify_family(
            user_id,
            f"Order placed: {payload['item_name']} from {payload['vendor']}."
            if success else
            f"Sorry, the order from {payload['vendor']} didn't go through.",
        )

        detail = (getattr(job, "result_text", "") or "").removeprefix("DONE:").strip()
        if success and detail:
            sentence = detail[0].upper() + detail[1:]
            if not sentence.endswith("."):
                sentence += "."
            message = f"Your order is placed. {sentence}"
        elif success:
            message = f"Good news, your order for {item_name} is placed."
        else:
            message = f"I had trouble placing your order for {item_name}. Want me to try again?"
        _speak_into_call(call_loop, user_id, message, behavior="queue")

    _stop_active_order(user_id)
    runner.submit(
        site="dashdish",
        goal=goal,
        user_id=user_id,
        flow_key=flow_key,
        on_done=on_done,
        on_progress=on_progress,
    )

    return speak(
        f"I'm placing {item_name} on DoorDash now. I'll tell you how it's going.",
        data={"category": "food_order", "outcome": "placing"},
    )


# ---------------------------------------------------------------------------
# Home services
# ---------------------------------------------------------------------------

@orders.tool()
def find_home_service(user_id: str, problem_description: str) -> str:
    """Find home service providers, such as a plumber or electrician, for a plainly described problem."""
    try:
        result = mock_services.search_services(problem_description)
    except Exception:  # noqa: BLE001
        log.exception("service search failed")
        return speak("I couldn't reach the scheduler just now, want me to try again?", data={"category": "home_service", "outcome": "error"})

    category = result.get("category", "")
    providers = [p for p in (result.get("providers") or []) if p.get("next_slots")]
    if not providers:
        return speak(
            "I couldn't find anyone for that just now. Want to describe it a different way?",
            data={"category": "home_service", "outcome": "resolved"},
        )

    top = providers[:3]
    parts = [f"{p['name']} for {money_str(p['price'])}, available {date_str(p['next_slots'][0])}" for p in top]
    if len(parts) == 1:
        say = f"I found {parts[0]}. Want me to book them?"
    else:
        say = "I found " + "; ".join(parts[:-1]) + f"; and {parts[-1]}. Who would you like?"

    data = [
        {"provider_id": p["id"], "category": category, "provider": p["name"], "price": p["price"], "time": p["next_slots"][0]}
        for p in top
    ]
    return speak(say, data={"category": "home_service", "outcome": "resolved", "options": data})


def _find_provider(category: str, provider_id: str) -> Optional[dict]:
    result = mock_services.search_services(category)
    return next((p for p in (result.get("providers") or []) if p["id"] == provider_id), None)


@orders.tool()
def prepare_service_booking(user_id: str, provider_id: str, category: str, time: Optional[str] = None) -> str:
    """Prepare to book a home service provider and return the details to read back."""
    try:
        provider = _find_provider(category, provider_id)
    except Exception:  # noqa: BLE001
        log.exception("provider lookup failed")
        return speak("I couldn't check on that provider just now, want me to try again?", data={"category": "home_service", "outcome": "error"})

    if not provider:
        return speak(
            "I couldn't find that provider anymore. Want me to look again?",
            data={"category": "home_service", "outcome": "error"},
        )

    slots = provider.get("next_slots") or []
    chosen_time = time if time in slots else (slots[0] if slots else None)
    if not chosen_time:
        return speak(
            f"{provider['name']} doesn't have any open times right now. Want me to find someone else?",
            data={"category": "home_service", "outcome": "error"},
        )

    decision = policy.check(kind="service", payee=provider["name"], amount=provider["price"], user_id=user_id)
    if decision.needs_approval:
        approvals.request(
            user_id=user_id,
            action="book_service",
            payload={"provider_id": provider_id, "category": category, "provider": provider["name"],
                      "price": provider["price"], "time": chosen_time},
            reason=decision.reason,
            summary=f"{provider['name']}, {money_str(provider['price'])}, {date_str(chosen_time)}",
        )
        return speak(
            f"I'd like to check with {decision.family_name} before booking that one.",
            data={"category": "home_service", "outcome": "needs_approval"},
        )

    action_id = pending.create(
        "book_service",
        user_id,
        provider_id=provider_id,
        category=category,
        provider=provider["name"],
        price=provider["price"],
        time=chosen_time,
    )
    return speak(
        f"{provider['name']} can come {date_str(chosen_time)} for about {money_str(provider['price'])}. Should I book them?",
        action_id=action_id,
        data={"category": "home_service"},
    )


@orders.tool()
def confirm_service_booking(user_id: str, action_id: str) -> str:
    """Book a previously prepared home service appointment after the user says yes."""
    try:
        payload = pending.consume(action_id, "book_service", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "home_service", "outcome": "error"})

    try:
        booking = mock_services.create_service_booking(provider_id=payload["provider_id"], time=payload["time"])
    except Exception:  # noqa: BLE001
        log.exception("service booking failed")
        return speak("I couldn't reach the scheduler just now, want me to try again?", data={"category": "home_service", "outcome": "error"})

    try:
        db.get_client().table("service_bookings").insert({
            "user_id": user_id,
            "category": payload["category"],
            "provider": booking.get("provider", payload["provider"]),
            "scheduled_at": booking.get("time", payload["time"]),
            "price": booking.get("price", payload["price"]),
            "status": "booked",
            "external_id": booking.get("booking_id"),
        }).execute()
    except Exception:  # noqa: BLE001
        log.exception("failed to record service booking for %s", user_id)

    provider_name = payload["provider"]
    when = date_str(payload["time"])
    activity.log_event(user_id, "service_booking", f"Booked {provider_name} for {when}", {"category": "home_service", "outcome": "booked"})
    notify.notify_family(user_id, f"{provider_name} is booked for {when} at your home.")

    return speak(f"You're all set, {provider_name} will come {when}.", data={"category": "home_service", "outcome": "booked"})
