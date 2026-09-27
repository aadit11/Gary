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
# Food & groceries: staged ordering
#
# The browser runs ahead of the conversation. The moment a restaurant is named, stage 1 opens
# it (open / closed / missing). As soon as the dish is known, stage 2 adds the closest item to
# the cart and stops on the checkout page; the caller then hears the real item and price and
# is asked to confirm. "Yes" is stage 3: one click on Place Order. Nothing is ordered before the
# pending action is consumed by confirm_order (safety invariant 2), and policy.check() runs on
# the staged price before the read-back (invariant 1).
# ---------------------------------------------------------------------------

STAGE_TTL_S = 600


def _caller_name(user_id: str) -> str:
    try:
        rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
        if rows and rows[0].get("name"):
            return str(rows[0]["name"]).split(" ")[0]
    except Exception:  # noqa: BLE001
        log.exception("could not read the caller's name")
    return "They"


def _speak_into_call(call_loop: Optional[asyncio.AbstractEventLoop], user_id: str, message: str, behavior: str = "queue") -> None:
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


def _runner():
    import sys

    main = sys.modules.get("main") or importlib.import_module("main")
    return main.app.state.browser_runner


def _stop_active_order(user_id: str) -> None:
    """Stop any browser job for this caller so its updates stop talking over the call."""
    cancel = getattr(_runner(), "cancel_for_user", None)
    if callable(cancel):
        cancel(user_id)


def _call_loop() -> Optional[asyncio.AbstractEventLoop]:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _progress_callback(call_loop: Optional[asyncio.AbstractEventLoop], user_id: str, fallback: str):
    """Fixed reassurance while the browser works: first after ~12 s, then every 20 s. Never model reasoning."""
    started = time.monotonic()
    spoken = {"n": 0}

    def on_progress(_reason: str) -> None:
        from voice.bridge import ACTIVE_SESSIONS

        session = ACTIVE_SESSIONS.get(user_id)
        if session is not None and getattr(session, "order_updates_paused", False):
            return
        elapsed = time.monotonic() - started
        due = 12 if spoken["n"] == 0 else 12 + 20 * spoken["n"]
        if elapsed < due:
            return
        spoken["n"] += 1
        line = fallback if spoken["n"] == 1 else "Still working on it, thanks for your patience."
        _speak_into_call(call_loop, user_id, line, behavior="queue")

    return on_progress


_NAME_NOISE = {"the", "a", "an", "restaurant", "restaurants", "place", "on", "from", "at", "in", "doordash", "dashdish", "please", "near", "me"}


def _normalize_restaurant(restaurant: str) -> str:
    """'the Souvla restaurant on DoorDash' -> 'souvla'. Speech gives many spellings of one name."""
    words = re.findall(r"[a-z0-9']+", (restaurant or "").casefold())
    kept = [w for w in words if w not in _NAME_NOISE]
    return " ".join(kept or words)


def _same_restaurant(a: str, b: str) -> bool:
    a, b = _normalize_restaurant(a), _normalize_restaurant(b)
    return bool(a and b) and (a == b or a in b or b in a)


# One food session per caller: {restaurant, dish, stage, item, price, action_id, at}
# stage: checking | open | closed | missing | staging | staged | placing | placed | error
_food: dict[str, dict] = {}


def _session(user_id: str) -> dict | None:
    sess = _food.get(user_id)
    if sess and time.monotonic() - sess.get("at", 0) > STAGE_TTL_S:
        _food.pop(user_id, None)
        return None
    return sess


def _set(user_id: str, **patch) -> dict:
    sess = _food.setdefault(user_id, {"restaurant": "", "dish": "", "stage": "", "item": "", "price": 0.0, "action_id": ""})
    sess.update(patch)
    sess["at"] = time.monotonic()
    return sess


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


def _parse_staged(result_text: str) -> tuple[str, float] | None:
    """'STAGED: Buffalo Spicy Wings | $12.96' -> ('Buffalo Spicy Wings', 12.96)."""
    m = re.search(r"STAGED:\s*(.+?)\s*\|\s*\$?\s*([\d,]+(?:\.\d+)?)", result_text or "", re.I)
    if m:
        return m.group(1).strip(" .|"), float(m.group(2).replace(",", ""))
    m = re.search(r"STAGED:\s*(.+)", result_text or "", re.I)
    if m:
        return m.group(1).strip(" .|"), 0.0
    return None


def _readback(sess: dict) -> str:
    price = f" for {money_str(sess['price'])}" if sess.get("price") else ""
    return f"{sess['restaurant']} has {sess['item']}{price}, ready to deliver to your home. Should I place it?"


# --- stage 1: open the restaurant --------------------------------------------

def _begin_lookup(user_id: str, restaurant: str, dish: str) -> None:
    _stop_active_order(user_id)
    _set(user_id, restaurant=restaurant, dish=dish, stage="checking", item="", price=0.0, action_id="")
    call_loop = _call_loop()
    goal = (
        f"Look up {restaurant} on DoorDash. Do not add anything to the cart and do not place an order. "
        "Search for the restaurant and open its page. "
        f'If its menu is available for delivery, finish with send_msg_to_user("DONE: OPEN. {restaurant} can take a delivery order."). '
        f'If the page says closed, unavailable, or not accepting orders, finish with send_msg_to_user("DONE: CLOSED. {restaurant} is closed."). '
        f'If it is not listed, finish with send_msg_to_user("DONE: MISSING. {restaurant} is not on DoorDash.").'
    )

    def on_done(job) -> None:
        sess = _session(user_id)
        if not sess or sess.get("stage") != "checking" or not _same_restaurant(sess["restaurant"], restaurant):
            return
        state = _eligibility(getattr(job, "status", ""), getattr(job, "result_text", ""))
        if state == "cancelled":
            _food.pop(user_id, None)
            return
        _set(user_id, stage=state)
        activity.log_event(user_id, "restaurant_checked", f"{restaurant} is {state}.", {"category": "food_order", "outcome": state})
        if state == "open" and sess.get("dish"):
            _speak_into_call(call_loop, user_id, f"{restaurant} is open. I'm getting the {sess['dish']} ready now.", behavior="queue")
            _begin_staging(user_id, call_loop)
            return
        if state == "open":
            line = f"{restaurant} is open for delivery. What would you like from there?"
        elif state == "closed":
            line = f"{restaurant} is closed right now, so I can't order from there. Want a different restaurant?"
        elif state == "missing":
            line = f"I couldn't find {restaurant} on DoorDash. Want a different restaurant?"
        else:
            line = f"I couldn't check {restaurant} just now. Want me to try again?"
        _speak_into_call(call_loop, user_id, line, behavior="queue")

    _runner().submit(
        site="dashdish", goal=goal, user_id=user_id, replay=False, lookup=True, mode="lookup",
        park=True, park_when="OPEN", page_name=restaurant, on_done=on_done,
        on_progress=_progress_callback(call_loop, user_id, f"I'm still checking whether {restaurant} is open."),
    )


# --- stage 2: add the dish and stop at checkout ------------------------------

def _begin_staging(user_id: str, call_loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    sess = _session(user_id)
    if not sess or not sess.get("dish"):
        return
    restaurant, dish = sess["restaurant"], sess["dish"]
    call_loop = call_loop or _call_loop()
    _set(user_id, stage="staging")
    goal = (
        f"You are on the {restaurant} menu page. Find {dish}; if that exact dish is not listed, choose the closest item on the menu. "
        "Click its Add button, then click 'Add to cart' in the dialog (a size is already selected; never click unlabeled buttons or the close button). "
        "Open the cart (the button at the top right whose label is the item count), click Checkout, and STOP on the checkout page. "
        "Do not click Place Order. Then finish with send_msg_to_user(\"STAGED: <exact item name as listed> | <item price shown, e.g. $12.96>\")."
    )

    def on_done(job) -> None:
        cur = _session(user_id)
        if not cur or cur.get("stage") != "staging":
            return
        status = getattr(job, "status", "")
        parsed = _parse_staged(getattr(job, "result_text", "")) if status == "done" else None
        if status == "cancelled":
            return
        if parsed and (len(parsed[0]) > 60 or re.search(r"\b(I|you|let me|however)\b", parsed[0])):
            parsed = (dish, 0.0)  # the cart is staged but the summary was narration; use the caller's words
        if not parsed:
            _set(user_id, stage="error")
            activity.log_event(user_id, "order_stage_failed", f"Could not stage {dish} at {restaurant}", {"category": "food_order", "outcome": "error"})
            _speak_into_call(call_loop, user_id, f"I couldn't find {dish} at {restaurant}. Want to try something else?", behavior="queue")
            return
        item, price = parsed
        decision = policy.check(kind="order", payee=restaurant, amount=price, user_id=user_id, message_text=item)
        if decision.needs_approval:
            _set(user_id, stage="needs_approval", item=item, price=price)
            approvals.request(user_id=user_id, action="place_order", payload={"item_name": item, "vendor": restaurant, "price": price},
                              reason=decision.reason, summary=f"{item} from {restaurant} for {money_str(price)}")
            _speak_into_call(call_loop, user_id, f"{restaurant} has {item} for {money_str(price)}. That one's a bit unusual, so I'm checking with {decision.family_name} first.", behavior="queue")
            return
        action_id = pending.create("place_order", user_id, item_name=item, vendor=restaurant, price=price)
        _set(user_id, stage="staged", item=item, price=price, action_id=action_id)
        activity.log_event(user_id, "order_staged", f"{item} from {restaurant} for {money_str(price)} is ready to place.", {"category": "food_order", "outcome": "staged"})
        _speak_into_call(call_loop, user_id, _readback(_session(user_id)), behavior="queue")

    _runner().submit(
        site="dashdish", goal=goal, user_id=user_id, replay=False, mode="stage",
        park=True, park_when="STAGED", page_name=restaurant, on_done=on_done,
        on_progress=_progress_callback(call_loop, user_id, f"I'm still getting the {dish} ready at {restaurant}."),
    )


@orders.tool()
def search_food_and_groceries(user_id: str, restaurant: str = "", dish: str = "") -> str:
    """Call this the moment the caller names a restaurant, even before they say what to order; pass the dish too if they said it. It opens the restaurant in the background and, once the dish is known, gets it into the cart so the read-back has the real price."""
    restaurant = (restaurant or "").strip()
    dish = (dish or "").strip()
    if not restaurant and not dish:
        return speak("Which restaurant should I use, and what would you like from there?", data={"category": "food_order", "outcome": "resolved"})
    if not restaurant:
        return speak(f"Which restaurant should I order {dish} from?", data={"category": "food_order", "outcome": "resolved", "item": dish})

    sess = _session(user_id)
    same = bool(sess) and _same_restaurant(sess["restaurant"], restaurant)
    if same:
        stage = sess["stage"]
        if dish and dish != sess.get("dish"):
            _set(user_id, dish=dish)
            if stage == "open":
                _begin_staging(user_id)
                return speak(f"{restaurant} is open. I'm getting the {dish} ready now, one moment.", data={"category": "food_order", "outcome": "staging"})
            if stage in ("staged", "staging", "needs_approval", "error"):
                _set(user_id, stage="open")
                _begin_staging(user_id)
                return speak(f"Sure, I'm getting the {dish} ready at {restaurant} instead.", data={"category": "food_order", "outcome": "staging"})
        if stage == "checking":
            ask = f"I'm still checking whether {restaurant} is open. " + ("" if sess.get("dish") else "What would you like from there?")
            return speak(ask.strip(), data={"category": "food_order", "outcome": "checking"})
        if stage == "open":
            return speak(f"{restaurant} is open for delivery. What would you like from there?", data={"category": "food_order", "outcome": "open"})
        if stage == "staging":
            return speak(f"I'm still getting the {sess['dish']} ready at {restaurant}.", data={"category": "food_order", "outcome": "staging"})
        if stage == "staged":
            return speak(_readback(sess), action_id=sess["action_id"], data={"category": "food_order", "outcome": "staged"})
        if stage in ("closed", "missing"):
            return speak(f"{restaurant} is {'closed right now' if stage == 'closed' else 'not on DoorDash'}. Want a different restaurant?", data={"category": "food_order", "outcome": stage})
    try:
        _begin_lookup(user_id, restaurant, dish)
    except Exception:  # noqa: BLE001
        log.exception("restaurant lookup failed to start")
        return speak(f"I couldn't check {restaurant} just now. Want me to try again?", data={"category": "food_order", "outcome": "error"})
    if dish:
        say = f"I'm looking for {dish} at {restaurant}. Give me a moment."
    else:
        say = f"I'm checking whether {restaurant} is open. What would you like from there?"
    return speak(say, data={"category": "food_order", "outcome": "checking", "restaurant": restaurant, "item": dish})


@orders.tool()
def prepare_order(user_id: str, restaurant: str = "", item: str = "", favorite_id: Optional[str] = None) -> str:
    """Repeat the read-back for an order that is ready, or start one from a saved favorite. Not needed after search_food_and_groceries has already read the order back."""
    if favorite_id:
        favorite = _get_favorite(user_id, favorite_id)
        if not favorite:
            return speak("I couldn't find that favorite anymore. Want to tell me what you'd like instead?", data={"category": "food_order", "outcome": "error"})
        return search_food_and_groceries(user_id, restaurant=favorite["vendor"] or "", dish=favorite["label"])
    sess = _session(user_id)
    if sess and sess.get("stage") == "staged" and (not restaurant or _same_restaurant(sess["restaurant"], restaurant)):
        return speak(_readback(sess), action_id=sess["action_id"], data={"category": "food_order", "outcome": "staged"})
    if not restaurant:
        return speak("Which restaurant should I use, and what would you like from there?", data={"category": "food_order", "outcome": "error"})
    return search_food_and_groceries(user_id, restaurant=restaurant, dish=item)


# --- stage 3: place it -------------------------------------------------------------

@orders.tool()
def confirm_order(user_id: str, action_id: str = "") -> str:
    """Place the order that was read back, after the caller clearly says yes. The action id may be left blank."""
    sess = _session(user_id)
    action_id = (action_id or "").strip() or (sess.get("action_id", "") if sess else "")
    try:
        payload = pending.consume(action_id, "place_order", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "food_order", "outcome": "error"})
    if not sess or sess.get("stage") != "staged":
        return speak("Let me get that order ready first. Which restaurant and what would you like?", data={"category": "food_order", "outcome": "error"})

    item_name, vendor, price = payload["item_name"], payload.get("vendor") or sess["restaurant"], float(payload.get("price") or 0)
    call_loop = _call_loop()
    _set(user_id, stage="placing")
    caller = _caller_name(user_id)
    notify.notify_family(user_id, f"{caller} confirmed an order: {item_name} from {vendor} for {money_str(price)}. Placing it now.")
    activity.log_event(user_id, "order_requested", f"Placing {item_name} from {vendor}.", {"category": "food_order", "outcome": "placing"})
    goal = (
        "You are on the DoorDash checkout page with the item already in the cart. Click the Place Order button. "
        "Then finish with send_msg_to_user(\"DONE: Order placed, order id <the id shown on the page>\")."
    )

    def on_done(job) -> None:
        status = getattr(job, "status", "")
        if status == "cancelled":
            return
        success = status == "done"
        text = (getattr(job, "result_text", "") or "")
        m = re.search(r"ORD-[\w-]+", text, re.I)
        order_ref = m.group(0) if m else None
        try:
            db.get_client().table("orders").insert({
                "user_id": user_id, "vendor": vendor, "items": [{"name": item_name, "price": price}], "total": price,
                "status": "placed" if success else "failed", "external_id": order_ref,
            }).execute()
        except Exception:  # noqa: BLE001
            log.exception("failed to record order for %s", user_id)
        activity.log_event(user_id, "order", f"Order placed: {item_name} from {vendor}" if success else f"Order to {vendor} failed",
                           {"category": "food_order", "outcome": "placed" if success else "error", "order_id": order_ref})
        notify.notify_family(user_id, f"Order placed: {item_name} from {vendor} for {money_str(price)}." if success else f"Sorry, the order from {vendor} didn't go through.")
        _set(user_id, stage="placed" if success else "error")
        if success:
            message = f"Your order is placed. {item_name} from {vendor}" + (f" for {money_str(price)}" if price else "") + " is on its way."
        else:
            message = f"I had trouble placing the {item_name}. Want me to try again?"
        _speak_into_call(call_loop, user_id, message, behavior="queue")

    _runner().submit(site="dashdish", goal=goal, user_id=user_id, replay=False, mode="place", page_name=vendor, on_done=on_done,
                     on_progress=_progress_callback(call_loop, user_id, "Still placing it, one moment."))
    return speak(f"Placing the {item_name} now.", data={"category": "food_order", "outcome": "placing"})


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
    """Book a previously prepared home service appointment on TaskHare after the user says yes."""
    try:
        payload = pending.consume(action_id, "book_service", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "home_service", "outcome": "error"})

    provider_name = payload["provider"]
    when = date_str(payload["time"])
    goal = (
        f"On TaskHare, hire {provider_name} for {payload['category']} help. "
        f"The visit should be {when}. "
        "Search or open that tasker, choose that time, and click Confirm this visit. "
        "Stop when the page says you're booked. Do not invent a tasker or a time."
    )
    call_loop = _call_loop()
    caller = _caller_name(user_id)
    notify.notify_family(
        user_id,
        f"{caller} asked to book {provider_name} for {when}. The request to book has been started.",
    )
    activity.log_event(
        user_id,
        "service_requested",
        f"Started a booking for {provider_name}.",
        {"category": "home_service", "outcome": "booking"},
    )

    def on_done(job) -> None:
        if getattr(job, "status", None) == "cancelled":
            return
        success = getattr(job, "status", None) == "done"
        if success:
            try:
                db.get_client().table("service_bookings").insert({
                    "user_id": user_id,
                    "category": payload["category"],
                    "provider": provider_name,
                    "scheduled_at": payload["time"],
                    "price": payload["price"],
                    "status": "booked",
                    "external_id": getattr(job, "id", "") or "taskhare",
                }).execute()
            except Exception:  # noqa: BLE001
                log.exception("failed to record service booking for %s", user_id)
        activity.log_event(
            user_id,
            "service_booking",
            f"Booked {provider_name} for {when}" if success else f"Booking {provider_name} failed",
            {"category": "home_service", "outcome": "booked" if success else "error"},
        )
        notify.notify_family(
            user_id,
            f"{provider_name} is booked for {when} at the home."
            if success else
            f"Sorry, the booking with {provider_name} didn't go through.",
        )
        message = (
            f"You're booked. {provider_name} will come {when}."
            if success else
            f"I had trouble booking {provider_name}. Want me to try again?"
        )
        _speak_into_call(call_loop, user_id, message, behavior="queue")

    app_module = importlib.import_module("main")
    app_module.app.state.browser_runner.submit(
        site="taskhare",
        goal=goal,
        user_id=user_id,
        replay=False,
        on_done=on_done,
        on_progress=_progress_callback(call_loop, user_id, f"I'm still booking {provider_name}."),
    )
    return speak(
        f"I'm booking {provider_name} on TaskHare for {when}. I'll tell you how it's going.",
        data={"category": "home_service", "outcome": "booking"},
    )
