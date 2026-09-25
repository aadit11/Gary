"""Seed the demo user, family contact, known payees, bills, and a favorite order.

Run from backend/:  uv run python scripts/seed_demo_user.py
Idempotent: reuses the user if the phone already exists. Prints DEMO_USER_ID for .env.

Edit DEMO below to match the team's shared demo persona and the real family phone.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402

DEMO = {
    "user": {
        "name": "Margaret Chen",
        "phone": "+15550100001",  # the demo caller's phone (Grandma)
        "address": "12 Oak Lane, Springfield",
        "timezone": "America/New_York",
    },
    "family": {"name": "David", "phone": "+13154804465", "relationship": "son", "can_approve": True},
    "known_payees": [
        {"name": "City Electric", "kind": "biller"},
        {"name": "Sunrise Pharmacy", "kind": "biller"},
        {"name": "Springfield Water", "kind": "biller"},
    ],
    "bills": [
        {"payee": "City Electric", "amount": 84.20, "due_date": "2026-10-02"},
        {"payee": "Sunrise Pharmacy", "amount": 23.50, "due_date": "2026-10-05"},
    ],
    "favorite": {
        "label": "my usual soup",
        "vendor": "Pho House",
        "items": [{"name": "Chicken noodle soup", "qty": 1, "price": 12.50}, {"name": "Spring rolls", "qty": 1, "price": 6.00}],
        "total": 18.50,
    },
}


def main() -> None:
    client = db.get_client()
    existing = client.table("users").select("*").eq("phone", DEMO["user"]["phone"]).limit(1).execute().data
    if existing:
        user = existing[0]
        print(f"user exists: {user['id']}")
    else:
        user = client.table("users").insert(DEMO["user"]).execute().data[0]
        print(f"created user: {user['id']}")
    uid = user["id"]

    if not client.table("family_contacts").select("*").eq("user_id", uid).execute().data:
        client.table("family_contacts").insert({**DEMO["family"], "user_id": uid}).execute()
        print("created family contact")
    if not client.table("known_payees").select("*").eq("user_id", uid).execute().data:
        client.table("known_payees").insert([{**p, "user_id": uid} for p in DEMO["known_payees"]]).execute()
        print("created known payees")
    if not client.table("bills").select("*").eq("user_id", uid).execute().data:
        client.table("bills").insert([{**b, "user_id": uid, "status": "due"} for b in DEMO["bills"]]).execute()
        print("created bills")
    if not client.table("favorites").select("*").eq("user_id", uid).execute().data:
        client.table("favorites").insert({**DEMO["favorite"], "user_id": uid}).execute()
        print("created favorite")

    print(f"\nDEMO_USER_ID={uid}")


if __name__ == "__main__":
    main()
