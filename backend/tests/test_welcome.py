import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from config import settings
from core import notify
from webhooks import welcome

REAL = "+14085550100"  # area code 408; the demo fixture's 555 numbers are refused by can_message


@pytest.fixture(autouse=True)
def no_cooldown():
    welcome._last_sent.clear()
    yield
    welcome._last_sent.clear()


def _real_number(fake_db, demo):
    fake_db.table("family_contacts").update({"phone": REAL}).eq("id", demo["family_id"]).execute()


def _creds(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "ACxxx")
    monkeypatch.setattr(settings, "twilio_auth_token", "tok")
    monkeypatch.setattr(settings, "twilio_phone_number", "+14085550123")


def test_unknown_user_is_404(demo):
    with pytest.raises(HTTPException) as err:
        welcome.send_welcome("not-a-user")
    assert err.value.status_code == 404


def test_no_approver(demo, fake_db):
    fake_db.table("family_contacts").update({"can_approve": False}).eq("id", demo["family_id"]).execute()
    assert welcome.send_welcome(demo["user_id"])["reason"] == "no_approver"


def test_fictional_number_is_reported_before_twilio_setup(demo, monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "")
    out = welcome.send_welcome(demo["user_id"])
    assert out["sent"] is False and out["reason"] == "invalid_number" and out["to"] == "0002" and out["name"] == "David"


def test_not_configured(demo, fake_db, monkeypatch):
    _real_number(fake_db, demo)
    monkeypatch.setattr(settings, "twilio_account_sid", "")
    out = welcome.send_welcome(demo["user_id"])
    assert out["reason"] == "not_configured" and out["to"] == "0100"


def test_sends_hello_and_logs(demo, fake_db, monkeypatch):
    _real_number(fake_db, demo)
    _creds(monkeypatch)
    sent = []
    monkeypatch.setattr(notify, "send_sms", lambda to, body: (sent.append((to, body)), "SM1")[1])
    out = welcome.send_welcome(demo["user_id"])
    assert out["sent"] is True and out["reason"] == "sent"
    to, body = sent[0]
    assert to == REAL
    assert "YES" in body and "NO" in body and "Margaret" in body and body.startswith("Hi David")
    kinds = [r["kind"] for r in fake_db.table("activity_log").select("*").eq("user_id", demo["user_id"]).execute().data]
    assert "family_welcomed" in kinds


def test_second_send_within_cooldown_is_skipped(demo, fake_db, monkeypatch):
    _real_number(fake_db, demo)
    _creds(monkeypatch)
    sent = []
    monkeypatch.setattr(notify, "send_sms", lambda to, body: (sent.append(to), "SM1")[1])
    assert welcome.send_welcome(demo["user_id"])["reason"] == "sent"
    assert welcome.send_welcome(demo["user_id"])["reason"] == "cooldown"
    assert len(sent) == 1


def test_send_failure_is_reported(demo, fake_db, monkeypatch):
    _real_number(fake_db, demo)
    _creds(monkeypatch)
    monkeypatch.setattr(notify, "send_sms", lambda to, body: "")
    assert welcome.send_welcome(demo["user_id"])["reason"] == "send_failed"


def test_route_wiring(demo, fake_db, monkeypatch):
    _real_number(fake_db, demo)
    monkeypatch.setattr(settings, "twilio_account_sid", "")
    app = FastAPI()
    app.include_router(welcome.router)
    client = TestClient(app)
    res = client.post("/notify/welcome", json={"user_id": demo["user_id"]})
    assert res.status_code == 200 and res.json()["reason"] == "not_configured"
    assert client.post("/notify/welcome", json={"user_id": "nope"}).status_code == 404
    assert client.post("/notify/welcome", json={}).status_code == 422


def test_welcome_text_is_short_and_plain():
    text = welcome.welcome_text("Margaret Chen", "David Chen")
    assert len(text) < 220
    assert text.startswith("Hi David, this is Gary, Margaret's phone helper.")
    assert welcome.welcome_text("", "").startswith("Hi there, this is Gary, your family member's phone helper.")
