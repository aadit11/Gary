"""/voice/incoming, /voice/outbound-twiml, /voice/stream (WebSocket), and place_outbound_call()."""

from __future__ import annotations

import logging
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from fastapi import APIRouter, Form, Request, WebSocket
from fastapi.responses import Response

from config import settings
from core import db, notify
from voice.bridge import VoiceAgentSession

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


def stream_url() -> str:
    base = settings.public_base_url.rstrip("/")
    return base.replace("https://", "wss://").replace("http://", "ws://") + "/voice/stream"


def twiml_stream(params: dict[str, str]) -> Response:
    """TwiML that opens a bidirectional Media Stream to /voice/stream with custom parameters."""
    parts = "".join(f'<Parameter name="{escape(k)}" value="{escape(str(v))}"/>' for k, v in params.items() if v)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Connect><Stream url="{escape(stream_url())}">{parts}</Stream></Connect></Response>'
    return Response(content=xml, media_type="application/xml")


def _user_for_phone(phone: str) -> dict | None:
    phone = notify.normalize_phone(phone)
    if not phone:
        return None
    rows = db.get_client().table("users").select("*").eq("phone", phone).limit(1).execute().data
    return rows[0] if rows else None


def _record_call(user_id: str, direction: str, reason: str, call_sid: str | None) -> None:
    try:
        db.get_client().table("calls").insert(
            {"user_id": user_id, "direction": direction, "reason": reason, "twilio_sid": call_sid}
        ).execute()
    except Exception:  # noqa: BLE001
        log.exception("calls insert failed")


@router.post("/incoming")
async def incoming(From: str = Form(""), CallSid: str = Form("")) -> Response:  # noqa: N803 (Twilio names)
    user = _user_for_phone(From)
    user_id = user["id"] if user else settings.demo_user_id
    _record_call(user_id, "inbound", "inbound", CallSid)
    return twiml_stream({"user_id": user_id, "reason": "inbound"})


@router.api_route("/outbound-twiml", methods=["GET", "POST"])
async def outbound_twiml(request: Request) -> Response:
    q = request.query_params
    reason = q.get("reason", "reminder")
    user_id = q.get("user_id") or settings.demo_user_id
    reminder_text = q.get("reminder_text") or ""
    if q.get("reminder_id"):
        rows = db.get_client().table("reminders").select("*").eq("id", q["reminder_id"]).limit(1).execute().data
        if rows:
            reminder_text = rows[0]["message"]
    params = {"user_id": user_id, "reason": reason, "reminder_text": reminder_text}
    if q.get("reminder_id"):
        params["reminder_id"] = q["reminder_id"]
    return twiml_stream(params)


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    adapter = ws.app.state.adapter
    await VoiceAgentSession(ws, adapter).run()


def dial_number(call_sid: str, phone: str) -> bool:
    """Replace the live call with a dial to the caregiver. False when the number must not be called."""
    if not call_sid or not notify._can_message(phone):
        return False
    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Dial>{escape(phone)}</Dial></Response>'
    try:
        from twilio.rest import Client

        Client(settings.twilio_account_sid, settings.twilio_auth_token).calls(call_sid).update(twiml=twiml)
    except Exception:  # noqa: BLE001
        log.exception("transfer failed for call %s", call_sid)
        return False
    log.info("call %s: transferring to ...%s", call_sid, phone[-4:])
    return True


def place_outbound_call(user_id: str, reason: str, reminder_id: str | None = None, note: str | None = None) -> str:
    """Ask Twilio to call the user and connect them to the bridge. Returns the call SID ('' on failure)."""
    rows = db.get_client().table("users").select("*").eq("id", user_id).limit(1).execute().data
    if not rows:
        log.error("place_outbound_call: unknown user %s", user_id)
        return ""
    to = rows[0]["phone"]
    params = {"reason": reason, "user_id": user_id}
    if reminder_id:
        params["reminder_id"] = reminder_id
    if note:
        params["reminder_text"] = note
    url = f"{settings.public_base_url.rstrip('/')}/voice/outbound-twiml?{urlencode(params)}"
    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        call = client.calls.create(to=to, from_=settings.twilio_phone_number, url=url, method="POST")
    except Exception:  # noqa: BLE001
        log.exception("outbound call failed to %s", to)
        return ""
    _record_call(user_id, "outbound", reason, call.sid)
    log.info("outbound %s call placed to ...%s sid=%s", reason, to[-4:], call.sid)
    return call.sid
