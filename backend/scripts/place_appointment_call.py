"""Place the appointment call to the demo user now (the scheduler only does it at 9:00 local).

Run from backend/ with the backend and ngrok running:

  uv run python scripts/place_appointment_call.py                   # next Dr. Patel appointment as saved
  uv run python scripts/place_appointment_call.py --in-minutes 60   # first move it to an hour from now
  uv run python scripts/place_appointment_call.py --medication ""   # skip the medication opener
  uv run python scripts/place_appointment_call.py --match "prescription"

The call opens with the medication reminder ("It's time for your daily magnesium glycinate"),
waits for the person to say they took it, then says "according to your email you have
<appointment> in about an hour at <place>" and offers a ride; prepare_ride holds a place the
family has not saved for their okay by text.
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.getLogger("httpx").setLevel(logging.WARNING)

from config import settings  # noqa: E402
from core import db  # noqa: E402
from core.speech import date_str  # noqa: E402
from voice.twilio_routes import place_outbound_call  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="Dr. Patel", help="pick the appointment whose title or subject contains this")
    ap.add_argument("--in-minutes", type=int, default=None, help="move the appointment to this many minutes from now first")
    ap.add_argument("--medication", default="magnesium glycinate", help="open the call with this daily medication reminder; pass \"\" for none")
    args = ap.parse_args()

    uid = settings.demo_user_id
    if not uid:
        raise SystemExit("DEMO_USER_ID is not set in .env (run scripts/seed_demo_user.py first)")
    client = db.get_client()
    user = client.table("users").select("*").eq("id", uid).limit(1).execute().data[0]
    tz = ZoneInfo(user.get("timezone") or "America/New_York")

    rows = client.table("emails").select("*").eq("user_id", uid).eq("classification", "appointment").execute().data
    rows = [r for r in rows if isinstance(r.get("extracted"), dict) and r["extracted"].get("starts_at")]
    wanted = [r for r in rows if args.match.lower() in ((r["extracted"].get("title") or "") + " " + (r.get("subject") or "")).lower()]
    rows = sorted(wanted or rows, key=lambda r: r["extracted"]["starts_at"])
    if not rows:
        raise SystemExit("no appointment email with a start time; run scripts/seed_gmail.py and scripts/ingest_gmail.py")
    appt = rows[-1] if wanted else rows[0]
    extra = dict(appt["extracted"])

    if args.in_minutes is not None:
        starts = (datetime.now(tz) + timedelta(minutes=args.in_minutes)).replace(second=0, microsecond=0)
        extra["starts_at"] = starts.isoformat()
        extra["when"] = date_str(starts)
        client.table("emails").update({"extracted": extra}).eq("id", appt["id"]).execute()
        print(f"moved the appointment to {date_str(starts)}")

    starts_local = datetime.fromisoformat(extra["starts_at"]).astimezone(tz)
    title = extra.get("title") or appt.get("subject") or "an appointment"
    minutes = (starts_local - datetime.now(tz)).total_seconds() / 60
    if 40 <= minutes <= 80:
        when = "in about an hour"
    elif 5 <= minutes < 40:
        when = f"in about {int(round(minutes / 5) * 5)} minutes"
    else:
        when = f"on {date_str(starts_local)}"
    if title.lower().startswith("dr"):
        title = f"a doctor's appointment with {title}"
    note = f"Appointment: {title} {when}"
    if extra.get("location"):
        note += f" at {str(extra['location']).rstrip('.')}"
    if args.medication.strip():
        note = f"Medication reminder: their daily {args.medication.strip()}. {note}"
    print("call text:", note)
    sid = place_outbound_call(uid, "appointment", note=note)
    print("call sid:", sid or "FAILED (see backend log)")


if __name__ == "__main__":
    main()
