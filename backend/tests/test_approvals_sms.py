from core import approvals
from webhooks.sms import handle_reply


def test_request_creates_pending_row(demo, fake_db):
    aid = approvals.request(demo["user_id"], "pay_person", {"to": "IRS Agent", "amount": 500}, "this looks like a tax agency demanding payment")
    row = fake_db.table("approvals").select("*").eq("id", aid).execute().data[0]
    assert row["status"] == "pending"
    assert row["family_contact_id"] == demo["family_id"]


def test_yes_resolves_and_fires_callback(demo):
    seen = []
    approvals.register(seen.append)
    aid = approvals.request(demo["user_id"], "pay_bill", {"bill_id": "b1"}, "over limit")
    reply = handle_reply("(555) 010-0002", "Yes please")
    assert "approved" in reply.lower()
    assert approvals.get(aid).status == "approved"
    assert seen and seen[0].id == aid


def test_no_denies(demo):
    aid = approvals.request(demo["user_id"], "pay_person", {"to": "IRS"}, "scam")
    reply = handle_reply("+15550100002", "NO")
    assert "won't" in reply
    assert approvals.get(aid).status == "denied"


def test_unknown_phone_or_nothing_pending(demo):
    assert "nothing waiting" in handle_reply("+15550100002", "YES")
    approvals.request(demo["user_id"], "pay_bill", {}, "x")
    assert "nothing waiting" in handle_reply("+15550109999", "YES")


def test_ambiguous_reply_asks_again(demo):
    aid = approvals.request(demo["user_id"], "pay_bill", {}, "x")
    assert "YES" in handle_reply("+15550100002", "what is this?")
    assert approvals.get(aid).status == "pending"


def test_second_yes_after_resolution(demo):
    approvals.request(demo["user_id"], "pay_bill", {}, "x")
    handle_reply("+15550100002", "yes")
    assert "nothing waiting" in handle_reply("+15550100002", "yes")
