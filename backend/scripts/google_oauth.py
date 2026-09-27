"""One-time OAuth flow for the Gary demo Gmail account (Testing-mode consent screen).

Run from backend/:
    uv run python scripts/google_oauth.py

Opens a browser, asks you to sign in as the demo Gmail user, then prints
GOOGLE_REFRESH_TOKEN=... to paste into the repo-root .env.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from google._thirdparty import load as load_google_api  # noqa: E402
from google.auth import SCOPES  # noqa: E402


def main() -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the repo-root .env first.")
        print("OAuth consent screen must be in Testing mode; add the demo Gmail as a test user.")
        sys.exit(1)

    api = load_google_api()
    InstalledAppFlow = api["InstalledAppFlow"]
    client_config = {
        "installed": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not creds.refresh_token:
        print("No refresh token returned. Revoke prior access at")
        print("  https://myaccount.google.com/permissions")
        print("then re-run this script with prompt=consent.")
        sys.exit(1)

    print("\nPaste these into the repo-root .env:\n")
    print(f"GOOGLE_CLIENT_ID={settings.google_client_id}")
    print(f"GOOGLE_CLIENT_SECRET={settings.google_client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("\nScopes granted:", json.dumps(list(creds.scopes or SCOPES)))


if __name__ == "__main__":
    main()
