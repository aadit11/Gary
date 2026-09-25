"""Vertical 2 (Person 2): list_bills_due, prepare_bill_payment, confirm_bill_payment,
prepare_payment_to_person, check_message_for_scam, list_suspicious_emails.

Phase 1: list_bills_due is real (reads the bills table). The rest land in Phase 2.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from core import db
from core.speech import date_str, money_str, speak

money = FastMCP("money", instructions="Bills, payments, and scam checks.")


def _bills_due(user_id: str) -> list[dict]:
    res = (
        db.get_client()
        .table("bills")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "due")
        .order("due_date")
        .execute()
    )
    return res.data


@money.tool()
def list_bills_due(user_id: str) -> str:
    """Tell the user which bills are due, with amounts and dates, when they ask about bills."""
    try:
        bills = _bills_due(user_id)
    except Exception:  # noqa: BLE001
        return speak("I couldn't check your bills just now. Want me to try again?")
    if not bills:
        return speak("You don't have any bills due right now.")
    parts = [f"{money_str(b['amount'])} to {b['payee']} due {date_str(b.get('due_date'))}" for b in bills[:3]]
    if len(bills) == 1:
        say = f"You have one bill: {parts[0]}. Would you like to pay it?"
    else:
        listed = ", ".join(parts[:-1]) + f", and {parts[-1]}"
        extra = f" and {len(bills) - 3} more" if len(bills) > 3 else ""
        say = f"You have {len(bills)} bills{extra}: {listed}. Would you like to pay one?"
    return speak(say, data={"bills": [{"id": b["id"], "payee": b["payee"], "amount": float(b["amount"])} for b in bills]})
