import importlib
import json

import pytest

from clients import mock_services
from core import approvals, pending
from mcp_servers.money import (
    check_message_for_scam,
    confirm_bill_payment,
    confirm_payment_to_person,
    list_bills_due,
    list_suspicious_emails,
    prepare_bill_payment,
    prepare_payment_to_person,
)
from webhooks.sms import handle_reply

# mcp_servers/__init__.py rebinds the name `money` to the FastMCP object, so fetch the module.
money = importlib.import_module("mcp_servers.money")

def _out(s: str) -> dict:
    out = json.loads(s)
    assert "{" not in out["say"]
    return out


def _bill(demo, payee):
    return next(b for b in demo["bills"] if b["payee"] == payee)


def _bill_row(fake_db, bill_id):
    return fake_db.table("bills").select("*").eq("id", bill_id).execute().data[0]


def _kinds(fake_db, user_id):
    return [e["kind"] for e in fake_db.table("activity_log").select("*").eq("user_id", user_id).execute().data]


# --- list_bills_due ------------------------------------------------------------------------


def test_list_bills_due_reads_seeded_bills(demo):
    out = _out(list_bills_due(demo["user_id"]))
    assert "$84.20" in out["say"] and "City Electric" in out["say"]
    assert "Friday, October 2" in out["say"]
    assert len(out["data"]["bills"]) == 2


def test_list_bills_due_none(fake_db):
    u = fake_db.table("users").insert({"name": "Nobody", "phone": "+15550100010"}).execute().data[0]
    out = _out(list_bills_due(u["id"]))
    assert "don't have any bills" in out["say"]


# --- recurring bill: prepare -> read back -> confirm --------------------------------------


def test_prepare_bill_by_spoken_name_reads_back(demo):
    out = _out(prepare_bill_payment(demo["user_id"], "the electric bill"))
    assert out["action_id"]
    assert "$84.20 to City Electric" in out["say"] and "Should I pay it?" in out["say"]
    assert out["data"]["outcome"] == "read_back"


def test_prepare_bill_by_id(demo):
    bill = _bill(demo, "Sunrise Pharmacy")
    out = _out(prepare_bill_payment(demo["user_id"], bill["id"]))
    assert "Sunrise Pharmacy" in out["say"] and out["action_id"]


def test_prepare_unknown_bill(demo):
    out = _out(prepare_bill_payment(demo["user_id"], "gas company"))
    assert out["data"]["outcome"] == "not_found"
    assert "action_id" not in out


def test_confirm_pays_bill_logs_and_notifies(demo, fake_db, monkeypatch):
    sent = []
    monkeypatch.setattr(money.notify, "notify_family", lambda uid, msg, **kw: sent.append(msg) or [])
    prep = _out(prepare_bill_payment(demo["user_id"], "electric"))
    out = _out(confirm_bill_payment(demo["user_id"], prep["action_id"]))
    assert out["data"]["outcome"] == "paid"
    assert "I paid $84.20 to City Electric" in out["say"]
    row = _bill_row(fake_db, _bill(demo, "City Electric")["id"])
    assert row["status"] == "paid" and row["confirmation_id"].startswith("SIM-") and row["paid_at"]
    assert "bill_paid" in _kinds(fake_db, demo["user_id"])
    assert sent and "Margaret paid $84.20 to City Electric" in sent[0]


def test_confirm_twice_rejected(demo):
    prep = _out(prepare_bill_payment(demo["user_id"], "electric"))
    _out(confirm_bill_payment(demo["user_id"], prep["action_id"]))
    again = _out(confirm_bill_payment(demo["user_id"], prep["action_id"]))
    assert again["data"]["outcome"] == "error" and "already" in again["say"]


def test_confirm_rejects_wrong_user_and_bad_id(demo, fake_db):
    prep = _out(prepare_bill_payment(demo["user_id"], "electric"))
    other = fake_db.table("users").insert({"name": "Other", "phone": "+15550100011"}).execute().data[0]
    assert _out(confirm_bill_payment(other["id"], prep["action_id"]))["data"]["outcome"] == "error"
    assert _out(confirm_bill_payment(demo["user_id"], "not-a-real-id"))["data"]["outcome"] == "error"
    assert _bill_row(fake_db, _bill(demo, "City Electric")["id"])["status"] == "due"


def test_confirm_rejects_person_action_id(demo, fake_db):
    aid = pending.create("pay_person", demo["user_id"], recipient="x", amount=1)
    out = _out(confirm_bill_payment(demo["user_id"], aid))
    assert out["data"]["outcome"] == "error"


def test_confirm_expired_rejected(demo, fake_db):
    prep = _out(prepare_bill_payment(demo["user_id"], "electric"))
    fake_db.table("pending_actions").update({"expires_at": "2000-01-01T00:00:00+00:00"}).eq("id", prep["action_id"]).execute()
    out = _out(confirm_bill_payment(demo["user_id"], prep["action_id"]))
    assert "expired" in out["say"]


def test_confirm_bill_already_paid_elsewhere(demo, fake_db):
    prep = _out(prepare_bill_payment(demo["user_id"], "electric"))
    fake_db.table("bills").update({"status": "paid"}).eq("id", _bill(demo, "City Electric")["id"]).execute()
    out = _out(confirm_bill_payment(demo["user_id"], prep["action_id"]))
    assert "already taken care of" in out["say"]


def test_biller_failure_is_friendly(demo, fake_db, monkeypatch):
    def boom(*a, **k):
        raise mock_services.MockServiceError("down")

    monkeypatch.setattr(money.mock_services, "pay_bill", boom)
    prep = _out(prepare_bill_payment(demo["user_id"], "electric"))
    out = _out(confirm_bill_payment(demo["user_id"], prep["action_id"]))
    assert "couldn't reach the biller" in out["say"]
    assert _bill_row(fake_db, _bill(demo, "City Electric")["id"])["status"] == "due"


# --- anomalous bill: approval at request time ---------------------------------------------


def _make_electric_anomalous(fake_db, user_id):
    fake_db.table("bills").insert({"user_id": user_id, "payee": "City Electric", "amount": 40.00, "status": "paid"}).execute()


def test_anomalous_bill_requests_approval_immediately(demo, fake_db):
    _make_electric_anomalous(fake_db, demo["user_id"])
    out = _out(prepare_bill_payment(demo["user_id"], "electric"))
    assert out["data"]["outcome"] == "approval_requested"
    assert "action_id" not in out
    assert "check with David" in out["say"]
    rows = fake_db.table("approvals").select("*").eq("user_id", demo["user_id"]).execute().data
    assert len(rows) == 1 and rows[0]["action"] == "pay_bill" and rows[0]["status"] == "pending"
    assert rows[0]["payload"]["summary"] == "pay $84.20 to City Electric"
    assert "approval_requested" in _kinds(fake_db, demo["user_id"])
    assert _bill_row(fake_db, _bill(demo, "City Electric")["id"])["status"] == "due"


def test_repeat_request_does_not_text_family_twice(demo, fake_db):
    _make_electric_anomalous(fake_db, demo["user_id"])
    _out(prepare_bill_payment(demo["user_id"], "electric"))
    again = _out(prepare_bill_payment(demo["user_id"], "electric"))
    assert again["data"]["outcome"] == "approval_pending"
    assert len(fake_db.table("approvals").select("*").eq("user_id", demo["user_id"]).execute().data) == 1


def test_family_yes_pays_bill_then_call_hears_result(demo, fake_db):
    _make_electric_anomalous(fake_db, demo["user_id"])
    heard = []

    def on_resolved(approval):
        bill = _bill_row(fake_db, approval.payload["bill_id"])
        heard.append((approval.outcome, bill["status"]))

    approvals.register(on_resolved)
    _out(prepare_bill_payment(demo["user_id"], "electric"))
    reply = handle_reply(demo["family_phone"], "YES")
    assert "Paid $84.20 to City Electric" in reply
    assert _bill_row(fake_db, _bill(demo, "City Electric")["id"])["status"] == "paid"
    assert heard == [("executed", "paid")]


def test_family_no_leaves_bill_unpaid(demo, fake_db):
    _make_electric_anomalous(fake_db, demo["user_id"])
    _out(prepare_bill_payment(demo["user_id"], "electric"))
    reply = handle_reply(demo["family_phone"], "no")
    assert "won't" in reply
    assert _bill_row(fake_db, _bill(demo, "City Electric")["id"])["status"] == "due"
    assert "bill_paid" not in _kinds(fake_db, demo["user_id"])


def test_executor_failure_reports_failed_outcome(demo, fake_db, monkeypatch):
    _make_electric_anomalous(fake_db, demo["user_id"])

    def boom(*a, **k):
        raise mock_services.MockServiceError("down")

    monkeypatch.setattr(money.mock_services, "pay_bill", boom)
    outcomes = []
    approvals.register(lambda a: outcomes.append(a.outcome))
    _out(prepare_bill_payment(demo["user_id"], "electric"))
    reply = handle_reply(demo["family_phone"], "yes")
    assert "went wrong" in reply
    assert outcomes == ["failed"]


# --- payments to people -------------------------------------------------------------------


def test_irs_agent_goes_to_family_immediately(demo, fake_db):
    out = _out(prepare_payment_to_person(demo["user_id"], "the IRS agent", 500, "He said I owe back taxes"))
    assert out["data"]["outcome"] == "approval_requested"
    assert "action_id" not in out
    assert "David" in out["say"] and "tax agency" in out["say"]
    row = fake_db.table("approvals").select("*").eq("user_id", demo["user_id"]).execute().data[0]
    assert row["action"] == "pay_person" and row["payload"]["amount"] == 500


def test_irs_family_no_sends_nothing_and_call_hears_it(demo, fake_db):
    from voice import injection

    sentences = []
    approvals.register(lambda a: sentences.append(injection.approval_sentence(a)))
    _out(prepare_payment_to_person(demo["user_id"], "the IRS agent", 500, "He said I owe back taxes"))
    handle_reply(demo["family_phone"], "NO")
    assert "person_paid" not in _kinds(fake_db, demo["user_id"])
    assert sentences and "said not to send $500.00 to the IRS agent" in sentences[0]
    assert "David" in sentences[0]


def test_unknown_person_small_amount_still_needs_approval(demo):
    out = _out(prepare_payment_to_person(demo["user_id"], "Aunt Rose", 10))
    assert out["data"]["outcome"] == "approval_requested"
    assert "haven't paid before" in out["say"]


def test_known_person_under_limit_reads_back_and_sends(demo, fake_db, monkeypatch):
    monkeypatch.setattr(money.notify, "notify_family", lambda *a, **k: [])
    fake_db.table("known_payees").insert({"user_id": demo["user_id"], "name": "Sarah", "kind": "person"}).execute()
    prep = _out(prepare_payment_to_person(demo["user_id"], "Sarah", 15))
    assert prep["action_id"] and "$15.00 to Sarah" in prep["say"]
    out = _out(confirm_payment_to_person(demo["user_id"], prep["action_id"]))
    assert out["data"]["outcome"] == "paid"
    assert "person_paid" in _kinds(fake_db, demo["user_id"])


def test_known_person_over_hard_limit_needs_approval(demo, fake_db):
    fake_db.table("known_payees").insert({"user_id": demo["user_id"], "name": "Sarah", "kind": "person"}).execute()
    out = _out(prepare_payment_to_person(demo["user_id"], "Sarah", 25))
    assert out["data"]["outcome"] == "approval_requested"
    assert "$20 limit" in out["say"]


def test_person_family_yes_sends(demo, fake_db):
    fake_db.table("known_payees").insert({"user_id": demo["user_id"], "name": "Sarah", "kind": "person"}).execute()
    _out(prepare_payment_to_person(demo["user_id"], "Sarah", 25))
    reply = handle_reply(demo["family_phone"], "yes")
    assert "Sent $25.00 to Sarah" in reply
    assert "person_paid" in _kinds(fake_db, demo["user_id"])


def test_confirm_person_rejects_bill_action(demo):
    aid = pending.create("pay_bill", demo["user_id"], bill_id="x")
    assert _out(confirm_payment_to_person(demo["user_id"], aid))["data"]["outcome"] == "error"


def test_person_needs_details(demo):
    assert _out(prepare_payment_to_person(demo["user_id"], "", 0))["data"]["outcome"] == "needs_details"


# --- scam checks --------------------------------------------------------------------------


@pytest.fixture
def scam_emails(demo, fake_db):
    fake_db.table("emails").insert(
        [
            {"user_id": demo["user_id"], "gmail_id": "m1", "sender": "alerts@medicare-verify.example",
             "subject": "URGENT: Your Medicare will be suspended", "classification": "scam",
             "received_at": "2026-09-25T10:00:00+00:00", "extracted": {"scam_labels": ["a Medicare or Social Security scare"]}},
            {"user_id": demo["user_id"], "gmail_id": "m2", "sender": "customs@parcel-fees.example",
             "subject": "Unpaid package customs fee", "classification": "scam",
             "received_at": "2026-09-25T09:00:00+00:00", "extracted": {"scam_labels": ["a package fee scam"]}},
            {"user_id": demo["user_id"], "gmail_id": "b1", "sender": "billing@cityelectric.example",
             "subject": "Your City Electric bill is ready", "classification": "bill",
             "received_at": "2026-09-24T09:00:00+00:00", "extracted": {"payee": "City Electric", "amount": 84.2}},
        ]
    ).execute()


def test_list_suspicious_emails(scam_emails, demo):
    out = _out(list_suspicious_emails(demo["user_id"]))
    assert "2 emails" in out["say"]
    assert "Medicare" in out["say"] and "package fee" in out["say"]
    assert "Want me to tell David?" in out["say"]
    assert len(out["data"]["emails"]) == 2


def test_list_suspicious_emails_none(demo):
    assert "didn't see any" in _out(list_suspicious_emails(demo["user_id"]))["say"]


def test_is_this_email_real_matches_scam_email(scam_emails, demo, fake_db):
    out = _out(check_message_for_scam(demo["user_id"], "Is the Medicare email real?"))
    assert out["data"]["outcome"] == "scam_suspected"
    assert "That email looks like a Medicare" in out["say"]
    assert "scam_check" in _kinds(fake_db, demo["user_id"])


def test_is_this_email_real_matches_normal_bill(scam_emails, demo):
    out = _out(check_message_for_scam(demo["user_id"], "Is the City Electric email real?"))
    assert out["data"]["outcome"] == "no_flags"
    assert "City Electric" in out["say"]


def test_described_phone_call_scam(demo):
    out = _out(check_message_for_scam(demo["user_id"], "A man says my grandson is in jail and needs bail money"))
    assert out["data"]["outcome"] == "scam_suspected"
    assert "family emergency" in out["say"]


def test_no_warning_signs(demo):
    out = _out(check_message_for_scam(demo["user_id"], "My neighbor invited me to lunch"))
    assert out["data"]["outcome"] == "no_flags"
    assert "David" in out["say"]
