"""Place one outbound reminder call to the demo user, creating a sample reminder if none exists.

Run from backend/ with the backend and ngrok running:  uv run python scripts/place_reminder_call.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.getLogger("httpx").setLevel(logging.WARNING)

from config import settings  # noqa: E402
from core import db  # noqa: E402
from voice.twilio_routes import place_outbound_call  # noqa: E402


def main() -> None:
    uid = settings.demo_user_id
    if not uid:
        raise SystemExit("DEMO_USER_ID is not set in .env (run scripts/seed_demo_user.py first)")
    rows = db.get_client().table("reminders").select("*").eq("user_id", uid).execute().data
    if rows:
        rem = rows[0]
    else:
        rem = db.get_client().table("reminders").insert(
            {"user_id": uid, "message": "It's time to take your morning blood pressure pill with a glass of water.",
             "time_of_day": "08:00", "recurrence": "daily"}
        ).execute().data[0]
    print("reminder:", rem["message"])
    sid = place_outbound_call(uid, "reminder", reminder_id=rem["id"])
    print("call sid:", sid or "FAILED (see backend log)")


if __name__ == "__main__":
    main()
