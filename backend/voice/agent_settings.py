"""Deepgram Voice Agent settings: audio format, listen/think/speak providers, turn-taking, prompts.

Turn-taking is tuned for older adults who pause mid-sentence. Don't make it more aggressive
without testing with deliberately slow speech.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import settings

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Twilio Media Streams are mulaw at 8 kHz in both directions.
AUDIO = {
    "input": {"encoding": "mulaw", "sample_rate": 8000},
    "output": {"encoding": "mulaw", "sample_rate": 8000, "container": "none"},
}

# English now. A later language is another entry here, not a change to the bridge.
CALL_LANGUAGE = "en"
VOICES: dict[str, dict[str, str]] = {
    "en": {
        "language": "en",
        "listen_model": "flux-general-en",
        "speak_model": "flux-cole-en",
    }
}

# Flux end-of-turn. High threshold and a long timeout wait through slow speech and thinking.
# Do not set eager_eot_threshold; that starts a reply before the person has finished.
_voice = VOICES[CALL_LANGUAGE]
LISTEN = {
    "provider": {
        "type": "deepgram",
        "version": "v2",
        "model": _voice["listen_model"],
        "eot_threshold": 0.85,
        "eot_timeout_ms": 15000,
    }
}

# Which MCP servers each call type can use. Fewer tools = better tool selection.
SERVERS_BY_REASON: dict[str, list[str]] = {
    "inbound": ["checkins", "money", "orders", "mobility"],
    "morning_briefing": ["checkins", "money", "mobility"],
    "reminder": ["checkins"],
    "appointment": ["checkins", "mobility"],
}

GREETINGS = {
    "inbound": "Hello {user_name}, this is Gary. How can I help you today?",
    "morning_briefing": "Good morning {user_name}, it's Gary calling with your morning check-in. How did you sleep?",
    "reminder": "Hello {user_name}, it's Gary calling with a quick reminder.",
    "appointment": "Hello {user_name}, it's Gary calling.",
}


def servers_for(reason: str) -> list[str]:
    return SERVERS_BY_REASON.get(reason, SERVERS_BY_REASON["inbound"])


def today_str(tz: str = "America/New_York") -> str:
    now = datetime.now(ZoneInfo(tz))
    return f"{now.strftime('%A, %B')} {now.day}"


def load_prompt(reason: str, **vars: Any) -> str:
    """Base prompt plus the call-type addition, with {placeholders} filled."""
    vars.setdefault("user_name", "there")
    vars.setdefault("today", today_str())
    vars.setdefault("reminder_text", "")
    text = (PROMPTS_DIR / "base.md").read_text()
    extra = {
        "inbound": "inbound.md",
        "morning_briefing": "morning_checkin.md",
        "reminder": "reminder.md",
        "appointment": "appointment.md",
    }.get(reason)
    if extra:
        text += "\n\n" + (PROMPTS_DIR / extra).read_text()
    return text.format(**vars)


def greeting_for(reason: str, user_name: str) -> str:
    return GREETINGS.get(reason, GREETINGS["inbound"]).format(user_name=user_name)


def build_settings(functions: list[dict], prompt: str, greeting: str) -> dict:
    """The full Deepgram `Settings` message (first message on the socket)."""
    return {
        "type": "Settings",
        "audio": AUDIO,
        "agent": {
            "language": _voice["language"],
            "listen": LISTEN,
            "think": {
                "provider": {"type": "open_ai", "model": settings.deepgram_think_model, "temperature": 0.3},
                "prompt": prompt,
                "functions": functions,
            },
            "speak": {"provider": {"type": "deepgram", "version": "v2", "model": _voice["speak_model"]}},
            "greeting": greeting,
        },
    }
