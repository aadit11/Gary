
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

    def submit(self, site, goal, user_id, flow_key=None, on_done=None, on_progress=None, replay=True, lookup=False, park=False, page_name="", park_when="", mode="", **_kw):
        self.submitted.append({"site": site, "goal": goal, "user_id": user_id, "flow_key": flow_key, "lookup": lookup, "mode": mode})
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


@pytest.fixture(autouse=True)
def patch_mock_services(monkeypatch):
    monkeypatch.setattr("clients.mock_services.search_food_catalog", lambda q: [FOOD_ITEM])
    monkeypatch.setattr("clients.mock_services.get_food_item", lambda item_id: FOOD_ITEM if item_id == "f2" else None)


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

def _runner_events(fake_runner):
    return [(j.get("mode"), j["goal"][:30]) for j in fake_runner.submitted]


def test_restaurant_only_starts_lookup_and_asks_for_dish(demo, fake_runner):
    orders._food.clear()
    out = json.loads(orders.search_food_and_groceries(demo["user_id"], restaurant="Wingstop"))
    assert "checking whether Wingstop" in out["say"] and "What would you like" in out["say"]
    assert fake_runner.submitted[-1]["lookup"] and fake_runner.submitted[-1]["mode"] == "lookup"


def test_rephrased_restaurant_does_not_restart(demo, fake_runner):
    orders._food.clear()
    orders.search_food_and_groceries(demo["user_id"], restaurant="Wingstop")
    out = json.loads(orders.search_food_and_groceries(demo["user_id"], restaurant="the Wingstop place"))
    assert "still checking" in out["say"] and len(fake_runner.submitted) == 1


def test_dish_after_open_stages_and_reads_back(demo, fake_runner):
    orders._food.clear()
    uid = demo["user_id"]
    orders.search_food_and_groceries(uid, restaurant="Wingstop")
    fake_runner.finish(FakeJob(status="done", result_text="DONE: OPEN. Wingstop can take a delivery order."))
    assert orders._food[uid]["stage"] == "open"
    out = json.loads(orders.search_food_and_groceries(uid, restaurant="Wingstop", dish="8 pc wings"))
    assert "getting the 8 pc wings ready" in out["say"]
    assert fake_runner.submitted[-1]["mode"] == "stage" and "Find 8 pc wings" in fake_runner.submitted[-1]["goal"]
    fake_runner.finish(FakeJob(status="done", result_text="STAGED: Buffalo Spicy Wings | $12.96"))
    sess = orders._food[uid]
    assert sess["stage"] == "staged" and sess["item"] == "Buffalo Spicy Wings" and sess["price"] == 12.96 and sess["action_id"]
    out = json.loads(orders.prepare_order(uid))
    assert "Buffalo Spicy Wings" in out["say"] and "$12.96" in out["say"] and out["action_id"] == sess["action_id"]


def test_restaurant_and_dish_together_chain_stage_after_open(demo, fake_runner):
    orders._food.clear()
    uid = demo["user_id"]
    out = json.loads(orders.search_food_and_groceries(uid, restaurant="Wingstop", dish="8 pc wings"))
    assert "looking for 8 pc wings" in out["say"]
    fake_runner.finish(FakeJob(status="done", result_text="DONE: OPEN. Wingstop can take a delivery order."))
    assert [m for m, _ in _runner_events(fake_runner)] == ["lookup", "stage"]


def test_closed_and_missing_do_not_stage(demo, fake_runner):
    orders._food.clear()
    uid = demo["user_id"]
    orders.search_food_and_groceries(uid, restaurant="Panera", dish="soup")
    fake_runner.finish(FakeJob(status="done", result_text="DONE: MISSING. Panera is not on DoorDash."))
    assert orders._food[uid]["stage"] == "missing" and len(fake_runner.submitted) == 1
    out = json.loads(orders.search_food_and_groceries(uid, restaurant="Panera"))
    assert "not on DoorDash" in out["say"]


def test_confirm_places_on_parked_checkout_and_records(demo, fake_runner):
    orders._food.clear()
    uid = demo["user_id"]
    orders.search_food_and_groceries(uid, restaurant="Wingstop", dish="wings")
    fake_runner.finish(FakeJob(status="done", result_text="DONE: OPEN. Wingstop can take a delivery order."))
    fake_runner.finish(FakeJob(status="done", result_text="STAGED: Buffalo Spicy Wings | $12.96"))
    out = json.loads(orders.confirm_order(uid))  # blank action id -> staged one
    assert "Placing the Buffalo Spicy Wings" in out["say"]
    assert fake_runner.submitted[-1]["mode"] == "place"
    fake_runner.finish(FakeJob(status="done", result_text="DONE: Order placed, order id ORD-123456789"))
    rows = orders.db.get_client().table("orders").select("*").eq("user_id", uid).execute().data
    assert rows and rows[-1]["status"] == "placed" and rows[-1]["external_id"] == "ORD-123456789"
    # the pending action was consumed: a second yes is rejected
    out = json.loads(orders.confirm_order(uid))
    assert "already" in out["say"] or "start" in out["say"].lower()


def test_confirm_without_staged_order_is_rejected(demo, fake_runner):
    orders._food.clear()
    out = json.loads(orders.confirm_order(demo["user_id"]))
    assert "say" in out and not fake_runner.submitted


def test_staged_price_over_limit_needs_approval(demo, fake_runner, monkeypatch):
    orders._food.clear()
    uid = demo["user_id"]
    monkeypatch.setattr(orders.approvals, "request", lambda **kw: "apr-1")
    orders.search_food_and_groceries(uid, restaurant="Wingstop", dish="party pack")
    fake_runner.finish(FakeJob(status="done", result_text="DONE: OPEN. Wingstop can take a delivery order."))
    fake_runner.finish(FakeJob(status="done", result_text="STAGED: 100 Piece Party Pack | $180.00"))
    assert orders._food[uid]["stage"] == "needs_approval" and not orders._food[uid]["action_id"]


def test_stage_failure_is_reported(demo, fake_runner):
    orders._food.clear()
    uid = demo["user_id"]
    orders.search_food_and_groceries(uid, restaurant="Wingstop", dish="sushi")
    fake_runner.finish(FakeJob(status="done", result_text="DONE: OPEN. Wingstop can take a delivery order."))
    fake_runner.finish(FakeJob(status="infeasible", result_text="nothing like that"))
    assert orders._food[uid]["stage"] == "error"


def test_new_restaurant_cancels_and_replaces_session(demo, fake_runner):
    orders._food.clear()
    uid = demo["user_id"]
    orders.search_food_and_groceries(uid, restaurant="Wingstop", dish="wings")
    orders.search_food_and_groceries(uid, restaurant="Souvla", dish="cheeseburger")
    assert fake_runner.cancelled and orders._food[uid]["restaurant"] == "Souvla"


def test_prepare_order_with_favorite_starts_lookup(demo, fake_runner):
    orders._food.clear()
    uid = demo["user_id"]
    fav = orders.db.get_client().table("favorites").insert({"user_id": uid, "label": "my usual soup", "vendor": "Pho House", "total": 18.5}).execute().data[0]
    out = json.loads(orders.prepare_order(uid, favorite_id=fav["id"]))
    assert "looking for my usual soup at Pho House" in out["say"]
    assert fake_runner.submitted[-1]["mode"] == "lookup"


# --- home services: TaskHare, through the browser ----------------------------

TASKERS_DONE = "DONE: TASKERS [Plumbing]: Bay Plumbing Co. | $120 | Monday, September 28 at 10 AM || Rapid Rooter | $95 | Monday, September 28 at 4 PM"
RESULTS_PAGE = """[42] heading 'Plumbing'
[43] list ''
\t[44] listitem ''
\t\t[45] heading 'Bay Plumbing Co.'
\t\t[46] paragraph ''
\t\t\tStaticText '4.8'
\t\t\tStaticText 'stars · $'
\t\t\tStaticText '120'
\t\t\tStaticText 'visit · next'
\t\t\tStaticText 'Monday, September 28 at 10 AM'
\t\t[47] link 'Choose Bay Plumbing Co.', url='http://127.0.0.1:3000/taskhare/hire/p1'
"""


def _heard(monkeypatch):
    lines = []
    monkeypatch.setattr(orders, "_speak_into_call", lambda loop, uid, msg, behavior="queue": lines.append(msg))
    return lines


def _found(demo, fake_runner, monkeypatch):
    orders._services.clear()
    heard = _heard(monkeypatch)
    orders.find_home_service(demo["user_id"], "my sink is leaking")
    fake_runner.finish(FakeJob(status="done", result_text=TASKERS_DONE))
    return heard


def test_find_home_service_searches_taskhare_in_browser(demo, fake_runner, monkeypatch):
    orders._services.clear()
    heard = _heard(monkeypatch)
    out = json.loads(orders.find_home_service(demo["user_id"], "my sink is leaking"))
    assert "look on TaskHare" in out["say"] and out["data"]["outcome"] == "searching"
    job = fake_runner.submitted[-1]
    assert job["site"] == "taskhare" and job["lookup"] and job["mode"] == "taskers" and "my sink is leaking" in job["goal"]
    fake_runner.finish(FakeJob(status="done", result_text=TASKERS_DONE))
    sess = orders._services[demo["user_id"]]
    assert sess["stage"] == "found" and [o["name"] for o in sess["options"]] == ["Bay Plumbing Co.", "Rapid Rooter"]
    assert "two plumbers" in heard[-1] and "$120.00" in heard[-1] and "Monday, September 28 at 4 PM" in heard[-1] and "Who would you like?" in heard[-1]


def test_find_home_service_reads_the_page_when_the_summary_is_off(demo, fake_runner, monkeypatch):
    orders._services.clear()
    heard = _heard(monkeypatch)
    orders.find_home_service(demo["user_id"], "my sink is leaking")
    job = FakeJob(status="done", result_text="DONE: I found some plumbers.")
    job.final_text = RESULTS_PAGE
    fake_runner.finish(job)
    sess = orders._services[demo["user_id"]]
    assert sess["stage"] == "found" and sess["options"][0]["name"] == "Bay Plumbing Co." and sess["category"] == "Plumbing"
    assert "one plumber" in heard[-1] and "Want me to book them?" in heard[-1]


def test_find_home_service_none_found(demo, fake_runner, monkeypatch):
    orders._services.clear()
    heard = _heard(monkeypatch)
    orders.find_home_service(demo["user_id"], "teach my parrot to sing")
    fake_runner.finish(FakeJob(status="done", result_text="DONE: TASKERS [Handyman]: none"))
    assert orders._services[demo["user_id"]]["stage"] == "none" and "couldn't find anyone" in heard[-1]


def test_find_home_service_failure_is_reported(demo, fake_runner, monkeypatch):
    orders._services.clear()
    heard = _heard(monkeypatch)
    orders.find_home_service(demo["user_id"], "my sink is leaking")
    fake_runner.finish(FakeJob(status="failed", result_text=""))
    assert orders._services[demo["user_id"]]["stage"] == "error" and "try again" in heard[-1]


def test_repeat_problem_while_searching_does_not_restart(demo, fake_runner):
    orders._services.clear()
    orders.find_home_service(demo["user_id"], "my sink is leaking")
    out = json.loads(orders.find_home_service(demo["user_id"], "My sink is leaking!"))
    assert "still looking" in out["say"] and len(fake_runner.submitted) == 1


def test_prepare_service_booking_by_name_reads_back(demo, fake_runner, monkeypatch):
    _found(demo, fake_runner, monkeypatch)
    out = json.loads(orders.prepare_service_booking(demo["user_id"], "rapid rooter"))
    assert out["action_id"] and "Rapid Rooter can come Monday, September 28 at 4 PM for $95.00. Should I book them?" == out["say"]


def test_prepare_service_booking_over_limit_needs_family(demo, fake_db, fake_runner, monkeypatch):
    _found(demo, fake_runner, monkeypatch)
    out = json.loads(orders.prepare_service_booking(demo["user_id"], "the first one"))  # Bay Plumbing, $120 > $100 limit
    assert out["data"]["outcome"] == "needs_approval" and "David" in out["say"] and not out.get("action_id")
    rows = fake_db.table("approvals").select("*").eq("user_id", demo["user_id"]).execute().data
    assert rows and rows[-1]["action"] == "book_service" and rows[-1]["payload"]["provider"] == "Bay Plumbing Co."


def test_prepare_service_booking_unknown_name_asks_again(demo, fake_runner, monkeypatch):
    _found(demo, fake_runner, monkeypatch)
    out = json.loads(orders.prepare_service_booking(demo["user_id"], "Golden Gate"))
    assert "Which one would you like" in out["say"] and "Bay Plumbing Co." in out["say"] and not out.get("action_id")


def test_prepare_before_search_asks_for_the_problem(demo):
    orders._services.clear()
    out = json.loads(orders.prepare_service_booking(demo["user_id"], "Bay Plumbing"))
    assert out["data"]["outcome"] == "error" and "TaskHare" in out["say"]


def test_confirm_service_booking_continues_in_browser_and_records(demo, fake_db, fake_runner, monkeypatch):
    heard = _found(demo, fake_runner, monkeypatch)
    prepared = json.loads(orders.prepare_service_booking(demo["user_id"], "Rapid Rooter"))
    confirmed = json.loads(orders.confirm_service_booking(demo["user_id"], prepared["action_id"]))
    assert "booking Rapid Rooter on TaskHare" in confirmed["say"]
    job = fake_runner.submitted[-1]
    assert job["site"] == "taskhare" and not job["lookup"] and "Choose Rapid Rooter" in job["goal"] and "Monday, September 28 at 4 PM" in job["goal"]
    fake_runner.finish(FakeJob(status="done", result_text="DONE: Rapid Rooter hired for plumbing on Monday, September 28 at 4 PM for $95."))
    rows = fake_db.table("service_bookings").select("*").eq("user_id", demo["user_id"]).execute().data
    assert len(rows) == 1 and rows[0]["status"] == "booked" and rows[0]["provider"] == "Rapid Rooter"
    assert rows[0]["scheduled_at"].endswith("-09-28T16:00:00-04:00")  # the demo user is in America/New_York
    assert heard[-1] == "You're booked. Rapid Rooter will come Monday, September 28 at 4 PM."
    # the pending action was consumed: a second yes is rejected
    again = json.loads(orders.confirm_service_booking(demo["user_id"]))
    assert again["data"]["outcome"] == "error"


def test_confirm_with_blank_action_id_uses_the_prepared_one(demo, fake_runner, monkeypatch):
    _found(demo, fake_runner, monkeypatch)
    orders.prepare_service_booking(demo["user_id"], "Rapid Rooter")
    out = json.loads(orders.confirm_service_booking(demo["user_id"]))
    assert "booking Rapid Rooter" in out["say"] and fake_runner.submitted[-1]["site"] == "taskhare"


def test_confirm_service_booking_rejects_unknown_action_id(demo, fake_runner):
    orders._services.clear()
    result = orders.confirm_service_booking(demo["user_id"], "not-a-real-id")
    assert _data(result)["outcome"] == "error" and not fake_runner.submitted


def test_family_yes_books_the_held_service(demo, fake_db, fake_runner, monkeypatch):
    from webhooks.sms import handle_reply

    _found(demo, fake_runner, monkeypatch)
    orders.prepare_service_booking(demo["user_id"], "Bay Plumbing")
    reply = handle_reply(demo["family_phone"], "YES")
    assert "Booking Bay Plumbing Co." in reply
    job = fake_runner.submitted[-1]
    assert job["site"] == "taskhare" and not job["lookup"] and "Choose Bay Plumbing Co." in job["goal"]
    assert orders._services[demo["user_id"]]["stage"] == "booking"
