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
from browser_agent.runner import BrowserJobRunner
from core import approvals
from scheduler.jobs import start_scheduler
from voice import injection
from voice.mcp_adapter import MCPAdapter
from voice.twilio_routes import router as voice_router
from webhooks.sms import router as sms_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gary")
logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs carry user ids

_mcp_apps = {name: server.streamable_http_app() for name, server in SERVERS.items()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        for name, server in SERVERS.items():
            await stack.enter_async_context(server.session_manager.run())
            log.info("MCP server '%s' ready at %s/mcp", name, mount_path(name))
        adapter = MCPAdapter()
        await adapter.start()
        app.state.adapter = adapter
        approvals.register(injection.on_approval_resolved)
        scheduler = start_scheduler() if settings.public_base_url else None
        browser_runner = BrowserJobRunner()
        browser_runner.start()  # worker thread only; no browser opens until a job is submitted
        app.state.browser_runner = browser_runner
        try:
            yield
        finally:
            browser_runner.stop()
            if scheduler:
                scheduler.shutdown(wait=False)
            await adapter.stop()


app = FastAPI(title="Gary backend", lifespan=lifespan)
app.include_router(sms_router)
app.include_router(voice_router)

for _name, _mcp_app in _mcp_apps.items():
    app.mount(mount_path(_name), _mcp_app)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "mcp_servers": {name: f"{mount_path(name)}/mcp" for name in SERVERS},
        "db": "supabase" if settings.supabase_url and not settings.gary_fake_db else "fake",
        "sms": bool(settings.twilio_account_sid),
        "browser_agent": {"model": settings.muse_model, "headless": settings.browser_headless, "configured": bool(settings.openrouter_api_key)},
    }
