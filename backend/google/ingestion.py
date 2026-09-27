"""Classify Gmail messages into bills / appointments / scams / other and store results in Supabase.

Classification runs at ingest time (CLI or optional job), never on a live phone call.
Bodies are used only in memory; emails.snippet and emails.extracted are what we persist.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from config import settings
from core import activity, db
from core.policy import scam_flags

from . import gmail as gmail_mod

log = logging.getLogger(__name__)

Classification = Literal["bill", "appointment", "scam", "other"]

_AMOUNT_RE = re.compile(
    r"(?:amount\s+due|balance\s+due|total\s+due|due)[:\s]*\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"
    r"|\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
    re.I,
)
_DUE_BY_RE = re.compile(
    r"(?:due\s+(?:by|on|date)?|pay\s+by)\s*:?\s*"
    r"([A-Za-z]+ \d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
    re.I,
)
_MONTH_DAY_YEAR_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
_APPT_RE = re.compile(
    r"\b(appointment|doctor'?s?\s+appointment|dr\.?\s+\w+|prescription\s+refill|"
    r"ready\s+for\s+pickup|see\s+(?:the\s+)?pharmacist|clinic)\b",
    re.I,
)
_BILL_HINT_RE = re.compile(r"\b(bill|amount\s+due|balance\s+due|invoice|statement)\b", re.I)


def _parse_amount(text: str) -> float | None:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _parse_date_token(token: str) -> str | None:
    token = token.strip().replace(",", "")
    for fmt in ("%B %d %Y", "%b %d %Y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(token, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_due_date(text: str) -> str | None:
    m = _DUE_BY_RE.search(text)
    if m:
        parsed = _parse_date_token(m.group(1))
        if parsed:
            return parsed
    # Fall back to first month-day-year in the message (bills usually have one).
    m2 = _MONTH_DAY_YEAR_RE.search(text)
    if m2:
        return _parse_date_token(m2.group(1))
    return None


def _known_payees(user_id: str) -> list[str]:
    try:
        rows = db.get_client().table("known_payees").select("*").eq("user_id", user_id).execute().data
        return [r["name"] for r in rows if r.get("name")]
    except Exception:  # noqa: BLE001
        log.exception("known_payees lookup failed")
        return []


def _match_payee(text: str, payees: list[str]) -> str | None:
    lower = text.lower()
    best: str | None = None
    best_len = 0
    for name in payees:
        n = name.strip()
        if n and n.lower() in lower and len(n) > best_len:
            best = n
            best_len = len(n)
    return best


def _zone_for(user_id: str) -> ZoneInfo:
    try:
        rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
        name = (rows[0].get("timezone") if rows else None) or "America/New_York"
    except Exception:  # noqa: BLE001
        name = "America/New_York"
    return ZoneInfo(name)


def _clock(token: str) -> tuple[int, int] | None:
    match = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", token.strip(), re.I)
    if not match:
        return None
    hour = int(match.group(1)) % 12
    if match.group(3).upper() == "PM":
        hour += 12
    return hour, int(match.group(2) or 0)


def _extract_appointment(subject: str, body: str, tz: ZoneInfo) -> dict[str, Any]:
    """Fields check-ins reads: title and starts_at (ISO timestamp in the user's timezone)."""
    text = f"{subject}\n{body}"
    title = (subject.strip() or "Appointment").splitlines()[0]
    # Spaces only, so a name cannot run onto the next line.
    doctor = re.search(r"\bDr\.?[ \t]+[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)?", text)
    if doctor:
        title = doctor.group(0)
    date_token = None
    found_date = _MONTH_DAY_YEAR_RE.search(text)
    if found_date:
        date_token = found_date.group(1)
    time_token = None
    found_time = re.search(r"\bat\s+(\d{1,2}(?::\d{2})?\s*(?:AM|PM))", text, re.I)
    if found_time:
        time_token = found_time.group(1)
    spoken = date_token
    if date_token and time_token:
        spoken = f"{date_token} at {time_token.upper()}"
    starts_at = None
    iso_day = _parse_date_token(date_token) if date_token else None
    clock = _clock(time_token) if time_token else None
    if iso_day and clock:
        starts_at = datetime.fromisoformat(iso_day).replace(hour=clock[0], minute=clock[1], tzinfo=tz).isoformat()
    loc = None
    found_loc = re.search(r"location\s*:\s*(.+)", text, re.I)
    if found_loc:
        loc = found_loc.group(1).strip().split("\n")[0][:120]
    out: dict[str, Any] = {"title": title}
    if spoken:
        out["when"] = spoken
    if starts_at:
        out["starts_at"] = starts_at
    if loc:
        out["location"] = loc
    return out


def classify(
    parsed: dict[str, Any],
    *,
    user_id: str,
    known_payees: list[str] | None = None,
) -> tuple[Classification, dict[str, Any]]:
    """Return (classification, extracted) for a parse_message() dict. Never includes the body."""
    subject = parsed.get("subject") or ""
    body = parsed.get("body") or ""
    text = f"{subject}\n{body}"

    flags = scam_flags(text)
    if flags:
        return "scam", {"scam_labels": flags}

    payees = known_payees if known_payees is not None else _known_payees(user_id)
    payee = _match_payee(text, payees)
    amount = _parse_amount(text)
    due = _parse_due_date(text)

    if payee and amount is not None and (_BILL_HINT_RE.search(text) or due):
        extracted: dict[str, Any] = {"payee": payee, "amount": amount}
        if due:
            extracted["due_date"] = due
        return "bill", extracted

    # Bill without a known payee still counts if it looks like a bill with amount+due.
    if amount is not None and due and _BILL_HINT_RE.search(text):
        guessed = payee or (subject.split("—")[0].split("-")[0].strip()[:80] or "Unknown payee")
        return "bill", {"payee": guessed, "amount": amount, "due_date": due}

    if _APPT_RE.search(text):
        return "appointment", _extract_appointment(subject, body, _zone_for(user_id))

    return "other", {}


def _existing_email(gmail_id: str) -> dict[str, Any] | None:
    rows = db.get_client().table("emails").select("*").eq("gmail_id", gmail_id).limit(1).execute().data
    return rows[0] if rows else None


def _bill_already_present(user_id: str, payee: str, amount: float, due_date: str | None) -> bool:
    """True if a matching bill already exists (e.g. from seed_demo_user.py)."""
    rows = (
        db.get_client()
        .table("bills")
        .select("*")
        .eq("user_id", user_id)
        .eq("payee", payee)
        .execute()
        .data
    )
    for b in rows:
        try:
            same_amount = abs(float(b.get("amount") or 0) - float(amount)) < 0.001
        except (TypeError, ValueError):
            same_amount = False
        same_due = True
        if due_date:
            existing_due = b.get("due_date")
            if existing_due:
                same_due = str(existing_due)[:10] == str(due_date)[:10]
        if same_amount and same_due:
            return True
    return False


def _bill_for_email(email_id: str) -> dict[str, Any] | None:
    rows = (
        db.get_client()
        .table("bills")
        .select("*")
        .eq("source_email_id", email_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def persist(
    user_id: str,
    parsed: dict[str, Any],
    classification: Classification,
    extracted: dict[str, Any],
) -> dict[str, Any]:
    """Upsert emails row; create a bills row for bill classifications when needed.

    Idempotent on gmail_id. Never stores the email body. Returns a result summary dict.
    """
    gmail_id = parsed.get("gmail_id") or ""
    if not gmail_id:
        raise ValueError("parsed message is missing gmail_id")

    client = db.get_client()
    existing = _existing_email(gmail_id)
    email_row = {
        "user_id": user_id,
        "gmail_id": gmail_id,
        "sender": (parsed.get("sender") or "")[:300],
        "subject": (parsed.get("subject") or "")[:500],
        "snippet": (parsed.get("snippet") or (parsed.get("body") or "")[:240])[:500],
        "received_at": parsed.get("received_at"),
        "classification": classification,
        "extracted": extracted,
    }

    if existing:
        client.table("emails").update(
            {
                "sender": email_row["sender"],
                "subject": email_row["subject"],
                "snippet": email_row["snippet"],
                "received_at": email_row["received_at"],
                "classification": classification,
                "extracted": extracted,
            }
        ).eq("id", existing["id"]).execute()
        email_id = existing["id"]
        created_email = False
    else:
        inserted = client.table("emails").insert(email_row).execute().data[0]
        email_id = inserted["id"]
        created_email = True

    bill_id = None
    created_bill = False
    if classification == "bill":
        prior = _bill_for_email(email_id)
        if prior:
            bill_id = prior["id"]
        else:
            payee = str(extracted.get("payee") or "Unknown")
            amount = float(extracted.get("amount") or 0)
            due_date = extracted.get("due_date")
            if _bill_already_present(user_id, payee, amount, due_date):
                log.info("skipping bill insert for %s — already present (likely seed_demo_user)", payee)
            else:
                bill = {
                    "user_id": user_id,
                    "payee": payee,
                    "amount": amount,
                    "due_date": due_date,
                    "status": "due",
                    "source_email_id": email_id,
                }
                bill_id = client.table("bills").insert(bill).execute().data[0]["id"]
                created_bill = True

    if classification == "scam" and created_email:
        labels = extracted.get("scam_labels") or []
        label = labels[0] if labels else "a suspicious message"
        activity.log_event(
            user_id,
            "scam_flagged",
            f"Flagged a suspicious email that looks like {label}",
            {"email_id": email_id, "gmail_id": gmail_id, "subject": email_row["subject"]},
        )

    return {
        "email_id": email_id,
        "gmail_id": gmail_id,
        "classification": classification,
        "created_email": created_email,
        "bill_id": bill_id,
        "created_bill": created_bill,
        "extracted": extracted,
    }


def ingest_parsed(user_id: str, parsed: dict[str, Any], *, known_payees: list[str] | None = None) -> dict[str, Any]:
    """Classify + persist one already-parsed message."""
    classification, extracted = classify(parsed, user_id=user_id, known_payees=known_payees)
    return persist(user_id, parsed, classification, extracted)


def run(
    user_id: str | None = None,
    *,
    query: str | None = None,
    max_results: int = 50,
    service: Any | None = None,
) -> dict[str, Any]:
    """Pull recent (or seeded) Gmail messages, classify, and write to Supabase.

    Default query targets messages inserted by seed_gmail.py. Pass query="" to scan recent mail.
    """
    uid = user_id or settings.demo_user_id
    if not uid:
        raise ValueError("user_id is required (or set DEMO_USER_ID in .env)")

    q = gmail_mod.seed_query() if query is None else query
    payees = _known_payees(uid)
    messages = gmail_mod.list_messages(query=q, max_results=max_results, service=service)

    results = []
    counts: dict[str, int] = {"bill": 0, "appointment": 0, "scam": 0, "other": 0}
    for parsed in messages:
        # Prefer a short snippet for storage when Gmail's snippet is empty.
        if not parsed.get("snippet") and parsed.get("body"):
            parsed = {**parsed, "snippet": parsed["body"][:240]}
        result = ingest_parsed(uid, parsed, known_payees=payees)
        results.append(result)
        counts[result["classification"]] = counts.get(result["classification"], 0) + 1

    summary = {
        "user_id": uid,
        "queried": q,
        "fetched": len(messages),
        "counts": counts,
        "results": results,
    }
    log.info(
        "ingestion done user=%s fetched=%s counts=%s",
        uid,
        len(messages),
        counts,
    )
    return summary
