"""HTTP client for web/ mock APIs (owners add their own functions).

Only mock services are ever called (safety invariant 4). When MOCK_SERVICES_BASE_URL is unset,
payments are simulated locally so the voice flow still works without the web app running.
"""

from __future__ import annotations

import logging
import uuid

import httpx

from config import settings

log = logging.getLogger(__name__)

TIMEOUT_S = 5.0


class MockServiceError(RuntimeError):
    """The mock service could not complete the request."""


def _base() -> str:
    return settings.mock_services_base_url.strip().rstrip("/")


def _local_confirmation(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def pay_bill(payee: str, amount: float, bill_id: str | None = None) -> dict:
    """POST /api/mock/biller/pay. Returns {confirmation_id, payee, amount, paid_at?, simulated?}."""
    base = _base()
    if not base:
        log.warning("MOCK_SERVICES_BASE_URL not set; simulating bill payment to %s", payee)
        return {"confirmation_id": _local_confirmation("SIM"), "payee": payee, "amount": amount, "simulated": True}
    try:
        res = httpx.post(
            f"{base}/api/mock/biller/pay",
            json={"bill_id": bill_id, "payee": payee, "amount": amount},
            timeout=TIMEOUT_S,
        )
        res.raise_for_status()
        data = res.json()
    except (httpx.HTTPError, ValueError) as err:
        raise MockServiceError(f"biller pay failed: {err}") from err
    if not data.get("confirmation_id"):
        raise MockServiceError("biller returned no confirmation_id")
    return data


def send_to_person(recipient: str, amount: float) -> dict:
    """No mock payment-to-person API exists; record a simulated transfer."""
    return {"confirmation_id": _local_confirmation("P2P"), "recipient": recipient, "amount": amount, "simulated": True}
