"""FastAPI app: mounts the four MCP servers, the SMS webhook, and (later) voice routes and scheduler.

FastMCP's streamable HTTP session managers must run inside FastAPI's lifespan; mounting alone
is not enough and requests will hang. `streamable_http_app()` is called at import so the
session manager exists before the lifespan starts it.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from config import settings
from mcp_servers import SERVERS, mount_path
from webhooks.sms import router as sms_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gary")

_mcp_apps = {name: server.streamable_http_app() for name, server in SERVERS.items()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        for name, server in SERVERS.items():
            await stack.enter_async_context(server.session_manager.run())
            log.info("MCP server '%s' ready at %s/mcp", name, mount_path(name))
        # Person 1: start the voice MCP adapter and scheduler here.
        yield


app = FastAPI(title="Gary backend", lifespan=lifespan)
app.include_router(sms_router)

for _name, _mcp_app in _mcp_apps.items():
    app.mount(mount_path(_name), _mcp_app)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "mcp_servers": {name: f"{mount_path(name)}/mcp" for name in SERVERS},
        "db": "supabase" if settings.supabase_url and not settings.gary_fake_db else "fake",
        "sms": bool(settings.twilio_account_sid),
    }
