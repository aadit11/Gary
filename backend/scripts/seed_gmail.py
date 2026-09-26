"""Insert demo emails into the demo Gmail inbox and ensure the doctor Calendar event exists.

Run from backend/ after google_oauth.py and seed_demo_user.py:
    uv run python scripts/seed_gmail.py

Idempotent for calendar (skips if a matching summary already exists). Emails are always
inserted; re-running creates duplicates unless you delete prior X-Gary-Seed messages.
Ingest is idempotent on gmail_id, so duplicates only matter if you seed twice.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from google.auth import GoogleAuthError, credentials_configured  # noqa: E402
from google.calendar import create_event, find_events_by_summary  # noqa: E402
from google.demo_emails import DEMO_EMAILS, DOCTOR_EVENT  # noqa: E402
from google.gmail import insert_message  # noqa: E402


def _profile_email() -> str:
    from google.auth import gmail_service

    profile = gmail_service().users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def _doctor_start(tz_name: str) -> datetime:
    """Next occurrence of the seeded doctor slot (defaults to tomorrow afternoon local)."""
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    # Prefer the hard-coded demo day in DEMO bodies (Sep 26, 2026) when still in the future.
    target = datetime(2026, 9, 26, DOCTOR_EVENT["start_hour"], DOCTOR_EVENT["start_minute"], tzinfo=tz)
    if target < now - timedelta(hours=1):
        target = (now + timedelta(days=1)).replace(
            hour=DOCTOR_EVENT["start_hour"],
            minute=DOCTOR_EVENT["start_minute"],
            second=0,
            microsecond=0,
        )
    return target


def main() -> None:
    if not credentials_configured():
        raise SystemExit(
            "Google OAuth not configured. Run: uv run python scripts/google_oauth.py"
        )
    try:
        me = _profile_email()
    except GoogleAuthError as err:
        raise SystemExit(str(err)) from err

    print(f"Seeding Gmail inbox for {me}")
    for item in DEMO_EMAILS:
        mid = insert_message(
            sender=item["sender"],
            to=me,
            subject=item["subject"],
            body=item["body"],
            seed=True,
        )
        print(f"  + [{item['classification']}] {item['subject'][:60]!r} -> {mid}")

    tz_name = "America/New_York"
    existing = find_events_by_summary(DOCTOR_EVENT["summary"], days=21, timezone_name=tz_name)
    if existing:
        print(f"Calendar event already present: {existing[0]['id']} ({existing[0]['start']})")
    else:
        start = _doctor_start(tz_name)
        end = start + timedelta(minutes=DOCTOR_EVENT["duration_minutes"])
        created = create_event(
            summary=DOCTOR_EVENT["summary"],
            start=start,
            end=end,
            timezone_name=tz_name,
            location=DOCTOR_EVENT["location"],
            description=DOCTOR_EVENT["description"],
        )
        print(f"Calendar event created: {created['id']} at {created['start']}")

    print("\nNext: uv run python scripts/ingest_gmail.py")
    if not settings.demo_user_id:
        print("Warning: DEMO_USER_ID is empty — set it from seed_demo_user.py before ingesting.")


if __name__ == "__main__":
    main()
