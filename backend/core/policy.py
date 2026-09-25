"""policy.check(): spending limit, known vs new payees, scam patterns.

This is never an MCP tool. Every money-moving tool calls it internally (safety invariant 1).

Phase 1 rules:
  * amount > POLICY_SPENDING_LIMIT            -> needs approval
  * payee not in known_payees for the user    -> needs approval
  * message_text matches a scam pattern       -> needs approval
Phase 2 (Person 2) refines the patterns and adds per-kind limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import settings
from core import db

Kind = str  # "bill" | "person" | "order" | "service" | "ride"

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


def is_known_payee(user_id: str, payee: str | None) -> bool:
    if not payee:
        return False
    res = db.get_client().table("known_payees").select("*").eq("user_id", user_id).execute()
    wanted = payee.strip().lower()
    return any((r.get("name") or "").strip().lower() == wanted for r in res.data)


def check(
    kind: Kind,
    payee: str | None,
    amount: float | int | None,
    user_id: str,
    message_text: str | None = None,
) -> Decision:
    """Decide whether an action can proceed after read-back or needs family approval."""
    family = approver_name(user_id)
    flags = scam_flags(message_text)
    amt = float(amount or 0)
    limit = float(settings.policy_spending_limit)

    if flags:
        return Decision(True, f"this looks like {flags[0]}", family, kind, flags)
    if amt > limit:
        return Decision(True, f"it's more than the usual limit of ${limit:,.0f}", family, kind)
    if kind in ("bill", "person") and not is_known_payee(user_id, payee):
        return Decision(True, f"{payee} is someone we haven't paid before", family, kind)
    return Decision(False, "", family, kind)
