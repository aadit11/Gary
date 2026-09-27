"""OAuth credentials for the demo Gmail/Calendar account (Testing-mode OAuth client)."""

from __future__ import annotations

from config import settings

from ._thirdparty import load as load_google_api

# Read + write calendar events (seed doctor visit; later service bookings).
# gmail.modify is enough to insert seed messages into INBOX without mailing them out.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]


class GoogleAuthError(RuntimeError):
    """Raised when Google credentials are missing or unusable."""


def credentials_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret and settings.google_refresh_token)


def get_credentials(*, refresh: bool = True):
    """Build user credentials from GOOGLE_* env vars. Refreshes the access token when needed."""
    if not credentials_configured():
        raise GoogleAuthError(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
            "and GOOGLE_REFRESH_TOKEN (run: uv run python scripts/google_oauth.py)."
        )
    api = load_google_api()
    Credentials = api["Credentials"]
    Request = api["Request"]
    creds = Credentials(
        token=None,
        refresh_token=settings.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )
    if refresh and not creds.valid:
        if not creds.refresh_token:
            raise GoogleAuthError("GOOGLE_REFRESH_TOKEN is empty.")
        creds.refresh(Request())
    return creds


def gmail_service():
    """Gmail API service for the demo account."""
    api = load_google_api()
    return api["build"]("gmail", "v1", credentials=get_credentials(), cache_discovery=False)


def calendar_service():
    """Calendar API service for the demo account."""
    api = load_google_api()
    return api["build"]("calendar", "v3", credentials=get_credentials(), cache_discovery=False)
