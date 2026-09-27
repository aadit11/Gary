"""Tests for google/ingestion.py: classify, persist, idempotency (fake DB, no Google network)."""

from __future__ import annotations

import base64

from google.demo_emails import DEMO_EMAILS
from google.gmail import parse_message
from google.ingestion import classify, ingest_parsed, persist, run


def _parsed(gmail_id: str, subject: str, body: str, sender: str = "test@example.com") -> dict:
    return {
        "gmail_id": gmail_id,
        "thread_id": "t1",
        "sender": sender,
        "subject": subject,
        "snippet": body[:120],
        "body": body,
        "received_at": "2026-09-25T12:00:00+00:00",
        "labels": ["INBOX"],
    }


def test_classify_demo_templates(demo):
    """Every seeded DEMO_EMAILS template hits the expected classification."""
    payees = ["City Electric", "Sunrise Pharmacy", "Springfield Water"]
    for item in DEMO_EMAILS:
        parsed = _parsed(f"id-{item['key']}", item["subject"], item["body"], item["sender"])
        label, extracted = classify(parsed, user_id=demo["user_id"], known_payees=payees)
        assert label == item["classification"], (item["key"], label, extracted)
        if label == "bill":
            assert "amount" in extracted and "payee" in extracted
            assert extracted["amount"] > 0
        if label == "scam":
            assert extracted.get("scam_labels")
        if label == "appointment":
            assert extracted.get("title")


def test_classify_scam_medicare(demo):
    parsed = _parsed("s1", "URGENT Medicare", "Your Medicare will be suspended unless you verify today")
    label, extracted = classify(parsed, user_id=demo["user_id"], known_payees=[])
    assert label == "scam"
    assert any("Medicare" in x for x in extracted["scam_labels"])


def test_classify_bill_electric(demo):
    item = next(i for i in DEMO_EMAILS if i["key"] == "bill_electric")
    parsed = _parsed("b1", item["subject"], item["body"], item["sender"])
    label, extracted = classify(
        parsed, user_id=demo["user_id"], known_payees=["City Electric", "Sunrise Pharmacy"]
    )
    assert label == "bill"
    assert extracted["payee"] == "City Electric"
    assert extracted["amount"] == 84.20
    assert extracted["due_date"] == "2026-10-02"


def test_classify_newsletter_other(demo):
    item = next(i for i in DEMO_EMAILS if i["key"] == "other_newsletter")
    parsed = _parsed("o1", item["subject"], item["body"])
    label, extracted = classify(parsed, user_id=demo["user_id"], known_payees=[])
    assert label == "other"
    assert extracted == {}


def test_persist_email_never_stores_body(demo, fake_db):
    item = next(i for i in DEMO_EMAILS if i["key"] == "scam_medicare")
    parsed = _parsed("gm-scam-1", item["subject"], item["body"], item["sender"])
    label, extracted = classify(parsed, user_id=demo["user_id"], known_payees=[])
    result = persist(demo["user_id"], parsed, label, extracted)
    row = fake_db.table("emails").select("*").eq("id", result["email_id"]).execute().data[0]
    assert "body" not in row
    assert row["classification"] == "scam"
    assert row["extracted"]["scam_labels"]
    # Full body must not be dumped into extracted
    assert "Call us immediately" not in str(row["extracted"])
    logs = fake_db.table("activity_log").select("*").eq("user_id", demo["user_id"]).execute().data
    assert any(e["kind"] == "scam_flagged" for e in logs)


def test_ingest_compatible_with_list_bills_due(demo, fake_db):
    """After ingest, existing money tool still speaks seeded + new water bill correctly."""
    import json
    from mcp_servers.money import list_bills_due

    fake_db.table("known_payees").insert(
        {"user_id": demo["user_id"], "name": "Springfield Water", "kind": "biller"}
    ).execute()
    item = next(i for i in DEMO_EMAILS if i["key"] == "bill_water")
    ingest_parsed(
        demo["user_id"],
        _parsed("gm-water-2", item["subject"], item["body"], item["sender"]),
        known_payees=["City Electric", "Sunrise Pharmacy", "Springfield Water"],
    )
    out = json.loads(list_bills_due(demo["user_id"]))
    assert "City Electric" in out["say"]
    assert "Springfield Water" in out["say"] or len(out["data"]["bills"]) >= 3


def test_persist_bill_creates_row_when_not_seeded(demo, fake_db):
    # Springfield Water is a known payee but seed_demo_user did not insert this bill.
    item = next(i for i in DEMO_EMAILS if i["key"] == "bill_water")
    parsed = _parsed("gm-water-1", item["subject"], item["body"], item["sender"])
    result = ingest_parsed(
        demo["user_id"],
        parsed,
        known_payees=["City Electric", "Sunrise Pharmacy", "Springfield Water"],
    )
    assert result["classification"] == "bill"
    assert result["created_bill"] is True
    bills = fake_db.table("bills").select("*").eq("source_email_id", result["email_id"]).execute().data
    assert len(bills) == 1
    assert bills[0]["payee"] == "Springfield Water"
    assert float(bills[0]["amount"]) == 41.15


def test_persist_skips_duplicate_seeded_bill(demo, fake_db):
    """City Electric $84.20 already exists from the demo fixture — do not double-insert."""
    item = next(i for i in DEMO_EMAILS if i["key"] == "bill_electric")
    parsed = _parsed("gm-elec-1", item["subject"], item["body"], item["sender"])
    before = len(fake_db.table("bills").select("*").eq("user_id", demo["user_id"]).execute().data)
    result = ingest_parsed(
        demo["user_id"],
        parsed,
        known_payees=["City Electric", "Sunrise Pharmacy"],
    )
    after = fake_db.table("bills").select("*").eq("user_id", demo["user_id"]).execute().data
    assert result["created_email"] is True
    assert result["created_bill"] is False
    assert len(after) == before


def test_persist_idempotent_on_gmail_id(demo, fake_db):
    item = next(i for i in DEMO_EMAILS if i["key"] == "other_newsletter")
    parsed = _parsed("gm-news-1", item["subject"], item["body"])
    first = ingest_parsed(demo["user_id"], parsed, known_payees=[])
    second = ingest_parsed(demo["user_id"], parsed, known_payees=[])
    assert first["email_id"] == second["email_id"]
    assert first["created_email"] is True
    assert second["created_email"] is False
    rows = fake_db.table("emails").select("*").eq("gmail_id", "gm-news-1").execute().data
    assert len(rows) == 1


def test_run_with_fake_gmail_service(demo, fake_db):
    """run() against an in-memory fake Gmail service — no network."""

    class _FakeExec:
        def __init__(self, data):
            self._data = data

        def execute(self):
            return self._data

    class _FakeMessages:
        def __init__(self, store):
            self._store = store

        def list(self, userId, q=None, maxResults=50):
            ids = [{"id": m["id"]} for m in self._store[:maxResults]]
            return _FakeExec({"messages": ids})

        def get(self, userId, id, format="full"):
            raw = next(m for m in self._store if m["id"] == id)
            return _FakeExec(raw)

    class _FakeUsers:
        def __init__(self, store):
            self._store = store

        def messages(self):
            return _FakeMessages(self._store)

    class FakeGmail:
        def __init__(self, store):
            self._store = store

        def users(self):
            return _FakeUsers(self._store)

    def raw_msg(mid: str, subject: str, body: str, sender: str) -> dict:
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
                ],
                "mimeType": "text/plain",
                "body": {"data": data},
            },
        }

    store = []
    for item in DEMO_EMAILS:
        store.append(raw_msg(f"id-{item['key']}", item["subject"], item["body"], item["sender"]))

    # Add Springfield Water to known payees so bill_water classifies cleanly
    # (demo fixture already has City Electric + Sunrise Pharmacy).
    fake_db.table("known_payees").insert(
        {"user_id": demo["user_id"], "name": "Springfield Water", "kind": "biller"}
    ).execute()

    summary = run(user_id=demo["user_id"], query="X-Gary-Seed:1", service=FakeGmail(store))
    assert summary["fetched"] == len(DEMO_EMAILS)
    assert summary["counts"]["scam"] == 3
    assert summary["counts"]["bill"] == 3
    assert summary["counts"]["appointment"] == 2
    assert summary["counts"]["other"] == 1

    emails = fake_db.table("emails").select("*").eq("user_id", demo["user_id"]).execute().data
    assert len(emails) == len(DEMO_EMAILS)

    # Re-run: still one row per gmail_id
    summary2 = run(user_id=demo["user_id"], query="X-Gary-Seed:1", service=FakeGmail(store))
    assert summary2["fetched"] == len(DEMO_EMAILS)
    emails2 = fake_db.table("emails").select("*").eq("user_id", demo["user_id"]).execute().data
    assert len(emails2) == len(DEMO_EMAILS)


def test_parse_message_roundtrip_with_classify(demo):
    item = next(i for i in DEMO_EMAILS if i["key"] == "scam_package")
    data = base64.urlsafe_b64encode(item["body"].encode()).decode().rstrip("=")
    raw = {
        "id": "pkg1",
        "snippet": "customs fee",
        "payload": {
            "headers": [
                {"name": "From", "value": item["sender"]},
                {"name": "Subject", "value": item["subject"]},
            ],
            "mimeType": "text/plain",
            "body": {"data": data},
        },
    }
    parsed = parse_message(raw)
    label, extracted = classify(parsed, user_id=demo["user_id"], known_payees=[])
    assert label == "scam"
    assert extracted["scam_labels"]
