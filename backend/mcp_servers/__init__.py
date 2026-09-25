"""SERVERS registry used by main.py (mounting) and voice/mcp_adapter.py (tool listing).

Each server is mounted at /mcp/<name> and serves streamable HTTP at /mcp/<name>/mcp.
"""

from mcp_servers.checkins import checkins
from mcp_servers.mobility import mobility
from mcp_servers.money import money
from mcp_servers.orders import orders

SERVERS = {
    "checkins": checkins,
    "money": money,
    "orders": orders,
    "mobility": mobility,
}


def mount_path(name: str) -> str:
    return f"/mcp/{name}"


def streamable_http_url(base_url: str, name: str) -> str:
    """Full client URL for a server, e.g. http://localhost:8000/mcp/money/mcp."""
    return f"{base_url.rstrip('/')}{mount_path(name)}/mcp"
