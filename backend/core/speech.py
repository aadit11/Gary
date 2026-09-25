"""speak() response helper and money/date formatting for TTS.

Every MCP tool returns `speak(...)`, a JSON string:
    {"say": "One or two sentences.", "action_id": "optional", "data": {}}
The voice agent speaks only `say`. Never put IDs, JSON, or markdown in `say`.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


def speak(say: str, action_id: str | None = None, data: dict[str, Any] | None = None) -> str:
    body: dict[str, Any] = {"say": say.strip()}
    if action_id:
        body["action_id"] = action_id
    if data:
        body["data"] = data
    return json.dumps(body, default=str)


def money_str(amount: float | int | str) -> str:
    """84.2 -> "$84.20"."""
    return f"${float(amount):,.2f}"


def date_str(value: date | datetime | str | None) -> str:
    """datetime -> "Friday, September 25 at 2 PM"; date -> "Friday, September 25"."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        day = f"{value.strftime('%A, %B')} {value.day}"
        hour = value.hour % 12 or 12
        ampm = "AM" if value.hour < 12 else "PM"
        time = f"{hour} {ampm}" if value.minute == 0 else f"{hour}:{value.minute:02d} {ampm}"
        return f"{day} at {time}"
    return f"{value.strftime('%A, %B')} {value.day}"
