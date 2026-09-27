"""Vertical 2: bills, payments to people, and Scam Guard.

Every money-moving tool calls policy.check() inside the tool (safety invariant 1). A payment that
needs family approval (scam pattern, over the spending limit, new payee, or a one-off over the
hard limit) texts the family as soon as it is requested and is executed only when they reply YES.
Everything else goes prepare -> read-back -> confirm with a pending action id (invariant 2).
"""

from __future__ import annotations

import logging
import re

from mcp.server.fastmcp import FastMCP

from clients import mock_services
from core import activity, approvals, db, notify, pending, policy
from core.models import Approval
from core.pending import PendingActionError
from core.speech import date_str, money_str, speak
from webhooks.sms import ACTION_EXECUTORS

log = logging.getLogger(__name__)

money = FastMCP("money", instructions="Bills, payments, and scam checks.")

_STOPWORDS = {
    "the", "my", "bill", "bills", "pay", "please", "for", "and", "that", "this", "one", "email",
    "emails", "real", "about", "from", "with", "have", "they", "said", "was", "is", "it", "a", "an",
    "to", "of", "me", "i", "got", "get", "just", "some", "someone", "message", "letter", "text",
}


class PaymentError(Exception):
    """A payment could not be carried out. `.say` is safe to speak."""

    def __init__(self, say: str):
        super().__init__(say)
        self.say = say


def _first_name(user_id: str) -> str:
    rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
    return ((rows[0].get("name") if rows else None) or "They").split(" ")[0]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3 and w not in _STOPWORDS}


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


def _get_bill(user_id: str, bill_id: str) -> dict | None:
    rows = db.get_client().table("bills").select("*").eq("id", bill_id).eq("user_id", user_id).limit(1).execute().data
    return rows[0] if rows else None


def _find_due_bill(user_id: str, query: str) -> dict | None:
    """Match a due bill by exact id or by the payee words the person said ("the electric bill")."""
    bills = _bills_due(user_id)
    q = (query or "").strip()
    for b in bills:
        if str(b["id"]) == q:
            return b
    wanted = _words(q)
    if not wanted:
        return bills[0] if len(bills) == 1 else None
    best, best_score = None, 0
    for b in bills:
        score = len(wanted & _words(b.get("payee") or ""))
        if score > best_score:
            best, best_score = b, score
    return best


def _request_approval(user_id: str, action: str, payload: dict, decision: policy.Decision, summary: str, category: str) -> str:
    approval_id = approvals.request(
        user_id,
        action,
        payload,
        decision.reason,
        summary=f"{_first_name(user_id)} wants to {summary}",
    )
    activity.log_event(
        user_id,
        "approval_requested",
        f"Asked {decision.family_name} before: {summary}",
        {"approval_id": approval_id, "action": action, "reason": decision.reason, "category": category},
    )
    return approval_id


# --- execution (shared by confirm_* tools and approval executors) -------------------------------


def _pay_bill(user_id: str, bill_id: str, *, tell_family: bool = True) -> dict:
    bill = _get_bill(user_id, bill_id)
    if not bill or bill.get("status") != "due":
        raise PaymentError("That bill is already taken care of.")
    amount = float(bill["amount"])
    try:
        result = mock_services.pay_bill(bill["payee"], amount, bill_id=bill_id)
    except mock_services.MockServiceError:
        log.exception("bill payment failed for %s", bill_id)
        raise PaymentError("I couldn't reach the biller just now. Want me to try again?") from None
    confirmation = result["confirmation_id"]
    db.get_client().table("bills").update(
        {"status": "paid", "confirmation_id": confirmation, "paid_at": db.now_iso()}
    ).eq("id", bill_id).execute()
    summary = f"Paid {money_str(amount)} to {bill['payee']}"
    activity.log_event(
        user_id,
        "bill_paid",
        summary,
        {"bill_id": bill_id, "payee": bill["payee"], "amount": amount, "confirmation_id": confirmation,
         "simulated": bool(result.get("simulated")), "category": "bill_payment"},
    )
    if tell_family:
        notify.notify_family(user_id, f"{_first_name(user_id)} paid {money_str(amount)} to {bill['payee']}. Confirmation {confirmation}.")
    return {"bill": bill, "amount": amount, "confirmation_id": confirmation}


def _send_to_person(user_id: str, recipient: str, amount: float, *, tell_family: bool = True) -> dict:
    result = mock_services.send_to_person(recipient, amount)
    confirmation = result["confirmation_id"]
    activity.log_event(
        user_id,
        "person_paid",
        f"Sent {money_str(amount)} to {recipient}",
        {"recipient": recipient, "amount": amount, "confirmation_id": confirmation, "simulated": True, "category": "person_payment"},
    )
    if tell_family:
        notify.notify_family(user_id, f"{_first_name(user_id)} sent {money_str(amount)} to {recipient}.")
    return {"recipient": recipient, "amount": amount, "confirmation_id": confirmation}


def _execute_pay_bill(approval: Approval) -> str:
    done = _pay_bill(approval.user_id, str(approval.payload.get("bill_id")), tell_family=False)
    return f"Done. Paid {money_str(done['amount'])} to {done['bill']['payee']}."


def _execute_pay_person(approval: Approval) -> str:
    recipient = str(approval.payload.get("recipient"))
    amount = float(approval.payload.get("amount") or 0)
    _send_to_person(approval.user_id, recipient, amount, tell_family=False)
    return f"Done. Sent {money_str(amount)} to {recipient}."


ACTION_EXECUTORS["pay_bill"] = _execute_pay_bill
ACTION_EXECUTORS["pay_person"] = _execute_pay_person


# --- tools -----------------------------------------------------------------------------------


@money.tool()
def list_bills_due(user_id: str) -> str:
    """Tell the user which bills are due, with amounts and dates, when they ask about bills."""
    try:
        bills = _bills_due(user_id)
    except Exception:  # noqa: BLE001
        return speak("I couldn't check your bills just now. Want me to try again?", data={"category": "bill_payment", "outcome": "error"})
    if not bills:
        return speak("You don't have any bills due right now.", data={"category": "bill_payment", "outcome": "resolved"})
    parts = [f"{money_str(b['amount'])} to {b['payee']} due {date_str(b.get('due_date'))}" for b in bills[:3]]
    if len(bills) == 1:
        say = f"You have one bill: {parts[0]}. Would you like to pay it?"
    else:
        listed = ", ".join(parts[:-1]) + f", and {parts[-1]}"
        extra = f" and {len(bills) - 3} more" if len(bills) > 3 else ""
        say = f"You have {len(bills)} bills{extra}: {listed}. Would you like to pay one?"
    return speak(
        say,
        data={
            "category": "bill_payment",
            "outcome": "resolved",
            "bills": [{"id": b["id"], "payee": b["payee"], "amount": float(b["amount"])} for b in bills],
        },
    )


@money.tool()
def prepare_bill_payment(user_id: str, bill: str) -> str:
    """Prepare to pay one due bill, named by its payee (like "electric") or id, and return details to read back."""
    try:
        found = _find_due_bill(user_id, bill)
        if not found:
            return speak("I don't see a bill like that. Would you like me to list your bills?", data={"category": "bill_payment", "outcome": "not_found"})
        amount = float(found["amount"])
        payee = found["payee"]
        summary = f"pay {money_str(amount)} to {payee}"
        decision = policy.check("bill", payee, amount, user_id)
        if decision.needs_approval:
            if approvals.find_pending(user_id, "pay_bill", bill_id=found["id"]):
                return speak(
                    f"I've already asked {decision.family_name} about that one. I'll tell you as soon as they answer.",
                    data={"category": "bill_payment", "outcome": "approval_pending"},
                )
            _request_approval(
                user_id,
                "pay_bill",
                {"bill_id": found["id"], "payee": payee, "amount": amount, "summary": summary,
                 "done_say": f"I paid {money_str(amount)} to {payee}."},
                decision,
                summary,
                "bill_payment",
            )
            return speak(
                f"Before I {summary}, I'd like to check with {decision.family_name}, because {decision.reason}. "
                "I'll let you know as soon as they answer.",
                data={"category": "bill_payment", "outcome": "approval_requested", "reason": decision.reason},
            )
        action_id = pending.create("pay_bill", user_id, bill_id=found["id"])
    except Exception:  # noqa: BLE001
        log.exception("prepare_bill_payment failed")
        return speak("I couldn't set that up just now. Want me to try again?", data={"category": "bill_payment", "outcome": "error"})
    return speak(
        f"That's {money_str(amount)} to {payee}, due {date_str(found.get('due_date'))}. Should I pay it?",
        action_id=action_id,
        data={"category": "bill_payment", "outcome": "read_back"},
    )


@money.tool()
def confirm_bill_payment(user_id: str, action_id: str) -> str:
    """Pay the bill only after prepare_bill_payment was read back and the user clearly said yes."""
    try:
        payload = pending.consume(action_id, "pay_bill", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "bill_payment", "outcome": "error"})
    try:
        bill = _get_bill(user_id, str(payload.get("bill_id")))
        if not bill or bill.get("status") != "due":
            return speak("That bill is already taken care of.", data={"category": "bill_payment", "outcome": "resolved"})
        amount = float(bill["amount"])
        decision = policy.check("bill", bill["payee"], amount, user_id)
        if decision.needs_approval:
            summary = f"pay {money_str(amount)} to {bill['payee']}"
            _request_approval(
                user_id, "pay_bill",
                {"bill_id": bill["id"], "payee": bill["payee"], "amount": amount, "summary": summary,
                 "done_say": f"I paid {money_str(amount)} to {bill['payee']}."},
                decision, summary, "bill_payment",
            )
            return speak(
                f"I'd like to check with {decision.family_name} first, because {decision.reason}. I'll let you know.",
                data={"category": "bill_payment", "outcome": "approval_requested"},
            )
        done = _pay_bill(user_id, bill["id"])
    except PaymentError as err:
        return speak(err.say, data={"category": "bill_payment", "outcome": "error"})
    except Exception:  # noqa: BLE001
        log.exception("confirm_bill_payment failed")
        return speak("I couldn't pay that just now. Want me to try again?", data={"category": "bill_payment", "outcome": "error"})
    return speak(
        f"Done. I paid {money_str(done['amount'])} to {done['bill']['payee']}, and I've let your family know.",
        data={"category": "bill_payment", "outcome": "paid"},
    )


@money.tool()
def prepare_payment_to_person(user_id: str, recipient: str, amount: float, message: str = "") -> str:
    """Prepare to send money to a person; pass what they were told in message so it can be checked for scams."""
    try:
        amount = float(amount or 0)
        recipient = " ".join((recipient or "").split())[:80]
        if amount <= 0 or not recipient:
            return speak("Who would you like to send money to, and how much?", data={"category": "person_payment", "outcome": "needs_details"})
        summary = f"send {money_str(amount)} to {recipient}"
        decision = policy.check("person", recipient, amount, user_id, message_text=message)
        if decision.needs_approval:
            if approvals.find_pending(user_id, "pay_person", recipient=recipient, amount=amount):
                return speak(
                    f"I've already asked {decision.family_name} about that. I'll tell you as soon as they answer.",
                    data={"category": "person_payment", "outcome": "approval_pending"},
                )
            _request_approval(
                user_id,
                "pay_person",
                {"recipient": recipient, "amount": amount, "summary": summary, "flags": decision.flags,
                 "done_say": f"I sent {money_str(amount)} to {recipient}."},
                decision,
                summary,
                "person_payment",
            )
            say = f"Before I {summary}, I'd like to check with {decision.family_name}, because {decision.reason}."
            if decision.flags:
                say += " Please don't share any numbers with them in the meantime."
            return speak(say, data={"category": "person_payment", "outcome": "approval_requested", "reason": decision.reason})
        action_id = pending.create("pay_person", user_id, recipient=recipient, amount=amount)
    except Exception:  # noqa: BLE001
        log.exception("prepare_payment_to_person failed")
        return speak("I couldn't set that up just now. Want me to try again?", data={"category": "person_payment", "outcome": "error"})
    return speak(
        f"That's {money_str(amount)} to {recipient}. Should I send it?",
        action_id=action_id,
        data={"category": "person_payment", "outcome": "read_back"},
    )


@money.tool()
def confirm_payment_to_person(user_id: str, action_id: str) -> str:
    """Send the money only after prepare_payment_to_person was read back and the user clearly said yes."""
    try:
        payload = pending.consume(action_id, "pay_person", user_id)
    except PendingActionError as err:
        return speak(err.say, data={"category": "person_payment", "outcome": "error"})
    recipient = str(payload.get("recipient"))
    amount = float(payload.get("amount") or 0)
    try:
        decision = policy.check("person", recipient, amount, user_id)
        if decision.needs_approval:
            summary = f"send {money_str(amount)} to {recipient}"
            _request_approval(
                user_id, "pay_person",
                {"recipient": recipient, "amount": amount, "summary": summary,
                 "done_say": f"I sent {money_str(amount)} to {recipient}."},
                decision, summary, "person_payment",
            )
            return speak(
                f"I'd like to check with {decision.family_name} first, because {decision.reason}. I'll let you know.",
                data={"category": "person_payment", "outcome": "approval_requested"},
            )
        _send_to_person(user_id, recipient, amount)
    except Exception:  # noqa: BLE001
        log.exception("confirm_payment_to_person failed")
        return speak("I couldn't send that just now. Want me to try again?", data={"category": "person_payment", "outcome": "error"})
    return speak(
        f"Done. I sent {money_str(amount)} to {recipient}, and I've let your family know.",
        data={"category": "person_payment", "outcome": "paid"},
    )


def _scam_emails(user_id: str) -> list[dict]:
    rows = (
        db.get_client()
        .table("emails")
        .select("*")
        .eq("user_id", user_id)
        .eq("classification", "scam")
        .order("received_at", desc=True)
        .execute()
        .data
    )
    return rows


def _email_label(row: dict) -> str:
    labels = (row.get("extracted") or {}).get("scam_labels") or []
    return labels[0] if labels else "something suspicious"


def _match_email(user_id: str, text: str) -> dict | None:
    wanted = _words(text)
    if not wanted:
        return None
    rows = db.get_client().table("emails").select("*").eq("user_id", user_id).execute().data
    best, best_score = None, 0
    for row in rows:
        score = len(wanted & _words(f"{row.get('subject', '')} {row.get('sender', '')}"))
        if score > best_score or (score == best_score and score and row.get("classification") == "scam"):
            best, best_score = row, score
    return best


@money.tool()
def check_message_for_scam(user_id: str, text: str) -> str:
    """Check whether an email, text, or phone call the user describes looks like a scam, such as "is this email real?"."""
    try:
        family = policy.approver_name(user_id)
        email = _match_email(user_id, text)
        flags = policy.scam_flags(text)
        if email and email.get("classification") == "scam":
            label = _email_label(email)
        elif flags:
            label = flags[0]
        else:
            label = ""
        if label:
            what = "That email" if email and email.get("classification") == "scam" else "That"
            activity.log_event(
                user_id, "scam_check", f"Checked a message that looks like {label}",
                {"email_id": email["id"] if email else None, "label": label, "category": "scam_check"},
            )
            return speak(
                f"{what} looks like {label}. Please don't reply, click anything, or send money. Want me to let {family} know?",
                data={"category": "scam_check", "outcome": "scam_suspected", "label": label},
            )
        if email:
            extra = email.get("extracted") or {}
            source = extra.get("payee") or extra.get("title") or "someone you know"
            say = f"That one looks like a normal message about {source}. Still, never share account numbers by phone or email."
        else:
            say = f"I don't see the usual warning signs. If anyone asks for money, gift cards, or personal numbers, it's safest to check with {family} first."
    except Exception:  # noqa: BLE001
        log.exception("check_message_for_scam failed")
        return speak("I couldn't check that just now. Want me to try again?", data={"category": "scam_check", "outcome": "error"})
    return speak(say, data={"category": "scam_check", "outcome": "no_flags"})


@money.tool()
def list_suspicious_emails(user_id: str) -> str:
    """Tell the user about recent emails that look like scams, for the morning briefing or when they ask."""
    try:
        rows = _scam_emails(user_id)
        family = policy.approver_name(user_id)
    except Exception:  # noqa: BLE001
        return speak("I couldn't check your email just now. Want me to try again?", data={"category": "scam_check", "outcome": "error"})
    if not rows:
        return speak("I didn't see any suspicious emails.", data={"category": "scam_check", "outcome": "resolved"})
    labels = [_email_label(r) for r in rows[:3]]
    if len(rows) == 1:
        say = f"I found one email that looks like {labels[0]}."
    else:
        listed = ", ".join(f"one that looks like {lbl}" for lbl in labels[:-1]) + f", and one that looks like {labels[-1]}"
        say = f"I found {len(rows)} emails that look like scams: {listed}."
    say += f" Please don't reply or pay anything. Want me to tell {family}?"
    return speak(
        say,
        data={
            "category": "scam_check",
            "outcome": "scam_suspected",
            "emails": [{"id": r["id"], "label": _email_label(r), "subject": r.get("subject", "")} for r in rows[:3]],
        },
    )
