"""Talk to Gary in the terminal: same Deepgram agent, same model, prompt, and MCP tools as a call.

  uv run python scripts/chat_gary.py            # inbound call persona
  uv run python scripts/chat_gary.py --reason reminder --reminder-text "take your pill"

Runs the FastAPI lifespan (MCP servers, adapter, browser runner) in-process with the reminder
scheduler off, opens a Deepgram Voice Agent session through the real voice bridge with a fake
Twilio socket (audio is discarded), and feeds your typed lines in as InjectUserMessage. Agent
replies arrive as ConversationText and are printed; tool calls and their `say` are shown too.
Type /quit to exit.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("GARY_NO_SCHEDULER", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("browser_agent.runner").setLevel(logging.INFO)

from config import settings  # noqa: E402


class FakeTwilioWS:
    """Looks like a Twilio Media Stream: one start event, then silence until we hang up."""

    def __init__(self, params: dict):
        self._params = params
        self._sent_start = False
        self.hangup = asyncio.Event()

    async def accept(self): ...

    async def close(self): ...

    async def send_text(self, _text: str):  # agent audio frames and clear events, discarded
        ...

    async def receive_text(self) -> str:
        if not self._sent_start:
            self._sent_start = True
            return json.dumps({"event": "start", "start": {"streamSid": "MZconsole", "callSid": "CAconsole", "customParameters": self._params}})
        await self.hangup.wait()
        return json.dumps({"event": "stop"})


def make_session_class():
    from voice.bridge import VoiceAgentSession

    class ConsoleSession(VoiceAgentSession):
        def __init__(self, ws, adapter):
            super().__init__(ws, adapter)
            self.ready = asyncio.Event()

        async def handle_deepgram_message(self, msg: dict):
            t = msg.get("type")
            if t == "SettingsApplied":
                self.ready.set()
            elif t == "ConversationText":
                role = msg.get("role")
                if role == "assistant":
                    print(f"\nGary: {msg.get('content')}", flush=True)
                    print("you> ", end="", flush=True)
            elif t == "InjectionRefused":
                print("\n[injection refused by Deepgram: agent or user was mid-turn]", flush=True)
            elif t == "Error":
                print(f"\n[deepgram error] {msg}", flush=True)
            return await super().handle_deepgram_message(msg)

        async def _handle_function_call(self, fn: dict) -> None:
            name = fn.get("name", "")
            raw = fn.get("arguments") or "{}"
            print(f"\n   [tool] {name}({raw})", flush=True)
            await super()._handle_function_call(fn)

        async def say_user(self, text: str) -> None:
            await self.dg.send(json.dumps({"type": "InjectUserMessage", "content": text}))

    return ConsoleSession


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", default="inbound", choices=["inbound", "reminder", "morning_briefing", "appointment"])
    ap.add_argument("--reminder-text", default="")
    ap.add_argument("--user-id", default=settings.demo_user_id)
    args = ap.parse_args()
    if not settings.deepgram_api_key:
        raise SystemExit("DEEPGRAM_API_KEY is not set")

    from main import app  # starts nothing until the lifespan below

    params = {"user_id": args.user_id, "reason": args.reason, "reminder_text": args.reminder_text}
    ws = FakeTwilioWS(params)
    print("Starting Gary (MCP servers, browser agent)…", flush=True)
    async with app.router.lifespan_context(app):
        ConsoleSession = make_session_class()
        session = ConsoleSession(ws, app.state.adapter)
        run_task = asyncio.create_task(session.run())
        try:
            await asyncio.wait_for(session.ready.wait(), 20)
        except asyncio.TimeoutError:
            print("Deepgram did not accept the settings in time. Check DEEPGRAM_API_KEY and the backend log.")
            ws.hangup.set()
            await run_task
            return
        print(f"Connected. Persona: {args.reason}. Type what {session.user_name} would say; /quit to hang up.", flush=True)
        print("you> ", end="", flush=True)
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:  # EOF
                await asyncio.sleep(30)  # give background jobs (orders) a chance to finish and speak
                break
            line = line.strip()
            if not line:
                print("you> ", end="", flush=True)
                continue
            if line in ("/quit", "/q", "/exit"):
                break
            await session.say_user(line)
        ws.hangup.set()
        try:
            await asyncio.wait_for(run_task, 10)
        except asyncio.TimeoutError:
            run_task.cancel()
    print("\nHung up.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nHung up.")
