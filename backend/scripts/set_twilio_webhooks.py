"""Point the Twilio number's voice and SMS webhooks at PUBLIC_BASE_URL.

Run from backend/ after every ngrok restart:  uv run python scripts/set_twilio_webhooks.py
The WhatsApp sandbox inbound URL has no API; update it in the Twilio console.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def main() -> None:
    if not settings.public_base_url:
        raise SystemExit("PUBLIC_BASE_URL is not set in .env")
    from twilio.rest import Client

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    numbers = client.incoming_phone_numbers.list(phone_number=settings.twilio_phone_number)
    if not numbers:
        raise SystemExit(f"Number {settings.twilio_phone_number} not found on this Twilio account")
    base = settings.public_base_url.rstrip("/")
    numbers[0].update(
        voice_url=f"{base}/voice/incoming", voice_method="POST",
        sms_url=f"{base}/webhooks/sms", sms_method="POST",
    )
    n = client.incoming_phone_numbers(numbers[0].sid).fetch()
    print("voice:", n.voice_url)
    print("sms:  ", n.sms_url)
    print("Now set the WhatsApp sandbox 'When a message comes in' URL to", n.sms_url)


if __name__ == "__main__":
    main()
