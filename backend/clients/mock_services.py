"""HTTP client for web/ mock APIs (owners add their own functions).

    GET  /api/mock/services/search?q=...      -> {"category": ..., "providers": [...]}
    POST /api/mock/services/bookings          -> {booking_id, provider, category, time, price, problem}

Food and groceries have no HTTP endpoint: DashDish is a real REAL clone with no API of its
own, ordered by the browser agent (see mcp_servers/orders.py). The static catalog below
exists only so search_food_and_groceries can return a fast, deterministic read-back before
the browser agent is told the item name in plain English at confirm time.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from config import settings

log = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:3000"


def _base_url() -> str:
    url = (settings.mock_services_base_url or "").strip().rstrip("/")
    if url.startswith(("http://", "https://")):
        return url
    if url:
        log.warning("MOCK_SERVICES_BASE_URL %r has no http(s) scheme; using %s", url, _DEFAULT_BASE_URL)
    return _DEFAULT_BASE_URL


def search_services(query: str) -> dict[str, Any]:
    """Find home service providers by category or plain-language problem description."""
    resp = httpx.get(f"{_base_url()}/api/mock/services/search", params={"q": query}, timeout=3.0)
    resp.raise_for_status()
    return resp.json()


def create_service_booking(provider_id: str, time: str, problem: str = "") -> dict[str, Any]:
    """Book a home service provider for a given ISO time slot."""
    resp = httpx.post(
        f"{_base_url()}/api/mock/services/bookings",
        json={"provider_id": provider_id, "time": time, "problem": problem},
        timeout=3.0,
    )
    resp.raise_for_status()
    return resp.json()


# --- food & grocery catalog (local, static; see module docstring) -----------

_FOOD_CATALOG: list[dict[str, Any]] | None = None


def _load_food_catalog() -> list[dict[str, Any]]:
    global _FOOD_CATALOG
    if _FOOD_CATALOG is None:
        path = Path(__file__).resolve().parent.parent / "data" / "food_catalog.json"
        with open(path) as f:
            _FOOD_CATALOG = json.load(f)
    return _FOOD_CATALOG


def search_food_catalog(query: str) -> list[dict[str, Any]]:
    """Fast local keyword lookup across item name, vendor, and tags."""
    query_lower = (query or "").strip().lower()
    catalog = _load_food_catalog()
    if not query_lower:
        return catalog[:3]
    matches = [
        item
        for item in catalog
        if query_lower in item["name"].lower()
        or query_lower in item["vendor"].lower()
        or any(query_lower in tag for tag in item.get("tags", []))
    ]
    return matches or catalog[:3]


def get_food_item(item_id: str) -> dict[str, Any] | None:
    """Authoritative lookup by id, so a tool never has to trust a name/price the LLM supplies."""
    return next((item for item in _load_food_catalog() if item["id"] == item_id), None)
