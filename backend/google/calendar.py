"""Google Calendar: list upcoming events and create events for the demo account."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .auth import calendar_service

log = logging.getLogger(__name__)


def _as_aware(dt: datetime, tz_name: str) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


def list_upcoming(
    *,
    days: int = 2,
    timezone_name: str = "America/New_York",
    max_results: int = 10,
    service: Any | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Upcoming events on the primary calendar within `days` (user-local window).

    Each item: {id, summary, start, end, location, description}.
    `start` / `end` are ISO-8601 strings (date or dateTime as returned by Google).
    """
    svc = service or calendar_service()
    tz = ZoneInfo(timezone_name)
    now_local = (now or datetime.now(timezone.utc)).astimezone(tz)
    time_min = now_local.isoformat()
    time_max = (now_local + timedelta(days=days)).isoformat()
    resp = (
        svc.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        )
        .execute()
    )
    out: list[dict[str, Any]] = []
    for ev in resp.get("items") or []:
        start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date") or ""
        end = (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date") or ""
        out.append(
            {
                "id": ev.get("id") or "",
                "summary": ev.get("summary") or "",
                "start": start,
                "end": end,
                "location": ev.get("location") or "",
                "description": ev.get("description") or "",
            }
        )
    return out


def create_event(
    *,
    summary: str,
    start: datetime,
    end: datetime,
    timezone_name: str = "America/New_York",
    location: str = "",
    description: str = "",
    service: Any | None = None,
) -> dict[str, Any]:
    """Create a timed event on the primary calendar. Returns {id, summary, start, end, html_link}."""
    svc = service or calendar_service()
    start = _as_aware(start, timezone_name)
    end = _as_aware(end, timezone_name)
    body: dict[str, Any] = {
        "summary": summary,
        "location": location,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": timezone_name},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone_name},
    }
    created = svc.events().insert(calendarId="primary", body=body).execute()
    return {
        "id": created.get("id") or "",
        "summary": created.get("summary") or summary,
        "start": (created.get("start") or {}).get("dateTime") or "",
        "end": (created.get("end") or {}).get("dateTime") or "",
        "html_link": created.get("htmlLink") or "",
    }


def find_events_by_summary(
    summary: str,
    *,
    days: int = 14,
    timezone_name: str = "America/New_York",
    service: Any | None = None,
) -> list[dict[str, Any]]:
    """Find upcoming events whose summary matches exactly (used to keep seed idempotent)."""
    wanted = summary.strip().lower()
    return [
        e
        for e in list_upcoming(days=days, timezone_name=timezone_name, max_results=50, service=service)
        if (e.get("summary") or "").strip().lower() == wanted
    ]
