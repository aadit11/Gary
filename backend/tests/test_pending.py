from datetime import datetime, timedelta, timezone

import pytest

from core import pending
from core.pending import PendingActionError


def test_create_then_consume_returns_payload(demo):
    aid = pending.create("pay_bill", demo["user_id"], bill_id="b1")
    assert pending.consume(aid, "pay_bill", demo["user_id"]) == {"bill_id": "b1"}


def test_consume_twice_rejected(demo):
    aid = pending.create("pay_bill", demo["user_id"], bill_id="b1")
    pending.consume(aid, "pay_bill", demo["user_id"])
    with pytest.raises(PendingActionError, match="already"):
        pending.consume(aid, "pay_bill", demo["user_id"])


def test_wrong_action_type_rejected(demo):
    aid = pending.create("pay_bill", demo["user_id"], bill_id="b1")
    with pytest.raises(PendingActionError):
        pending.consume(aid, "place_order", demo["user_id"])


def test_wrong_user_rejected(demo):
    aid = pending.create("pay_bill", demo["user_id"], bill_id="b1")
    with pytest.raises(PendingActionError):
        pending.consume(aid, "pay_bill", "someone-else")


def test_unknown_and_empty_ids_rejected(demo):
    with pytest.raises(PendingActionError):
        pending.consume("does-not-exist", "pay_bill", demo["user_id"])
    with pytest.raises(PendingActionError):
        pending.consume("", "pay_bill", demo["user_id"])


def test_expired_rejected(demo, fake_db):
    aid = pending.create("pay_bill", demo["user_id"], ttl_seconds=60, bill_id="b1")
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    fake_db.table("pending_actions").update({"expires_at": past}).eq("id", aid).execute()
    with pytest.raises(PendingActionError, match="expired"):
        pending.consume(aid, "pay_bill", demo["user_id"])


def test_rejected_consume_does_not_mark_used(demo, fake_db):
    aid = pending.create("pay_bill", demo["user_id"], bill_id="b1")
    with pytest.raises(PendingActionError):
        pending.consume(aid, "place_order", demo["user_id"])
    row = fake_db.table("pending_actions").select("*").eq("id", aid).execute().data[0]
    assert row["used_at"] is None
