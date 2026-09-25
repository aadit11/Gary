"""VoiceAgentSession: relays audio and events between a Twilio Media Stream and the Deepgram
Voice Agent API, and routes Deepgram function calls to the MCP adapter.

Twilio -> us:  {"event": "start"|"media"|"stop"|"connected"|"mark", ...}
us -> Twilio:  {"event": "media", "streamSid", "media": {"payload": b64}} and {"event": "clear", "streamSid"}
Deepgram -> us: binary audio frames, or JSON {"type": "UserStartedSpeaking"|"FunctionCallRequest"|...}
us -> Deepgram: Settings (first), binary audio, FunctionCallResponse, InjectAgentMessage, KeepAlive
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from config import settings
from core import activity, db
from voice import agent_settings
from voice.mcp_adapter import MCPAdapter

log = logging.getLogger(__name__)

KEEPALIVE_S = 8

# user_id -> live session, so approvals can be spoken into the call (voice/injection.py).
ACTIVE_SESSIONS: dict[str, "VoiceAgentSession"] = {}


class VoiceAgentSession:
    def __init__(self, twilio_ws: Any, adapter: MCPAdapter, deepgram_connect: Any = None):
        self.twilio_ws = twilio_ws
        self.adapter = adapter
        self._connect = deepgram_connect or _default_connect
        self.dg: Any = None
        self.stream_sid: str | None = None
        self.call_sid: str | None = None
        self.user_id: str = settings.demo_user_id
        self.user_name: str = "there"
        self.reason: str = "inbound"
        self.reminder_text: str = ""
        self.settings_sent = False

    # --- entry point -----------------------------------------------------
    async def run(self) -> None:
        await self.twilio_ws.accept()
        if not await self._wait_for_start():
            return
        self._load_user()
        prompt = agent_settings.load_prompt(
            self.reason, user_name=self.user_name, reminder_text=self.reminder_text, today=agent_settings.today_str(self.user_tz)
        )
        functions = self.adapter.deepgram_functions(agent_settings.servers_for(self.reason))
        settings_msg = agent_settings.build_settings(functions, prompt, agent_settings.greeting_for(self.reason, self.user_name))
        log.info("call %s: reason=%s user=%s tools=%s", self.call_sid, self.reason, self.user_id, [f["name"] for f in functions])

        activity.log_event(self.user_id, "call_started", f"{self.reason} call started", {"call_sid": self.call_sid})
        ACTIVE_SESSIONS[self.user_id] = self
        try:
            async with self._connect() as dg:
                self.dg = dg
                await dg.send(json.dumps(settings_msg))
                self.settings_sent = True
                tasks = [
                    asyncio.create_task(self._twilio_to_deepgram(), name="twilio->dg"),
                    asyncio.create_task(self._deepgram_to_twilio(), name="dg->twilio"),
                    asyncio.create_task(self._keepalive(), name="keepalive"),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                for t in done:
                    if t.exception() and not isinstance(t.exception(), asyncio.CancelledError):
                        log.error("call %s: %s ended with %r", self.call_sid, t.get_name(), t.exception())
        except Exception:  # noqa: BLE001
            log.exception("call %s: bridge failed", self.call_sid)
        finally:
            ACTIVE_SESSIONS.pop(self.user_id, None)
            self._mark_call_ended()
            activity.log_event(self.user_id, "call_ended", f"{self.reason} call ended", {"call_sid": self.call_sid})
            try:
                await self.twilio_ws.close()
            except Exception:  # noqa: BLE001
                pass

    # --- setup -----------------------------------------------------------
    async def _wait_for_start(self) -> bool:
        while True:
            msg = json.loads(await self.twilio_ws.receive_text())
            event = msg.get("event")
            if event == "start":
                self.handle_start(msg["start"])
                return True
            if event == "stop":
                return False

    def handle_start(self, start: dict) -> None:
        self.stream_sid = start.get("streamSid")
        self.call_sid = start.get("callSid")
        params = start.get("customParameters") or {}
        self.user_id = params.get("user_id") or settings.demo_user_id
        self.reason = params.get("reason") or "inbound"
        self.reminder_text = params.get("reminder_text") or ""

    def _load_user(self) -> None:
        self.user_tz = "America/New_York"
        try:
            rows = db.get_client().table("users").select("*").eq("id", self.user_id).limit(1).execute().data
            if rows:
                self.user_name = (rows[0].get("name") or "there").split(" ")[0]
                self.user_tz = rows[0].get("timezone") or self.user_tz
        except Exception:  # noqa: BLE001
            log.exception("user lookup failed")

    def _mark_call_ended(self) -> None:
        if not self.call_sid:
            return
        try:
            db.get_client().table("calls").update({"ended_at": db.now_iso()}).eq("twilio_sid", self.call_sid).execute()
        except Exception:  # noqa: BLE001
            log.exception("calls.ended_at update failed")

    # --- pumps -----------------------------------------------------------
    async def _twilio_to_deepgram(self) -> None:
        while True:
            msg = json.loads(await self.twilio_ws.receive_text())
            event = msg.get("event")
            if event == "media":
                await self.dg.send(base64.b64decode(msg["media"]["payload"]))
            elif event == "stop":
                log.info("call %s: twilio stop", self.call_sid)
                return

    async def _deepgram_to_twilio(self) -> None:
        while True:
            raw = await self.dg.recv()
            if isinstance(raw, (bytes, bytearray)):
                await self.send_twilio_audio(bytes(raw))
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if await self.handle_deepgram_message(msg) is False:
                return

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_S)
            await self.dg.send(json.dumps({"type": "KeepAlive"}))

    # --- message handlers (pure enough to unit test) ---------------------
    async def send_twilio_audio(self, audio: bytes) -> None:
        if not self.stream_sid:
            return
        payload = base64.b64encode(audio).decode()
        await self.twilio_ws.send_text(json.dumps({"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}}))

    async def clear_twilio_audio(self) -> None:
        if self.stream_sid:
            await self.twilio_ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))

    async def handle_deepgram_message(self, msg: dict) -> bool | None:
        """Return False to end the call."""
        t = msg.get("type")
        if t == "UserStartedSpeaking":
            await self.clear_twilio_audio()
        elif t == "FunctionCallRequest":
            for fn in msg.get("functions", []):
                if fn.get("client_side") is False:
                    continue
                await self._handle_function_call(fn)
        elif t == "ConversationText":
            log.info("call %s [%s] %s", self.call_sid, msg.get("role"), msg.get("content"))
        elif t == "InjectionRefused":
            log.warning("call %s: injection refused", self.call_sid)
        elif t == "Error":
            log.error("call %s: deepgram error %s", self.call_sid, msg)
            return False
        elif t == "Warning":
            log.warning("call %s: deepgram warning %s", self.call_sid, msg)
        elif t in ("Welcome", "SettingsApplied", "AgentThinking", "AgentStartedSpeaking", "AgentAudioDone", "PromptUpdated", "History", "LatencyReport"):
            pass
        else:
            log.debug("call %s: unhandled deepgram message %s", self.call_sid, t)
        return None

    async def _handle_function_call(self, fn: dict) -> None:
        name = fn.get("name", "")
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except json.JSONDecodeError:
            args = {}
        log.info("call %s: tool %s %s", self.call_sid, name, args)
        content = await self.adapter.call(name, args, self.user_id)
        activity.log_event(self.user_id, "tool_called", f"{name}", {"call_sid": self.call_sid, "args": args})
        await self.dg.send(json.dumps({"type": "FunctionCallResponse", "id": fn.get("id"), "name": name, "content": content}))

    async def inject(self, text: str, behavior: str = "interrupt") -> None:
        """Make the agent say `text` now (approval results)."""
        if self.dg is None or not self.settings_sent:
            return
        await self.dg.send(json.dumps({"type": "InjectAgentMessage", "message": text, "behavior": behavior}))


def _default_connect():
    import websockets

    return websockets.connect(
        settings.deepgram_agent_url,
        additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
        max_size=None,
    )
