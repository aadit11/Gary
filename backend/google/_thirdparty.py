"""Load the real Google API client libs without conflicting with this local `google` package.

`backend/google/` shadows the installed `google` / `google.oauth2` namespace. Callers that need
Credentials or discovery.build must go through this helper so site-packages wins once, then the
local package remains importable as `google.ingestion`, etc.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent.parent
_CACHE: dict[str, Any] | None = None


def _is_google_ns(name: str) -> bool:
    return name == "google" or (
        name.startswith("google.")
        and not name.startswith("googleapiclient")
        and not name.startswith("google_auth_oauthlib")
    )


def load() -> dict[str, Any]:
    """Return Credentials, Request, build, InstalledAppFlow from the installed Google packages."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    backend = str(_BACKEND)
    removed: list[str] = []
    for entry in (backend, ""):
        while entry in sys.path:
            sys.path.remove(entry)
            removed.append(entry)

    for key in list(sys.modules):
        if _is_google_ns(key):
            del sys.modules[key]

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        _CACHE = {
            "Credentials": Credentials,
            "Request": Request,
            "build": build,
            "InstalledAppFlow": InstalledAppFlow,
        }
        return _CACHE
    finally:
        # Drop site-packages google.* so `import google` resolves to this local package again.
        for key in list(sys.modules):
            if _is_google_ns(key):
                del sys.modules[key]
        for entry in reversed(removed):
            if entry not in sys.path:
                sys.path.insert(0, entry)
