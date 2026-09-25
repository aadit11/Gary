"""Shared fixtures: every test runs against the in-memory fake database, seeded with a demo user."""

import os

os.environ["GARY_FAKE_DB"] = "1"
os.environ["POLICY_SPENDING_LIMIT"] = "100"
os.environ.pop("TWILIO_ACCOUNT_SID", None)  # never send real SMS from tests

import pytest  # noqa: E402

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fake_db():
    client = db.use_fake()
    yield client


@pytest.fixture
def demo(fake_db):
    """Seed a demo user with one approver, two known payees, and two bills. Returns ids."""
    user = fake_db.table("users").insert(
        {"name": "Margaret Chen", "phone": "+15550100001", "address": "12 Oak Lane", "timezone": "America/New_York"}
    ).execute().data[0]
    family = fake_db.table("family_contacts").insert(
        {"user_id": user["id"], "name": "David", "phone": "+15550100002", "relationship": "son", "can_approve": True}
    ).execute().data[0]
    fake_db.table("known_payees").insert(
        [
            {"user_id": user["id"], "name": "City Electric", "kind": "biller"},
            {"user_id": user["id"], "name": "Sunrise Pharmacy", "kind": "biller"},
        ]
    ).execute()
    bills = fake_db.table("bills").insert(
        [
            {"user_id": user["id"], "payee": "City Electric", "amount": 84.20, "due_date": "2026-10-02", "status": "due"},
            {"user_id": user["id"], "payee": "Sunrise Pharmacy", "amount": 23.50, "due_date": "2026-10-05", "status": "due"},
        ]
    ).execute().data
    return {"user_id": user["id"], "family_id": family["id"], "family_phone": family["phone"], "bills": bills}
