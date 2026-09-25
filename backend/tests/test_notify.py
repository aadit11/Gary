from config import settings
from core import notify


def test_normalize_phone():
    assert notify.normalize_phone("(408) 981-4724") == "+14089814724"
    assert notify.normalize_phone("whatsapp:+14089814724") == "+14089814724"
    assert notify.normalize_phone("") == ""


def test_addresses_sms(monkeypatch):
    monkeypatch.setattr(settings, "family_channel", "sms")
    monkeypatch.setattr(settings, "twilio_phone_number", "+15550000000")
    assert notify.addresses("4089814724") == ("+14089814724", "+15550000000")


def test_addresses_whatsapp(monkeypatch):
    monkeypatch.setattr(settings, "family_channel", "whatsapp")
    to, frm = notify.addresses("4089814724")
    assert to == "whatsapp:+14089814724" and frm.startswith("whatsapp:")


def test_send_without_creds_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "")
    assert notify.send_sms("4089814724", "hi") == ""
