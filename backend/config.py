"""Environment loading via pydantic-settings.

The .env file lives at the repo root (one level above backend/). A backend/.env is also honored.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent
_ENV_FILES = (_BACKEND_DIR.parent / ".env", _BACKEND_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Deepgram
    deepgram_api_key: str = ""

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""

    # Google (demo account)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # Optional
    meta_api_key: str = ""

    # App
    public_base_url: str = ""
    mock_services_base_url: str = ""
    demo_user_id: str = ""
    policy_spending_limit: float = 100.0

    # Set GARY_FAKE_DB=1 to force the in-memory database (tests, teammates without creds).
    gary_fake_db: bool = False

    # How long a prepared action stays valid before confirm_* rejects it.
    pending_ttl_seconds: int = 300


settings = Settings()
