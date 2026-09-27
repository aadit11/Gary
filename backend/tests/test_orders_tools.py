
import asyncio
import json
import sys

import pytest

import sys

import mcp_servers.orders  # importing it here guarantees sys.modules has the real module

# NOT "from mcp_servers import orders" or "import mcp_servers.orders as orders" - both resolve
# through attribute access on the `mcp_servers` package, and mcp_servers/__init__.py's own
# `from mcp_servers.orders import orders` permanently rebinds that attribute to the FastMCP
# server instance (which has no .get_favorite_orders etc.). Pulling the module straight out of
# sys.modules by its dotted key sidesteps that attribute entirely and gets the real module.
orders = sys.modules["mcp_servers.orders"]


# --- fakes for the browser agent -------------------------------------------

class FakeJob:
    def __init__(self, status="done", result_text="DONE: Ordered Tomato Basil Soup, total $8.50"):
        self.status = status
        self.result_text = result_text


class FakeBrowserRunner:
    """Captures submit() calls; finish() lets a test trigger on_done manually
    instead of actually driving a browser."""

    def submit(self, site, goal, user_id, flow_key=None, on_done=None, on_progress=None, replay=True, lookup=False, park=False, page_name="", park_when="", **_kw):
        self.submitted.append({"site": site, "goal": goal, "user_id": user_id, "flow_key": flow_key, "lookup": lookup})
        self._last_on_done = on_done
        self.on_progress = on_progress

    def cancel_for_user(self, user_id):
        self.cancelled.append(user_id)

    def __init__(self):
        self.submitted = []
        self.cancelled = []
        self._last_on_done = None

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


# --- fakes for clients/mock_services.py -------------------------------------

FOOD_ITEM = {"id": "f2", "name": "Tomato Basil Soup", "vendor": "Souvla", "price": 8.50}
PROVIDER = {"id": "p1", "name": "Ace Plumbing", "category": "plumber", "price": 89.0,
            "next_slots": ["2026-09-28T10:00:00"]}


@pytest.fixture(autouse=True)
def patch_mock_services(monkeypatch):
    monkeypatch.setattr("clients.mock_services.search_food_catalog", lambda q: [FOOD_ITEM])
    monkeypatch.setattr("clients.mock_services.get_food_item", lambda item_id: FOOD_ITEM if item_id == "f2" else None)
    monkeypatch.setattr("clients.mock_services.search_services", lambda q: {"category": "plumber", "providers": [PROVIDER]})
    monkeypatch.setattr(
        "clients.mock_services.create_service_booking",
        lambda provider_id, time, problem="": {"booking_id": "BK-123", "provider": "Ace Plumbing",
                                                 "category": "plumber", "time": time, "price": 89.0},
    )


def _say(json_str: str) -> str:
    return json.loads(json_str)["say"]


def _data(json_str: str) -> dict:
    return json.loads(json_str).get("data", {})


# --- favorites ---------------------------------------------------------------

def test_get_favorite_orders_empty(demo):
    result = orders.get_favorite_orders(demo["user_id"])
    assert "don't have any" in _say(result).lower()
    assert _data(result)["outcome"] == "resolved"


def test_get_favorite_orders_lists_saved_favorite(demo, fake_db):
    fake_db.table("favorites").insert(
        {"user_id": demo["user_id"], "label": "my usual soup", "vendor": "Souvla", "total": 8.50}
    ).execute()
    result = orders.get_favorite_orders(demo["user_id"])
    assert "my usual soup" in _say(result)


# --- food & groceries ---------------------------------------------------------

def test_new_search_stops_the_order_being_placed(demo, fake_runner):
    orders.search_food_and_groceries(demo["user_id"], restaurant="Panera Bread")
    assert fake_runner.cancelled == [demo["user_id"]]


def _mark_open(user_id, restaurant="Panera Bread"):
    orders._restaurant_status[(user_id, restaurant.casefold())] = "open"


def test_search_restaurant_checks_before_asking_for_a_dish(demo, fake_runner):
    result = orders.search_food_and_groceries(demo["user_id"], restaurant="Panera Bread")
    say = _say(result).lower()
    assert "checking" in say and "panera bread" in say
    assert "what would you like" not in say
    assert fake_runner.submitted[0]["lookup"] is True
    assert "DONE: OPEN" in fake_runner.submitted[0]["goal"]
    assert "do not place an order" in fake_runner.submitted[0]["goal"].lower()


def test_closed_restaurant_does_not_ask_for_a_dish(demo, fake_runner):
    orders.search_food_and_groceries(demo["user_id"], restaurant="Panera Bread")
    fake_runner.finish(FakeJob(status="done", result_text="DONE: CLOSED. Panera Bread is closed."))
    result = orders.prepare_order(demo["user_id"], restaurant="Panera Bread", item="broccoli cheddar soup")
    say = _say(result).lower()
    assert "closed" in say
    assert "what would you like" not in say
    assert "action_id" not in json.loads(result)


@pytest.mark.asyncio
async def test_open_restaurant_then_asks_for_the_dish(demo, fake_runner):
    from voice.bridge import ACTIVE_SESSIONS

    class FakeSession:
        def __init__(self):
            self.injected = []
            self.order_updates_paused = False

        async def inject(self, text, behavior="interrupt"):
            self.injected.append(text)

    session = FakeSession()
    ACTIVE_SESSIONS[demo["user_id"]] = session
    try:
        orders.search_food_and_groceries(demo["user_id"], restaurant="Panera Bread")
        fake_runner.finish(FakeJob(status="done", result_text="DONE: OPEN. Panera Bread can take a delivery order."))
        await asyncio.sleep(0.05)
        assert any("what would you like" in line.lower() for line in session.injected)
        prepared = json.loads(orders.prepare_order(demo["user_id"], restaurant="Panera Bread", item="broccoli cheddar soup"))
        assert prepared["action_id"]
        assert "broccoli cheddar soup" in prepared["say"]
    finally:
        ACTIVE_SESSIONS.pop(demo["user_id"], None)


def test_search_dish_asks_for_the_restaurant(demo):
    result = orders.search_food_and_groceries(demo["user_id"], dish="pizza")
    say = _say(result).lower()
    assert "pizza" in say and "which restaurant" in say


def test_prepare_order_by_description_creates_pending_action(demo):
    _mark_open(demo["user_id"])
    result = json.loads(orders.prepare_order(demo["user_id"], restaurant="Panera Bread", item="broccoli cheddar soup"))
    assert result["action_id"]
    assert "broccoli cheddar soup" in result["say"] and "Panera Bread" in result["say"]


def test_prepare_order_without_a_dish_asks(demo):
    _mark_open(demo["user_id"])
    result = orders.prepare_order(demo["user_id"], restaurant="Panera Bread")
    assert "what would you like" in _say(result).lower()
    assert "action_id" not in json.loads(result)
    assert _data(result)["outcome"] == "error"


def test_prepare_order_scam_request_needs_approval(demo):
    _mark_open(demo["user_id"], "Corner Store")
    result = orders.prepare_order(demo["user_id"], restaurant="Corner Store", item="a stack of gift cards")
    assert "checking with" in _say(result).lower()
    assert _data(result)["outcome"] == "needs_approval"


def test_confirm_order_rejects_unknown_action_id(demo):
    result = orders.confirm_order(demo["user_id"], "not-a-real-id")
    assert _data(result)["outcome"] == "error"


def test_confirm_order_submits_browser_job(demo, fake_runner, monkeypatch):
    notes = []
    monkeypatch.setattr(orders.notify, "notify_family", lambda *args, **kwargs: notes.append(args) or [])
    _mark_open(demo["user_id"])
    prepared = json.loads(orders.prepare_order(demo["user_id"], restaurant="Panera Bread", item="tomato soup"))
    result = orders.confirm_order(demo["user_id"], prepared["action_id"])

    assert "placing" in _say(result).lower() and "doordash" in _say(result).lower()
    assert fake_runner.submitted[0]["site"] == "dashdish"
    assert "tomato soup" in fake_runner.submitted[0]["goal"]
    assert "Panera Bread" in fake_runner.submitted[0]["goal"]
    assert notes and "started" in notes[0][1]

    # Simulate the background browser job finishing successfully.
    fake_runner.finish(FakeJob(status="done"))


def test_confirm_order_records_result_in_orders_table(demo, fake_runner, fake_db):
    _mark_open(demo["user_id"])
    prepared = json.loads(orders.prepare_order(demo["user_id"], restaurant="Panera Bread", item="tomato soup"))
    orders.confirm_order(demo["user_id"], prepared["action_id"])
    fake_runner.finish(FakeJob(status="done"))

    rows = fake_db.table("orders").select("*").eq("user_id", demo["user_id"]).execute().data
    assert len(rows) == 1
    assert rows[0]["status"] == "placed"
    assert rows[0]["vendor"] == "Panera Bread"


def test_confirm_order_records_failure(demo, fake_runner, fake_db):
    _mark_open(demo["user_id"])
    prepared = json.loads(orders.prepare_order(demo["user_id"], restaurant="Panera Bread", item="tomato soup"))
    orders.confirm_order(demo["user_id"], prepared["action_id"])
    fake_runner.finish(FakeJob(status="failed", result_text=""))

    rows = fake_db.table("orders").select("*").eq("user_id", demo["user_id"]).execute().data
    assert rows[0]["status"] == "failed"


def test_confirm_order_cannot_be_reused(demo, fake_runner):
    _mark_open(demo["user_id"])
    prepared = json.loads(orders.prepare_order(demo["user_id"], restaurant="Panera Bread", item="tomato soup"))
    orders.confirm_order(demo["user_id"], prepared["action_id"])
    fake_runner.finish(FakeJob(status="done"))

    second = orders.confirm_order(demo["user_id"], prepared["action_id"])
    assert _data(second)["outcome"] == "error"


@pytest.mark.asyncio
async def test_confirm_order_speaks_result_into_live_call(demo, fake_runner, monkeypatch):
    """Runs inside a real event loop (asyncio_mode=auto), so confirm_order can capture it
    and the on_done callback can hop back onto it with run_coroutine_threadsafe."""
    from voice.bridge import ACTIVE_SESSIONS

    class FakeSession:
        def __init__(self):
            self.injected = []

        def __init__(self):
            self.injected = []
            self.behaviors = []
            self.order_updates_paused = False

        async def inject(self, text, behavior="interrupt"):
            self.injected.append(text)
            self.behaviors.append(behavior)

    session = FakeSession()
    ACTIVE_SESSIONS[demo["user_id"]] = session
    try:
        _mark_open(demo["user_id"])
        prepared = json.loads(orders.prepare_order(demo["user_id"], restaurant="Panera Bread", item="tomato soup"))
        orders.confirm_order(demo["user_id"], prepared["action_id"])
        # Progress lines are fixed reassurances on a timer, never the model's reasoning.
        fake_runner.on_progress("I am looking through the DoorDash menu for soup.")  # too early: silent
        assert not session.injected
        real_monotonic = orders.time.monotonic
        monkeypatch.setattr(orders.time, "monotonic", lambda: real_monotonic() + 13)
        fake_runner.on_progress("I need to analyze the current situation:")
        monkeypatch.setattr(orders.time, "monotonic", real_monotonic)
        session.order_updates_paused = True
        fake_runner.on_progress("The caller changed the subject, so this must not be spoken.")
        session.order_updates_paused = False
        await asyncio.sleep(0.05)
        fake_runner.finish(FakeJob(status="done"))
        await asyncio.sleep(0.05)  # let the loop process the scheduled inject()
        assert any("working on your order" in line.lower() for line in session.injected)
        assert not any("analyze" in line.lower() or "changed the subject" in line.lower() for line in session.injected)
        assert any("placed" in line.lower() for line in session.injected)
        assert session.behaviors and set(session.behaviors) == {"queue"}
    finally:
        ACTIVE_SESSIONS.pop(demo["user_id"], None)


# --- home services -------------------------------------------------------------

def test_find_home_service_returns_options(demo):
    result = orders.find_home_service(demo["user_id"], "my sink is leaking")
    say = _say(result)
    assert "Ace Plumbing" in say and "89.00" in say


def test_prepare_service_booking_happy_path(demo):
    result = json.loads(orders.prepare_service_booking(demo["user_id"], "p1", "plumber"))
    assert result["action_id"]
    assert "Ace Plumbing" in result["say"]


def test_prepare_service_booking_unknown_provider(demo):
    result = orders.prepare_service_booking(demo["user_id"], "does-not-exist", "plumber")
    assert _data(result)["outcome"] == "error"


def test_confirm_service_booking_happy_path(demo, fake_db):
    prepared = json.loads(orders.prepare_service_booking(demo["user_id"], "p1", "plumber"))
    confirmed = json.loads(orders.confirm_service_booking(demo["user_id"], prepared["action_id"]))
    assert "Ace Plumbing" in confirmed["say"]

    rows = fake_db.table("service_bookings").select("*").eq("user_id", demo["user_id"]).execute().data
    assert len(rows) == 1
    assert rows[0]["status"] == "booked"
    assert rows[0]["external_id"] == "BK-123"


def test_confirm_service_booking_rejects_unknown_action_id(demo):
    result = orders.confirm_service_booking(demo["user_id"], "not-a-real-id")
    assert _data(result)["outcome"] == "error"

# --- restaurant-name matching (a re-phrased name must not restart or cancel a lookup) ---

def test_normalize_restaurant_names():
    n = orders._normalize_restaurant
    assert n("Souvla") == "souvla"
    assert n("the Souvla restaurant on DoorDash") == "souvla"
    assert n("Pho House, please") == "pho house"
    assert n("The Restaurant") == "the restaurant"  # nothing but noise words: keep them


def test_rephrased_name_reuses_lookup_key():
    orders._restaurant_status.clear()
    k1 = orders._restaurant_key("u1", "Souvla")
    orders._restaurant_status[k1] = "checking"
    assert orders._restaurant_key("u1", "Souvla restaurant") == k1
    assert orders._restaurant_key("u1", "the Souvla place") == k1
    assert orders._restaurant_key("u2", "Souvla") != k1
    assert orders._restaurant_key("u1", "Pho House") == ("u1", "pho house")
    orders._restaurant_status.clear()


def test_second_mention_does_not_cancel_running_lookup(monkeypatch, demo):
    orders._restaurant_status.clear()
    runner = FakeBrowserRunner()
    import types
    monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(browser_runner=runner))))
    uid = demo["user_id"]
    json.loads(orders.search_food_and_groceries(uid, restaurant="Souvla", dish="cheeseburger"))
    assert len(runner.submitted) == 1 and runner.submitted[0]["lookup"]
    out = json.loads(orders.search_food_and_groceries(uid, restaurant="Souvla restaurant", dish="cheeseburger"))
    assert "still checking" in out["say"]
    out = json.loads(orders.prepare_order(uid, restaurant="the Souvla place", item="cheeseburger"))
    assert "still checking" in out["say"]
    assert len(runner.submitted) == 1, "a re-phrased name must not start a second lookup"
    # a cancelled lookup clears its status so a retry is possible
    runner.finish(FakeJob(status="cancelled", result_text=""))
    assert not orders._restaurant_status
    orders._restaurant_status.clear()
