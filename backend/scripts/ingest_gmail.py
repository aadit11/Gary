"""Pull seeded (or recent) Gmail messages, classify them, and write to Supabase.

Run from backend/:
    uv run python scripts/ingest_gmail.py
    uv run python scripts/ingest_gmail.py --all   # recent inbox, not only X-Gary-Seed

Requires DEMO_USER_ID and Google OAuth env vars. Safe to re-run (idempotent on gmail_id).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from google.auth import GoogleAuthError, credentials_configured  # noqa: E402
from google.ingestion import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Gmail into Gary Supabase tables")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ingest recent mail (newer_than:14d) instead of only X-Gary-Seed messages",
    )
    parser.add_argument("--max", type=int, default=50, help="Max messages to fetch")
    parser.add_argument("--user-id", default="", help="Override DEMO_USER_ID")
    args = parser.parse_args()

    if not credentials_configured():
        raise SystemExit("Google OAuth not configured. Run scripts/google_oauth.py first.")
    uid = args.user_id or settings.demo_user_id
    if not uid:
        raise SystemExit("Set DEMO_USER_ID (from seed_demo_user.py) or pass --user-id")

    query = "newer_than:14d" if args.all else None
    try:
        summary = run(user_id=uid, query=query, max_results=args.max)
    except GoogleAuthError as err:
        raise SystemExit(str(err)) from err

    print(json.dumps({k: summary[k] for k in ("user_id", "queried", "fetched", "counts")}, indent=2))
    for r in summary["results"]:
        print(
            f"  {r['classification']:12} email={r['email_id'][:8]}… "
            f"new={r['created_email']} bill_new={r['created_bill']} "
            f"extracted={r['extracted']}"
        )


if __name__ == "__main__":
    main()
