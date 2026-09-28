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
on the phone. Home services work the same way on TaskHare, which has no API: find_home_service
searches the site in the browser and parks on the results, the taskers are read off the page and
spoken into the call, and confirm_service_booking continues from that page to book.

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
from core.speech import money_str, speak
from browser_agent.taskhare import parse_taskers, parse_taskers_result, slot_to_iso
from webhooks.sms import ACTION_EXECUTORS

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


def _caller_timezone(user_id: str) -> str:
    try:
        rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
        return str(rows[0].get("timezone") or "") if rows else ""
    except Exception:  # noqa: BLE001
        return ""


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
# Home services: TaskHare, through the browser
#
# TaskHare has no API. find_home_service starts a search job that types the caller's words into
# the site, reads the results list off the page, and parks the browser there; the options are
# spoken into the call when they arrive (about ten seconds). prepare_service_booking runs
# policy.check() on the chosen tasker's listed price and creates the pending action for the
# read-back (invariants 1 and 2); confirm_service_booking consumes it and a booking job continues
# on the parked results page (Choose -> time -> Confirm this visit). A family YES on a held
# booking runs the same booking job (ACTION_EXECUTORS["book_service"]).
# ---------------------------------------------------------------------------

# One home-service session per caller: {problem, category, stage, options, chosen, action_id, at}
# stage: searching | found | none | error | ready | needs_approval | booking | booked
_services: dict[str, dict] = {}

_PEOPLE = {
    "plumbing": ("plumber", "plumbers"),
    "electrical": ("electrician", "electricians"),
    "handyman": ("handyman", "handymen"),
    "house cleaning": ("house cleaner", "house cleaners"),
    "yard work": ("yard helper", "yard helpers"),
    "furniture assembly": ("furniture assembler", "furniture assemblers"),
}
_COUNT_WORDS = {1: "one", 2: "two", 3: "three"}
_ORDINALS = {"first": 0, "1": 0, "second": 1, "2": 1, "third": 2, "3": 2, "last": -1}
_CHOICE_FILLER = {"the", "one", "please", "that", "them", "guy", "guys", "company", "co"}


def _svc_session(user_id: str) -> dict | None:
    sess = _services.get(user_id)
    if sess and time.monotonic() - sess.get("at", 0) > STAGE_TTL_S:
        _services.pop(user_id, None)
        return None
    return sess


def _svc_set(user_id: str, **patch) -> dict:
    sess = _services.setdefault(user_id, {"problem": "", "category": "", "stage": "", "options": [], "chosen": None, "action_id": ""})
    sess.update(patch)
    sess["at"] = time.monotonic()
    return sess


def _same_problem(a: str, b: str) -> bool:
    norm = lambda t: " ".join(re.findall(r"[a-z0-9']+", (t or "").casefold()))  # noqa: E731
    return bool(a and b) and norm(a) == norm(b)


def _people(category: str, count: int) -> str:
    singular, plural = _PEOPLE.get((category or "").casefold(), ("person", f"people for {category.casefold()}" if category else "people"))
    return f"one {singular}" if count == 1 else f"{_COUNT_WORDS.get(count, str(count))} {plural}"


def _options_say(category: str, options: list[dict]) -> str:
    parts = [f"{o['name']} for {money_str(o['price'])}, available {o['time']}" for o in options]
    if len(parts) == 1:
        return f"I found {_people(category, 1)} on TaskHare: {parts[0]}. Want me to book them?"
    return f"I found {_people(category, len(parts))} on TaskHare. " + "; ".join(parts[:-1]) + f"; and {parts[-1]}. Who would you like?"


def _match_option(options: list[dict], provider: str) -> Optional[dict]:
    """The option the caller meant: by name ('Rapid Rooter', 'the Bay Plumbing one') or by position ('the first one')."""
    words = re.findall(r"[a-z0-9']+", (provider or "").casefold())
    if not words:
        return options[0] if len(options) == 1 else None
    if all(w in _ORDINALS or w in _CHOICE_FILLER for w in words):
        for w in words:
            if w in _ORDINALS:
                idx = _ORDINALS[w]
                return options[idx] if -len(options) <= idx < len(options) else None
        return None
    key = " ".join(w for w in words if w not in _CHOICE_FILLER)
    best: tuple[int, dict] | None = None
    for option in options:
        name = option["name"].casefold()
        if key and (key in name or name in key):
            return option
        overlap = len((set(words) - _CHOICE_FILLER) & set(re.findall(r"[a-z0-9']+", name)))
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, option)
    return best[1] if best else None


def _begin_service_search(user_id: str, problem: str) -> None:
    _stop_active_order(user_id)
    _svc_set(user_id, problem=problem, category="", stage="searching", options=[], chosen=None, action_id="")
    call_loop = _call_loop()
    goal = (
        f"Search TaskHare for help with this job: {problem}. Type those words into the box labeled Describe the job "
        "and submit the search. When the results list is showing, report the taskers listed with their prices and "
        "next available times, and stop. Do not choose anyone and do not book anything."
    )

    def on_done(job) -> None:
        cur = _svc_session(user_id)
        if not cur or cur.get("stage") != "searching" or cur.get("problem") != problem:
            return
        status = getattr(job, "status", "")
        if status == "cancelled":
            return
        parsed = parse_taskers_result(getattr(job, "result_text", "") or "") if status == "done" else None
        if parsed is None and getattr(job, "final_text", ""):
            category, taskers = parse_taskers(job.final_text)  # the list is on the page even if the agent stopped oddly
            parsed = (category, taskers) if taskers else None
        if parsed is None:
            _svc_set(user_id, stage="error")
            activity.log_event(user_id, "service_search_failed", f"Could not search TaskHare for: {problem}", {"category": "home_service", "outcome": "error"})
            _speak_into_call(call_loop, user_id, "I couldn't get an answer from TaskHare just now. Want me to try again?", behavior="queue")
            return
        category, taskers = parsed
        options = taskers[:3]
        if not options:
            _svc_set(user_id, stage="none", category=category)
            activity.log_event(user_id, "service_search", f"No one on TaskHare for: {problem}", {"category": "home_service", "outcome": "none"})
            _speak_into_call(call_loop, user_id, "I couldn't find anyone on TaskHare for that. Want to describe it a different way?", behavior="queue")
            return
        _svc_set(user_id, stage="found", category=category, options=options)
        activity.log_event(user_id, "service_search", f"TaskHare lists {len(options)} for: {problem}", {"category": "home_service", "outcome": "found", "options": options})
        _speak_into_call(call_loop, user_id, _options_say(category, options), behavior="queue")

    _runner().submit(
        site="taskhare", goal=goal, user_id=user_id, replay=False, lookup=True, mode="taskers",
        park=True, park_when="TASKERS", page_name=problem, on_done=on_done,
        on_progress=_progress_callback(call_loop, user_id, "I'm still looking on TaskHare."),
    )


@orders.tool()
def find_home_service(user_id: str, problem_description: str) -> str:
    """Call this the moment the caller describes a home problem, such as a leak or a broken light, in their own words. It searches TaskHare in the background and the taskers found are read out in the call when ready."""
    problem = (problem_description or "").strip()
    if not problem:
        return speak("What's going on at home that you'd like help with?", data={"category": "home_service", "outcome": "resolved"})
    sess = _svc_session(user_id)
    if sess and _same_problem(sess.get("problem", ""), problem):
        if sess["stage"] == "searching":
            return speak("I'm still looking on TaskHare. One moment.", data={"category": "home_service", "outcome": "searching"})
        if sess["stage"] in ("found", "ready", "needs_approval") and sess.get("options"):
            return speak(_options_say(sess["category"], sess["options"]), data={"category": "home_service", "outcome": "found", "options": sess["options"]})
    try:
        _begin_service_search(user_id, problem)
    except Exception:  # noqa: BLE001
        log.exception("home service search failed to start")
        return speak("I couldn't reach TaskHare just now. Want me to try again?", data={"category": "home_service", "outcome": "error"})
    return speak(
        "Let me look on TaskHare for someone who can help with that. Give me a moment.",
        data={"category": "home_service", "outcome": "searching", "problem": problem},
    )


@orders.tool()
def prepare_service_booking(user_id: str, provider: str = "") -> str:
    """After find_home_service has read out the taskers, prepare to book the one the caller chose, by name or position, and return the read-back."""
    sess = _svc_session(user_id)
    if not sess or sess.get("stage") in ("", "none", "error"):
        return speak("Tell me what's going on at home and I'll look for someone on TaskHare.", data={"category": "home_service", "outcome": "error"})
    stage = sess["stage"]
    if stage == "searching":
        return speak("I'm still looking on TaskHare. One moment.", data={"category": "home_service", "outcome": "searching"})
    if stage == "booking":
        return speak(f"I'm already booking {sess['chosen']['name']}. I'll tell you how it goes.", data={"category": "home_service", "outcome": "booking"})
    if stage == "booked":
        return speak(f"{sess['chosen']['name']} is already booked for {sess['chosen']['time']}.", data={"category": "home_service", "outcome": "booked"})

    options = sess.get("options") or []
    chosen = _match_option(options, provider)
    if not chosen:
        names = [o["name"] for o in options]
        ask = f"Should I book {names[0]}?" if len(names) == 1 else "Which one would you like: " + ", ".join(names[:-1]) + f", or {names[-1]}?"
        return speak(ask, data={"category": "home_service", "outcome": "resolved", "options": options})
    if stage == "ready" and sess.get("action_id") and sess.get("chosen") == chosen:
        return speak(f"{chosen['name']} can come {chosen['time']} for {money_str(chosen['price'])}. Should I book them?",
                     action_id=sess["action_id"], data={"category": "home_service", "outcome": "ready"})

    payload = {"provider": chosen["name"], "price": chosen["price"], "time": chosen["time"],
               "category": sess.get("category", ""), "problem": sess.get("problem", "")}
    decision = policy.check(kind="service", payee=chosen["name"], amount=chosen["price"], user_id=user_id)
    if decision.needs_approval:
        approvals.request(user_id=user_id, action="book_service", payload=payload, reason=decision.reason,
                          summary=f"{chosen['name']}, {money_str(chosen['price'])}, {chosen['time']}")
        _svc_set(user_id, stage="needs_approval", chosen=chosen, action_id="")
        return speak(
            f"I'd like to check with {decision.family_name} before booking that one.",
            data={"category": "home_service", "outcome": "needs_approval"},
        )
    action_id = pending.create("book_service", user_id, **payload)
    _svc_set(user_id, stage="ready", chosen=chosen, action_id=action_id)
    return speak(
        f"{chosen['name']} can come {chosen['time']} for {money_str(chosen['price'])}. Should I book them?",
        action_id=action_id,
        data={"category": "home_service", "outcome": "ready"},
    )


def _start_booking(user_id: str, payload: dict, call_loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """Book on TaskHare in the browser, continuing on the parked results page when there is one."""
    provider_name = str(payload.get("provider") or "the tasker")
    when = str(payload.get("time") or "the next available time")
    price = float(payload.get("price") or 0)
    category = str(payload.get("category") or "home")
    _svc_set(user_id, stage="booking", chosen={"name": provider_name, "price": price, "time": when}, action_id="")
    caller = _caller_name(user_id)
    notify.notify_family(user_id, f"{caller} asked to book {provider_name} for {when}. The request to book has been started.")
    activity.log_event(user_id, "service_requested", f"Started a booking for {provider_name}.", {"category": "home_service", "outcome": "booking"})
    goal = (
        f"On TaskHare, hire {provider_name} for {category} help. The visit should be {when}. "
        f"Click the link Choose {provider_name}, click the time {when}, then click Confirm this visit. "
        "Stop when the page heading says You're booked. Do not invent a tasker or a time."
    )

    def on_done(job) -> None:
        if getattr(job, "status", None) == "cancelled":
            return
        success = getattr(job, "status", None) == "done"
        if success:
            try:
                db.get_client().table("service_bookings").insert({
                    "user_id": user_id,
                    "category": category,
                    "provider": provider_name,
                    "scheduled_at": slot_to_iso(when, tz=_caller_timezone(user_id)),
                    "price": price,
                    "status": "booked",
                    "external_id": getattr(job, "id", "") or "taskhare",
                }).execute()
            except Exception:  # noqa: BLE001
                log.exception("failed to record service booking for %s", user_id)
        _svc_set(user_id, stage="booked" if success else "error")
        activity.log_event(
            user_id,
            "service_booking",
            f"Booked {provider_name} for {when}" if success else f"Booking {provider_name} failed",
            {"category": "home_service", "outcome": "booked" if success else "error"},
        )
        notify.notify_family(
            user_id,
            f"{provider_name} is booked for {when} at the home." if success else f"Sorry, the booking with {provider_name} didn't go through.",
        )
        message = (
            f"You're booked. {provider_name} will come {when}." if success else f"I had trouble booking {provider_name}. Want me to try again?"
        )
        _speak_into_call(call_loop, user_id, message, behavior="queue")

    _runner().submit(
        site="taskhare", goal=goal, user_id=user_id, replay=False, page_name=str(payload.get("problem") or provider_name),
        on_done=on_done, on_progress=_progress_callback(call_loop, user_id, f"I'm still booking {provider_name}."),
    )


@orders.tool()
def confirm_service_booking(user_id: str, action_id: str = "") -> str:
    """Book the tasker that was read back, after the caller clearly says yes. The action id may be left blank."""
    sess = _svc_session(user_id)
    action_id = (action_id or "").strip() or (sess.get("action_id", "") if sess else "")
    try:
        payload = pending.consume(action_id, "book_service", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "home_service", "outcome": "error"})
    _start_booking(user_id, payload, _call_loop())
    return speak(
        f"I'm booking {payload['provider']} on TaskHare for {payload.get('time') or 'the next available time'}. I'll tell you how it's going.",
        data={"category": "home_service", "outcome": "booking"},
    )


def _execute_book_service(approval) -> str:
    """Family replied YES to a held booking: book it the same way a spoken yes would."""
    payload = dict(approval.payload or {})
    _start_booking(approval.user_id, payload, _call_loop())
    return f"Approved. Booking {payload.get('provider', 'the tasker')} for {payload.get('time', 'the next time')} now; we'll text you when it's done."


ACTION_EXECUTORS["book_service"] = _execute_book_service
