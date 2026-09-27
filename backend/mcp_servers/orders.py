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

Food orders execute on the DashDish clone via the browser agent (15-35s), so confirm_order
never blocks the call: it says "placing it now" immediately, and the background job's on_done
callback logs the result, texts family, and speaks the outcome into the live call if the user
is still on the phone. Home service bookings hit the mock API directly and are fast enough to
confirm synchronously.

NOTE for Person 1: voice/agent_settings.py's SERVERS_BY_REASON does not include "orders" for
any reason yet (not even "inbound"), so these tools aren't reachable on a live call until
that's added.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
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

@orders.tool()
def search_food_and_groceries(user_id: str, query: str) -> str:
    """Search restaurants and grocery items by name or craving and return a couple of options with prices."""
    try:
        results = mock_services.search_food_catalog(query)
    except Exception:  # noqa: BLE001
        log.exception("food catalog search failed")
        return speak("I couldn't check on that just now, want me to try again?", data={"category": "food_order", "outcome": "error"})

    if not results:
        return speak(
            f"I couldn't find anything matching {query}. Want to try something else?",
            data={"category": "food_order", "outcome": "resolved"},
        )

    top = results[:3]
    parts = [f"{r['name']} from {r['vendor']} for {money_str(r['price'])}" for r in top]
    if len(parts) == 1:
        say = f"I found {parts[0]}. Want me to order it?"
    else:
        say = "I found " + "; ".join(parts[:-1]) + f"; and {parts[-1]}. Which one?"

    data = [{"id": r["id"], "name": r["name"], "vendor": r["vendor"], "price": r["price"]} for r in top]
    return speak(say, data={"category": "food_order", "outcome": "resolved", "results": data})


@orders.tool()
def prepare_order(user_id: str, favorite_id: Optional[str] = None, catalog_item_id: Optional[str] = None) -> str:
    """Prepare to order a saved favorite or a catalog item found by search, and return the read-back."""
    if favorite_id:
        favorite = _get_favorite(user_id, favorite_id)
        if not favorite:
            return speak(
                "I couldn't find that favorite anymore. Want to tell me what you'd like instead?",
                data={"category": "food_order", "outcome": "error"},
            )
        item_name, vendor, price = favorite["label"], favorite["vendor"], float(favorite["total"] or 0)
    elif catalog_item_id:
        item = mock_services.get_food_item(catalog_item_id)
        if not item:
            return speak(
                "I couldn't find that item anymore. Want to search again?",
                data={"category": "food_order", "outcome": "error"},
            )
        item_name, vendor, price = item["name"], item["vendor"], float(item["price"])
    else:
        return speak(
            "I'm not sure which item you mean. Want to search for it or ask for your usual?",
            data={"category": "food_order", "outcome": "error"},
        )

    decision = policy.check(kind="order", payee=vendor, amount=price, user_id=user_id)
    if decision.needs_approval:
        approvals.request(
            user_id=user_id,
            action="place_order",
            payload={"item_name": item_name, "vendor": vendor, "price": price, "favorite_id": favorite_id},
            reason=decision.reason,
            summary=f"{item_name} from {vendor}, {money_str(price)}",
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
    return speak(
        f"That's {item_name} from {vendor} for {money_str(price)}, delivered to your home. Should I place it?",
        action_id=action_id,
        data={"category": "food_order"},
    )


@orders.tool()
def confirm_order(user_id: str, action_id: str) -> str:
    """Place a previously prepared food or grocery order after the user says yes."""
    try:
        payload = pending.consume(action_id, "place_order", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "food_order", "outcome": "error"})

    goal = f"Order {payload['item_name']} from {payload['vendor']} for delivery and place the order."
    flow_key = payload.get("favorite_id")

    # Captured now, while we're still on the FastAPI event loop (the MCP adapter awaits this
    # tool). on_done fires later on the browser agent's worker thread, which has no event loop
    # of its own, so it needs this one to hop back onto to speak into the live call.
    try:
        call_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
    except RuntimeError:
        call_loop = None
        log.warning("confirm_order for %s has no running event loop; result won't be spoken into a live call", user_id)

    def on_done(job) -> None:
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

        message = (
            f"Good news, your order from {payload['vendor']} is placed."
            if success else
            f"I had trouble placing your order from {payload['vendor']}. Want me to try again?"
        )
        if call_loop is not None:
            from voice.bridge import ACTIVE_SESSIONS  # deferred: avoids a circular import with mcp_servers

            session = ACTIVE_SESSIONS.get(user_id)
            if session is not None:
                try:
                    asyncio.run_coroutine_threadsafe(session.inject(message), call_loop)
                except Exception:  # noqa: BLE001
                    log.exception("failed to inject order result into live call for %s", user_id)
            else:
                log.info("order result ready for %s but they are not on a call; family was texted", user_id)

    app_module = importlib.import_module("main")  # deferred: main imports mcp_servers, which imports this file
    app_module.app.state.browser_runner.submit(
        site="dashdish",
        goal=goal,
        user_id=user_id,
        flow_key=flow_key,
        on_done=on_done,
    )

    return speak(
        f"Placing your order from {payload['vendor']} now, it'll take about a minute. I'll let you know when it's done.",
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
