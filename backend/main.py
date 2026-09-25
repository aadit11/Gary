"""FastAPI app: mounts MCP servers, routers, and the lifespan (MCP session managers, scheduler, adapter)."""

from fastapi import FastAPI

app = FastAPI(title="Gary backend")
