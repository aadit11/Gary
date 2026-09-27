import httpx
import pytest

from clients import mock_services


def test_simulates_when_base_url_unset(monkeypatch):
    monkeypatch.setattr(mock_services.settings, "mock_services_base_url", "")
    out = mock_services.pay_bill("City Electric", 84.2)
    assert out["simulated"] and out["confirmation_id"].startswith("SIM-")


def test_posts_to_mock_biller(monkeypatch):
    monkeypatch.setattr(mock_services.settings, "mock_services_base_url", "http://localhost:3000/")
    seen = {}

    def fake_post(url, json, timeout):
        seen["url"], seen["json"] = url, json
        return httpx.Response(200, json={"confirmation_id": "CONF-ABC123", "payee": json["payee"], "amount": json["amount"]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(mock_services.httpx, "post", fake_post)
    out = mock_services.pay_bill("City Electric", 84.2, bill_id="b1")
    assert seen["url"] == "http://localhost:3000/api/mock/biller/pay"
    assert seen["json"] == {"bill_id": "b1", "payee": "City Electric", "amount": 84.2}
    assert out["confirmation_id"] == "CONF-ABC123"


def test_http_error_raises_mock_service_error(monkeypatch):
    monkeypatch.setattr(mock_services.settings, "mock_services_base_url", "http://localhost:3000")

    def fake_post(url, json, timeout):
        return httpx.Response(500, json={"error": "x"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(mock_services.httpx, "post", fake_post)
    with pytest.raises(mock_services.MockServiceError):
        mock_services.pay_bill("City Electric", 84.2)


def test_connection_error_raises_mock_service_error(monkeypatch):
    monkeypatch.setattr(mock_services.settings, "mock_services_base_url", "http://localhost:1")

    def fake_post(url, json, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(mock_services.httpx, "post", fake_post)
    with pytest.raises(mock_services.MockServiceError):
        mock_services.pay_bill("City Electric", 84.2)


def test_send_to_person_is_simulated():
    out = mock_services.send_to_person("Sarah", 15)
    assert out["simulated"] and out["confirmation_id"].startswith("P2P-")
