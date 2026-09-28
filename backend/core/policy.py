"""policy.check(): scam patterns, spending limit, known vs new payees, recurring vs one-off.

This is never an MCP tool. Every money-moving tool calls it internally (safety invariant 1).

Rules, in order (the first that matches decides):
  1. payee or message_text matches a scam pattern          -> needs approval
  2. amount > POLICY_SPENDING_LIMIT                         -> needs approval
  3. bill/person payee not in known_payees                  -> needs approval
  3b. ride to a place the family has not saved              -> needs approval
     (the profile's home, hospital, and saved places, plus the user's address)
  4. bill/person payment that is not recurring and amount
     > the hard limit (users.hard_limit, else POLICY_HARD_LIMIT) -> needs approval

A bill is recurring when its payee is a known biller and, if we have paid that payee before,
the amount is within POLICY_RECURRING_TOLERANCE of those earlier payments. Person payments are
never recurring. Orders, services, and rides are not subject to the hard limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import settings
from core import db

Kind = str  # "bill" | "person" | "order" | "service" | "ride"

PAYMENT_KINDS = ("bill", "person")

# (label, regex). Labels are plain words that can be spoken to the user.
SCAM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("a tax agency demanding payment", re.compile(r"\b(irs|internal revenue|tax (?:agency|office|debt|warrant))\b", re.I)),
    ("a Medicare or Social Security scare", re.compile(r"\b(medicare|social security)\b.*\b(suspend|suspended|cancel|expire|verify|urgent)\b", re.I | re.S)),
    ("a family emergency request for money", re.compile(r"\b(grandson|granddaughter|grandchild|nephew|niece)\b.*\b(jail|arrested|accident|hospital|bail|trouble|stuck)\b", re.I | re.S)),
    ("a request for gift cards", re.compile(r"\b(gift ?cards?|itunes|google play|steam cards?)\b", re.I)),
    ("a wire transfer or crypto request", re.compile(r"\b(wire transfer|western union|moneygram|bitcoin|crypto|zelle me)\b", re.I)),
    ("a package fee scam", re.compile(r"\b(package|parcel|delivery)\b.*\b(fee|redelivery|customs|unpaid)\b", re.I | re.S)),
    ("a tech support scare", re.compile(r"\b(virus|hacked|microsoft|apple support|refund department)\b.*\b(call|remote|access)\b", re.I | re.S)),
]


@dataclass
class Decision:
    needs_approval: bool
    reason: str = ""
    family_name: str = "your family"
    kind: Kind = ""
    flags: list[str] = field(default_factory=list)
    recurring: bool = False


def scam_flags(text: str | None) -> list[str]:
    """Return spoken labels for every scam pattern that matches `text`."""
    if not text:
        return []
    return [label for label, rx in SCAM_PATTERNS if rx.search(text)]


def approver_name(user_id: str) -> str:
    """First family contact who can approve, for use in spoken sentences."""
    try:
        res = (
            db.get_client()
            .table("family_contacts")
            .select("*")
            .eq("user_id", user_id)
            .eq("can_approve", True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["name"]
    except Exception:  # noqa: BLE001
        pass
    return "your family"


def _known_payee(user_id: str, payee: str | None) -> dict | None:
    if not payee:
        return None
    res = db.get_client().table("known_payees").select("*").eq("user_id", user_id).execute()
    wanted = payee.strip().lower()
    for r in res.data:
        if (r.get("name") or "").strip().lower() == wanted:
            return r
    return None


def is_known_payee(user_id: str, payee: str | None) -> bool:
    return _known_payee(user_id, payee) is not None


PROFILE_GMAIL_ID = "caregiver-profile"


def saved_places(user_id: str) -> list[str]:
    """Places the family has saved for rides: the user's address and the profile's home, hospital, and places."""
    places: list[str] = []
    try:
        client = db.get_client()
        rows = client.table("users").select("*").eq("id", user_id).limit(1).execute().data
        if rows and rows[0].get("address"):
            places.append(str(rows[0]["address"]))
        prof = client.table("emails").select("*").eq("user_id", user_id).eq("gmail_id", PROFILE_GMAIL_ID).limit(1).execute().data
        uber = (((prof[0].get("extracted") or {}).get("connectors") or {}).get("uber") or {}) if prof else {}
        for key in ("home", "hospital"):
            if uber.get(key):
                places.append(str(uber[key]))
        for place in uber.get("places") or []:
            if isinstance(place, dict):
                places.extend(str(place[k]) for k in ("label", "address") if place.get(k))
    except Exception:  # noqa: BLE001
        pass
    return [p for p in places if p.strip()]


def _norm_place(text: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").casefold()))


def is_known_place(user_id: str, place: str | None) -> bool:
    """True when the destination matches a saved place (either contains the other, ignoring punctuation and case)."""
    want = _norm_place(place)
    if not want:
        return False
    for saved in saved_places(user_id):
        have = _norm_place(saved)
        if have and (have in want or want in have):
            return True
    return False


def hard_limit_for(user_id: str) -> float:
    """The user's one-off payment limit: users.hard_limit when set, else POLICY_HARD_LIMIT."""
    try:
        rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
        value = rows[0].get("hard_limit") if rows else None
        if value is not None:
            return float(value)
    except Exception:  # noqa: BLE001
        pass
    return float(settings.policy_hard_limit)


def is_recurring_bill(user_id: str, payee: str | None, amount: float) -> bool:
    """Known biller, and within tolerance of earlier paid amounts when there is history."""
    known = _known_payee(user_id, payee)
    if not known or (known.get("kind") or "biller") != "biller":
        return False
    paid = (
        db.get_client()
        .table("bills")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "paid")
        .execute()
        .data
    )
    history = [float(b["amount"]) for b in paid if (b.get("payee") or "").strip().lower() == known["name"].strip().lower()]
    if not history:
        return True
    typical = sum(history) / len(history)
    if typical <= 0:
        return False
    return abs(amount - typical) / typical <= float(settings.policy_recurring_tolerance)


def check(
    kind: Kind,
    payee: str | None,
    amount: float | int | None,
    user_id: str,
    message_text: str | None = None,
) -> Decision:
    """Decide whether an action can proceed after read-back or needs family approval."""
    family = approver_name(user_id)
    flags = scam_flags(" ".join(t for t in (payee, message_text) if t))
    amt = float(amount or 0)
    limit = float(settings.policy_spending_limit)

    if flags:
        return Decision(True, f"this looks like {flags[0]}", family, kind, flags)
    if amt > limit:
        return Decision(True, f"it's more than the usual limit of ${limit:,.0f}", family, kind)
    if kind in PAYMENT_KINDS and not is_known_payee(user_id, payee):
        return Decision(True, f"{payee} is someone we haven't paid before", family, kind)
    if kind == "ride" and not is_known_place(user_id, payee):
        return Decision(True, f"{payee} is a new place that isn't saved", family, kind)

    recurring = kind == "bill" and is_recurring_bill(user_id, payee, amt)
    if kind in PAYMENT_KINDS and not recurring:
        hard = hard_limit_for(user_id)
        if amt > hard:
            return Decision(True, f"it's a one-time payment over your ${hard:,.0f} limit", family, kind)
    return Decision(False, "", family, kind, recurring=recurring)
