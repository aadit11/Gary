"""Unit tests for google/gmail.py pure parsers (no network)."""

from __future__ import annotations

import base64

from google.gmail import extract_body, parse_message, parse_received_at, seed_query


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def test_seed_query_targets_seed_senders():
    assert seed_query() == "from:example in:inbox"


def test_extract_body_plain():
    payload = {"mimeType": "text/plain", "body": {"data": _b64("Amount due: $84.20")}}
    assert "84.20" in extract_body(payload)


def test_extract_body_multipart_prefers_plain():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("plain body")}},
            {"mimeType": "text/html", "body": {"data": _b64("<b>html</b>")}},
        ],
    }
    assert extract_body(payload) == "plain body"


def test_parse_received_at_from_internal_date():
    iso = parse_received_at("1758758400000")
    assert iso is not None
    assert "T" in iso
    assert iso.endswith("+00:00") or iso.endswith("Z") or "+00:00" in iso or iso.endswith("+0000")


def test_parse_message_full_shape():
    raw = {
        "id": "msg-abc",
        "threadId": "thr-1",
        "snippet": "Your City Electric bill",
        "internalDate": "1758758400000",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "From", "value": "billing@cityelectric.example"},
                {"name": "Subject", "value": "Your City Electric bill is ready"},
                {"name": "Date", "value": "Thu, 25 Sep 2026 12:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64("Amount due: $84.20\nDue by: October 2, 2026\n")},
        },
    }
    parsed = parse_message(raw)
    assert parsed["gmail_id"] == "msg-abc"
    assert parsed["sender"].startswith("billing@")
    assert "City Electric" in parsed["subject"]
    assert "84.20" in parsed["body"]
    assert parsed["snippet"].startswith("Your City")
    assert "INBOX" in parsed["labels"]
