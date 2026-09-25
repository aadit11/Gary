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

    # Family messaging channel: "sms" (needs A2P 10DLC registration on the Twilio number) or
    # "whatsapp" (Twilio WhatsApp sandbox; family phone must first send the join message).
    family_channel: str = "sms"
    twilio_whatsapp_from: str = "whatsapp:+14155238886"  # Twilio's shared sandbox number

    # Voice agent (Deepgram Voice Agent API)
    deepgram_agent_url: str = "wss://agent.deepgram.com/v1/agent/converse"
    deepgram_think_model: str = "gpt-4o-mini"     # Deepgram-managed OpenAI model
    deepgram_voice: str = "flux-alexis-en"        # Deepgram speak model (v2)
    port: int = 8000                              # local port; the MCP adapter connects over loopback

    # Browser agent (Muse Spark on Meta Model API driving REAL clones)
    meta_api_base: str = "https://api.meta.ai/v1"
    muse_model: str = "muse-spark-1.3"
    muse_reasoning_effort: str = "low"           # minimal | low | medium | high (Muse Spark is a reasoning model)
    muse_max_tokens: int = 3000
    browser_headless: bool = True
    browser_max_steps: int = 25
    browser_timeout_s: int = 180
    browser_use_screenshot: bool = True
    browser_video_dir: str = ""
    browser_replay_verify: bool = False
    # jev-ultrafast experiment (branch jev-ultrafast): TypeSafe Jev chooses actions, Muse Spark writes text
    typesafe_api_key: str = ""
    typesafe_model: str = "jev-latest"
    jev_cdp_ws: str = ""                  # websocket of a Chromium started with --remote-debugging-port
    jev_max_steps: int = 30   # True = ask the model to confirm after a full replay (adds ~5-8 s)
    real_dashdish_url: str = "https://evals-dashdish.vercel.app"
    real_udriver_url: str = "https://evals-udriver.vercel.app"

    # Set GARY_FAKE_DB=1 to force the in-memory database (tests, teammates without creds).
    gary_fake_db: bool = False

    # How long a prepared action stays valid before confirm_* rejects it.
    pending_ttl_seconds: int = 300


settings = Settings()
