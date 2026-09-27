
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

    def __init__(self):
        self.submitted = []
        self._last_on_done = None

    def submit(self, site, goal, user_id, flow_key=None, on_done=None):
        self.submitted.append({"site": site, "goal": goal, "user_id": user_id, "flow_key": flow_key})
        self._last_on_done = on_done

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

def test_search_food_and_groceries_returns_options(demo):
    result = orders.search_food_and_groceries(demo["user_id"], "soup")
    say = _say(result)
    assert "Tomato Basil Soup" in say and "Souvla" in say and "8.50" in say


def test_prepare_order_by_catalog_item_creates_pending_action(demo):
    result = json.loads(orders.prepare_order(demo["user_id"], catalog_item_id="f2"))
    assert result["action_id"]
    assert "8.50" in result["say"]


def test_prepare_order_unknown_item_is_friendly(demo):
    result = orders.prepare_order(demo["user_id"], catalog_item_id="does-not-exist")
    assert "couldn't find" in _say(result).lower()
    assert _data(result)["outcome"] == "error"


def test_prepare_order_over_limit_requests_approval(demo, monkeypatch):
    monkeypatch.setattr("clients.mock_services.get_food_item",
                         lambda item_id: {"id": "big", "name": "Fancy Feast", "vendor": "New Vendor", "price": 500.0})
    result = orders.prepare_order(demo["user_id"], catalog_item_id="big")
    assert "checking with" in _say(result).lower()
    assert _data(result)["outcome"] == "needs_approval"


def test_confirm_order_rejects_unknown_action_id(demo):
    result = orders.confirm_order(demo["user_id"], "not-a-real-id")
    assert _data(result)["outcome"] == "error"


def test_confirm_order_submits_browser_job(demo, fake_runner):
    prepared = json.loads(orders.prepare_order(demo["user_id"], catalog_item_id="f2"))
    result = orders.confirm_order(demo["user_id"], prepared["action_id"])

    assert "placing your order" in _say(result).lower()
    assert fake_runner.submitted[0]["site"] == "dashdish"
    assert "Tomato Basil Soup" in fake_runner.submitted[0]["goal"]

    # Simulate the background browser job finishing successfully.
    fake_runner.finish(FakeJob(status="done"))


def test_confirm_order_records_result_in_orders_table(demo, fake_runner, fake_db):
    prepared = json.loads(orders.prepare_order(demo["user_id"], catalog_item_id="f2"))
    orders.confirm_order(demo["user_id"], prepared["action_id"])
    fake_runner.finish(FakeJob(status="done"))

    rows = fake_db.table("orders").select("*").eq("user_id", demo["user_id"]).execute().data
    assert len(rows) == 1
    assert rows[0]["status"] == "placed"
    assert rows[0]["vendor"] == "Souvla"


def test_confirm_order_records_failure(demo, fake_runner, fake_db):
    prepared = json.loads(orders.prepare_order(demo["user_id"], catalog_item_id="f2"))
    orders.confirm_order(demo["user_id"], prepared["action_id"])
    fake_runner.finish(FakeJob(status="failed", result_text=""))

    rows = fake_db.table("orders").select("*").eq("user_id", demo["user_id"]).execute().data
    assert rows[0]["status"] == "failed"


def test_confirm_order_cannot_be_reused(demo, fake_runner):
    prepared = json.loads(orders.prepare_order(demo["user_id"], catalog_item_id="f2"))
    orders.confirm_order(demo["user_id"], prepared["action_id"])
    fake_runner.finish(FakeJob(status="done"))

    second = orders.confirm_order(demo["user_id"], prepared["action_id"])
    assert _data(second)["outcome"] == "error"


@pytest.mark.asyncio
async def test_confirm_order_speaks_result_into_live_call(demo, fake_runner):
    """Runs inside a real event loop (asyncio_mode=auto), so confirm_order can capture it
    and the on_done callback can hop back onto it with run_coroutine_threadsafe."""
    from voice.bridge import ACTIVE_SESSIONS

    class FakeSession:
        def __init__(self):
            self.injected = []

        async def inject(self, text, behavior="interrupt"):
            self.injected.append(text)

    session = FakeSession()
    ACTIVE_SESSIONS[demo["user_id"]] = session
    try:
        prepared = json.loads(orders.prepare_order(demo["user_id"], catalog_item_id="f2"))
        orders.confirm_order(demo["user_id"], prepared["action_id"])
        fake_runner.finish(FakeJob(status="done"))
        await asyncio.sleep(0.05)  # let the loop process the scheduled inject()
        assert session.injected and "placed" in session.injected[0].lower()
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