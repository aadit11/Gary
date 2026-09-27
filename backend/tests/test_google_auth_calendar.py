"""Tests for google/auth.py and google/calendar.py helpers (no live Google calls)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from google.auth import GoogleAuthError, credentials_configured, get_credentials
from google.calendar import create_event, list_upcoming
from google._thirdparty import load as load_google_api


def test_thirdparty_load_returns_credentials_class():
    api = load_google_api()
    assert "Credentials" in api and "build" in api and "Request" in api
    # Local package must still be importable after loading site-packages google.*
    from google import ingestion  # noqa: F401
    from google import gmail  # noqa: F401


def test_credentials_configured_false_without_env(monkeypatch):
    monkeypatch.setattr("google.auth.settings.google_client_id", "")
    monkeypatch.setattr("google.auth.settings.google_client_secret", "")
    monkeypatch.setattr("google.auth.settings.google_refresh_token", "")
    assert credentials_configured() is False
    with pytest.raises(GoogleAuthError):
        get_credentials(refresh=False)


def test_get_credentials_builds_without_refresh(monkeypatch):
    monkeypatch.setattr("google.auth.settings.google_client_id", "cid")
    monkeypatch.setattr("google.auth.settings.google_client_secret", "sec")
    monkeypatch.setattr("google.auth.settings.google_refresh_token", "rtok")
    creds = get_credentials(refresh=False)
    assert creds.refresh_token == "rtok"
    assert creds.client_id == "cid"


def test_list_upcoming_parses_events():
    svc = MagicMock()
    svc.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "ev1",
                "summary": "Dr. Patel appointment",
                "location": "Springfield Medical",
                "description": "seed",
                "start": {"dateTime": "2026-09-26T14:00:00-04:00"},
                "end": {"dateTime": "2026-09-26T14:45:00-04:00"},
            }
        ]
    }
    rows = list_upcoming(service=svc, timezone_name="America/New_York", days=2)
    assert len(rows) == 1
    assert rows[0]["summary"] == "Dr. Patel appointment"
    assert "2026-09-26" in rows[0]["start"]
    svc.events.return_value.list.assert_called_once()


def test_create_event_posts_body():
    svc = MagicMock()
    svc.events.return_value.insert.return_value.execute.return_value = {
        "id": "new1",
        "summary": "Dr. Patel appointment",
        "htmlLink": "https://calendar.google.com/event?eid=1",
        "start": {"dateTime": "2026-09-26T14:00:00-04:00"},
        "end": {"dateTime": "2026-09-26T14:45:00-04:00"},
    }
    tz = ZoneInfo("America/New_York")
    start = datetime(2026, 9, 26, 14, 0, tzinfo=tz)
    end = datetime(2026, 9, 26, 14, 45, tzinfo=tz)
    created = create_event(
        summary="Dr. Patel appointment",
        start=start,
        end=end,
        timezone_name="America/New_York",
        location="Springfield Medical",
        service=svc,
    )
    assert created["id"] == "new1"
    body = svc.events.return_value.insert.call_args.kwargs["body"]
    assert body["summary"] == "Dr. Patel appointment"
    assert body["start"]["timeZone"] == "America/New_York"
