"""Independent outcome checks shared by both agents (never trust the agent's own DONE claim)."""

from __future__ import annotations

import re

_ORDER_ID = re.compile(r"\bORD-\d{6,}", re.I)


def dashdish_order_confirmed(page_text: str) -> str | None:
    """Return the order id shown on the page after Place Order, or None."""
    m = _ORDER_ID.search(page_text or "")
    return m.group(0) if m else None
