from config import settings
from core import notify


def test_normalize_phone():
    assert notify.normalize_phone("(408) 555-0123") == "+14085550123"
    assert notify.normalize_phone("whatsapp:+14085550123") == "+14085550123"
    assert notify.normalize_phone("") == ""


def test_addresses_sms(monkeypatch):
    monkeypatch.setattr(settings, "family_channel", "sms")
    monkeypatch.setattr(settings, "twilio_phone_number", "+15550000000")
    assert notify.addresses("4085550123") == ("+14085550123", "+15550000000")


def test_addresses_whatsapp(monkeypatch):
    monkeypatch.setattr(settings, "family_channel", "whatsapp")
    to, frm = notify.addresses("4085550123")
    assert to == "whatsapp:+14085550123" and frm.startswith("whatsapp:")


def test_send_without_creds_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "")
    assert notify.send_sms("4085550123", "hi") == ""


def test_invalid_number_does_not_call_twilio(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "ACxxx")
    monkeypatch.setattr(settings, "twilio_auth_token", "tok")
    monkeypatch.setattr(settings, "twilio_phone_number", "+14085550123")
    monkeypatch.setattr(notify, "_twilio", lambda: (_ for _ in ()).throw(AssertionError("Twilio was called")))
    assert notify.send_sms("+15005550001", "hi") == ""
