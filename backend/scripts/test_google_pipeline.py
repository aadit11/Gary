"""End-to-end pipeline smoke test (no Google/Supabase credentials required).

Simulates: seed user -> seed inbox messages -> ingest -> verify emails/bills/activity
-> list_bills_due -> calendar list_upcoming (mocked) -> re-ingest idempotency.

Run:  uv run python scripts/test_google_pipeline.py
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

os.environ["GARY_FAKE_DB"] = "1"
os.environ.pop("SUPABASE_URL", None)

from core import db  # noqa: E402
from google.calendar import list_upcoming  # noqa: E402
from google.demo_emails import DEMO_EMAILS, DOCTOR_EVENT  # noqa: E402
from google.ingestion import run  # noqa: E402
from mcp_servers.money import list_bills_due  # noqa: E402


def _raw(mid: str, subject: str, body: str, sender: str) -> dict:
    data = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return {
        "id": mid,
        "threadId": "t",
        "snippet": body[:80],
        "internalDate": "1758758400000",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "X-Gary-Seed", "value": "1"},
            ],
            "mimeType": "text/plain",
            "body": {"data": data},
        },
    }


class _Exec:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data


class FakeGmail:
    def __init__(self, store: list[dict]):
        self._store = store

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q=None, maxResults=50):
        return _Exec({"messages": [{"id": m["id"]} for m in self._store[:maxResults]]})

    def get(self, userId, id, format="full"):
        return _Exec(next(m for m in self._store if m["id"] == id))


def seed_demo(client) -> str:
    user = client.table("users").insert(
        {
            "name": "Margaret Chen",
            "phone": "+15550109999",
            "address": "12 Oak Lane",
            "timezone": "America/New_York",
        }
    ).execute().data[0]
    uid = user["id"]
    client.table("family_contacts").insert(
        {"user_id": uid, "name": "David", "phone": "+15550108888", "relationship": "son", "can_approve": True}
    ).execute()
    client.table("known_payees").insert(
        [
            {"user_id": uid, "name": "City Electric", "kind": "biller"},
            {"user_id": uid, "name": "Sunrise Pharmacy", "kind": "biller"},
            {"user_id": uid, "name": "Springfield Water", "kind": "biller"},
        ]
    ).execute()
    # Pre-seed two bills the way seed_demo_user.py does (ingest must not duplicate them).
    client.table("bills").insert(
        [
            {"user_id": uid, "payee": "City Electric", "amount": 84.20, "due_date": "2026-10-02", "status": "due"},
            {"user_id": uid, "payee": "Sunrise Pharmacy", "amount": 23.50, "due_date": "2026-10-05", "status": "due"},
        ]
    ).execute()
    return uid


def main() -> int:
    client = db.use_fake()
    uid = seed_demo(client)
    print(f"1. Seeded demo user {uid}")

    store = [
        _raw(f"id-{item['key']}", item["subject"], item["body"], item["sender"]) for item in DEMO_EMAILS
    ]
    print(f"2. Fake inbox has {len(store)} seeded messages")

    summary = run(user_id=uid, query="X-Gary-Seed:1", service=FakeGmail(store))
    print(f"3. Ingest fetched={summary['fetched']} counts={summary['counts']}")

    emails = client.table("emails").select("*").eq("user_id", uid).execute().data
    by_class: dict[str, int] = {}
    for e in emails:
        by_class[e["classification"]] = by_class.get(e["classification"], 0) + 1
    print(f"4. emails table: {len(emails)} rows {by_class}")

    bills = client.table("bills").select("*").eq("user_id", uid).execute().data
    with_source = [b for b in bills if b.get("source_email_id")]
    print(f"5. bills table: {len(bills)} total, {len(with_source)} from email (expect Springfield Water only)")

    scams = client.table("activity_log").select("*").eq("user_id", uid).eq("kind", "scam_flagged").execute().data
    print(f"6. activity_log scam_flagged: {len(scams)}")

    spoken = json.loads(list_bills_due(uid))
    print(f"7. list_bills_due: {spoken['say']}")

    cal = MagicMock()
    cal.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "cal-doc-1",
                "summary": DOCTOR_EVENT["summary"],
                "location": DOCTOR_EVENT["location"],
                "start": {"dateTime": "2026-09-26T14:00:00-04:00"},
                "end": {"dateTime": "2026-09-26T14:45:00-04:00"},
            }
        ]
    }
    upcoming = list_upcoming(service=cal, timezone_name="America/New_York", days=2)
    print(f"8. calendar list_upcoming: {upcoming[0]['summary']} @ {upcoming[0]['start']}")

    summary2 = run(user_id=uid, query="X-Gary-Seed:1", service=FakeGmail(store))
    emails2 = client.table("emails").select("*").eq("user_id", uid).execute().data
    bills2 = client.table("bills").select("*").eq("user_id", uid).execute().data
    print(f"9. Re-ingest: emails={len(emails2)} bills={len(bills2)} (idempotent)")

    # Assertions
    errors: list[str] = []
    if summary["fetched"] != 9:
        errors.append(f"expected 9 messages, got {summary['fetched']}")
    if by_class != {"bill": 3, "appointment": 2, "scam": 3, "other": 1}:
        errors.append(f"bad classification counts: {by_class}")
    if len(bills) != 3:
        errors.append(f"expected 3 bills (2 seed + 1 water), got {len(bills)}")
    if len(with_source) != 1 or with_source[0]["payee"] != "Springfield Water":
        errors.append(f"expected only Springfield Water from email, got {with_source}")
    if len(scams) != 3:
        errors.append(f"expected 3 scam activity events, got {len(scams)}")
    if "City Electric" not in spoken["say"] or "Springfield Water" not in spoken["say"]:
        errors.append(f"list_bills_due missing payees: {spoken['say']}")
    if not upcoming or "Patel" not in upcoming[0]["summary"]:
        errors.append(f"calendar event missing: {upcoming}")
    if len(emails2) != 9 or len(bills2) != 3:
        errors.append("re-ingest not idempotent")
    # Bodies never stored
    for e in emails:
        if "body" in e:
            errors.append("email row contains body field")
            break
        if "Call us immediately" in str(e.get("extracted")):
            errors.append("full body leaked into extracted")
            break

    if errors:
        print("\nPIPELINE FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("\nPIPELINE OK - classify -> persist -> bills/activity -> list_bills_due -> calendar -> re-ingest")
    print("Note: live Gmail/Calendar not exercised (no GOOGLE_* / SUPABASE_* in .env).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
