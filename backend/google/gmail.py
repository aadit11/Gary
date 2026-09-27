"""Gmail API access for the demo account. Parse helpers are pure and unit-tested without network."""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .auth import gmail_service

log = logging.getLogger(__name__)

# Header used by seed_gmail.py so ingest can find demo messages reliably.
SEED_HEADER = "X-Gary-Seed"
SEED_HEADER_VALUE = "1"


def _b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _header_map(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in payload.get("headers") or []:
        name = (h.get("name") or "").lower()
        if name and name not in out:
            out[name] = h.get("value") or ""
    return out


def _walk_parts(part: dict[str, Any], texts: list[str]) -> None:
    mime = (part.get("mimeType") or "").lower()
    body = part.get("body") or {}
    data = body.get("data")
    if data and mime.startswith("text/plain"):
        texts.append(_b64url_decode(data).decode("utf-8", errors="replace"))
    elif data and mime.startswith("text/html") and not texts:
        raw = _b64url_decode(data).decode("utf-8", errors="replace")
        texts.append(re.sub(r"<[^>]+>", " ", raw))
    for child in part.get("parts") or []:
        _walk_parts(child, texts)


def extract_body(payload: dict[str, Any]) -> str:
    """Plain-text body from a Gmail message payload (for classification only; never stored)."""
    texts: list[str] = []
    _walk_parts(payload or {}, texts)
    if texts:
        return "\n".join(texts).strip()
    data = (payload or {}).get("body", {}).get("data")
    if data:
        return _b64url_decode(data).decode("utf-8", errors="replace").strip()
    return ""


def parse_received_at(internal_date: str | int | None, date_header: str = "") -> str | None:
    """Return an ISO-8601 UTC timestamp string, or None."""
    if internal_date not in (None, ""):
        try:
            ms = int(internal_date)
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass
    if date_header:
        try:
            dt = parsedate_to_datetime(date_header)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, IndexError):
            pass
    return None


def parse_message(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Gmail `users.messages.get` format=full response into a flat dict.

    Keys: gmail_id, thread_id, sender, subject, snippet, body, received_at, labels.
    `body` is for in-memory classification only — never write it to Supabase.
    """
    payload = raw.get("payload") or {}
    headers = _header_map(payload)
    return {
        "gmail_id": raw.get("id") or "",
        "thread_id": raw.get("threadId") or "",
        "sender": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "snippet": (raw.get("snippet") or "")[:500],
        "body": extract_body(payload),
        "received_at": parse_received_at(raw.get("internalDate"), headers.get("date", "")),
        "labels": list(raw.get("labelIds") or []),
    }


def list_message_ids(
    *,
    query: str = "",
    max_results: int = 50,
    service: Any | None = None,
) -> list[str]:
    """Return Gmail message ids matching `query` (newest first)."""
    svc = service or gmail_service()
    resp = (
        svc.users()
        .messages()
        .list(userId="me", q=query or None, maxResults=max_results)
        .execute()
    )
    return [m["id"] for m in resp.get("messages") or []]


def get_message(message_id: str, *, service: Any | None = None) -> dict[str, Any]:
    """Fetch and parse one message."""
    svc = service or gmail_service()
    raw = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    return parse_message(raw)


def list_messages(
    *,
    query: str = "",
    max_results: int = 50,
    service: Any | None = None,
) -> list[dict[str, Any]]:
    """List and parse messages. Prefer a narrow query (e.g. seeded header) for demos."""
    svc = service or gmail_service()
    ids = list_message_ids(query=query, max_results=max_results, service=svc)
    return [get_message(mid, service=svc) for mid in ids]


def insert_message(
    *,
    sender: str,
    to: str,
    subject: str,
    body: str,
    service: Any | None = None,
    seed: bool = True,
) -> str:
    """Insert a message into the demo inbox (no SMTP send). Returns the new gmail id."""
    from email.mime.text import MIMEText

    svc = service or gmail_service()
    msg = MIMEText(body, _charset="utf-8")
    msg["to"] = to
    msg["from"] = sender
    msg["subject"] = subject
    if seed:
        msg[SEED_HEADER] = SEED_HEADER_VALUE
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    created = (
        svc.users()
        .messages()
        .insert(userId="me", body={"raw": raw, "labelIds": ["INBOX", "UNREAD"]})
        .execute()
    )
    return created["id"]


def seed_query() -> str:
    """Gmail search string that finds messages inserted by seed_gmail.py.

    Gmail does not index custom headers, so X-Gary-Seed cannot be searched.
    Seed senders all use .example addresses.
    """
    return "from:example in:inbox"
