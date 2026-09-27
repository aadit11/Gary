import base64
import json

import pytest

from core.speech import speak
from voice.bridge import ACTIVE_SESSIONS, VoiceAgentSession


class FakeTwilioWS:
    def __init__(self):
        self.sent = []

    async def accept(self): ...
    async def close(self): ...
    async def send_text(self, s):
        self.sent.append(json.loads(s))


class FakeDG:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class FakeAdapter:
    def __init__(self):
        self.calls = []
        self.result = None

    async def call(self, name, args, user_id):
        self.calls.append((name, args, user_id))
        return self.result or speak(f"ran {name}")


@pytest.fixture
def session(demo):
    s = VoiceAgentSession(FakeTwilioWS(), FakeAdapter())
    s.handle_start({"streamSid": "MZ1", "callSid": "CA1", "customParameters": {"user_id": demo["user_id"], "reason": "inbound"}})
    s.dg = FakeDG()
    s.settings_sent = True
    return s


async def test_start_params(session, demo):
    assert session.stream_sid == "MZ1" and session.call_sid == "CA1"
    assert session.user_id == demo["user_id"] and session.reason == "inbound"


async def test_audio_to_twilio_is_base64_media_frame(session):
    await session.send_twilio_audio(b"\x00\x01\x02")
    frame = session.twilio_ws.sent[-1]
    assert frame["event"] == "media" and frame["streamSid"] == "MZ1"
    assert base64.b64decode(frame["media"]["payload"]) == b"\x00\x01\x02"


async def test_user_started_speaking_clears_twilio(session):
    await session.handle_deepgram_message({"type": "UserStartedSpeaking"})
    assert session.twilio_ws.sent[-1] == {"event": "clear", "streamSid": "MZ1"}


async def test_function_call_roundtrip(session, demo):
    await session.handle_deepgram_message({
        "type": "FunctionCallRequest",
        "functions": [{"id": "fc_1", "name": "list_bills_due", "arguments": "{\"x\": 1}", "client_side": True}],
    })
    assert session.adapter.calls == [("list_bills_due", {"x": 1}, demo["user_id"])]
    reply = json.loads(session.dg.sent[-1])
    assert reply["type"] == "FunctionCallResponse" and reply["id"] == "fc_1" and reply["name"] == "list_bills_due"
    assert isinstance(reply["content"], str) and json.loads(reply["content"])["say"] == "ran list_bills_due"


async def test_tool_log_stores_category_and_redacts_digits(session, demo):
    from core import db
    from core.speech import speak

    session.adapter.result = speak("Noted.", data={"category": "money_screened", "outcome": "summarized_to_family"})
    await session.handle_deepgram_message({
        "type": "FunctionCallRequest",
        "functions": [{"id": "fc_9", "name": "summarize_for_family", "arguments": '{"summary": "card 4111111111111111"}', "client_side": True}],
    })
    rows = db.get_client().table("activity_log").select("*").eq("kind", "tool_called").execute().data
    blob = json.dumps(rows)
    assert "4111111111111111" not in blob
    assert "[redacted]" in blob
    assert rows[-1]["data"]["category"] == "money_screened"
    assert rows[-1]["data"]["outcome"] == "summarized_to_family"
    assert session.last_category == "money_screened"
    assert session.last_outcome == "summarized_to_family"


async def test_owned_tool_runs_even_if_marked_server_side(session):
    session.adapter.tool_names = lambda: ["get_upcoming_appointments"]
    await session.handle_deepgram_message({
        "type": "FunctionCallRequest",
        "functions": [{"id": "fc_2", "name": "get_upcoming_appointments", "arguments": "{}", "client_side": False}],
    })
    assert session.adapter.calls[0][0] == "get_upcoming_appointments"
    assert json.loads(session.dg.sent[-1])["type"] == "FunctionCallResponse"


async def test_server_side_functions_are_skipped(session):
    await session.handle_deepgram_message({"type": "FunctionCallRequest", "functions": [{"id": "1", "name": "x", "arguments": "{}", "client_side": False}]})
    assert session.adapter.calls == [] and session.dg.sent == []


async def test_error_ends_call(session):
    assert await session.handle_deepgram_message({"type": "Error", "description": "boom"}) is False


async def test_inject_sends_interrupt(session):
    await session.inject("Your son said no.")
    assert json.loads(session.dg.sent[-1]) == {"type": "InjectAgentMessage", "message": "Your son said no.", "behavior": "interrupt"}


async def test_injection_module_targets_active_session(session, demo):
    from core.models import Approval
    from voice import injection

    ACTIVE_SESSIONS[demo["user_id"]] = session
    try:
        injection.on_approval_resolved(Approval(id="a", user_id=demo["user_id"], family_contact_id=demo["family_id"], action="pay_person", status="denied"))
        import asyncio
        await asyncio.sleep(0)
        msg = json.loads(session.dg.sent[-1])
        assert msg["type"] == "InjectAgentMessage" and "David" in msg["message"] and "won't" in msg["message"]
    finally:
        ACTIVE_SESSIONS.pop(demo["user_id"], None)
