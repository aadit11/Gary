"""MCP client adapter: persistent sessions to our MCP servers, MCP -> Deepgram function
schemas, and routing of Deepgram function calls to the right server.

Deepgram does not speak MCP. At call start the bridge asks this adapter for Deepgram function
definitions; when Deepgram sends FunctionCallRequest the bridge calls `adapter.call(...)`.

`user_id` is stripped from every schema the LLM sees and injected on every call, so the model
never has to know or guess it.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from contextlib import AsyncExitStack
from typing import Any, Protocol

from config import settings
from core.speech import speak
from mcp_servers import SERVERS, streamable_http_url

log = logging.getLogger(__name__)

TOOL_TIMEOUT_S = 5.0
HIDDEN_PARAMS = {"user_id"}


class _Session(Protocol):
    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


def to_deepgram_function(tool: Any) -> dict:
    """Convert an MCP Tool (name, description, inputSchema) to a Deepgram function definition."""
    schema = copy.deepcopy(getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}})
    props = schema.get("properties", {})
    for p in HIDDEN_PARAMS:
        props.pop(p, None)
    schema["properties"] = props
    schema["required"] = [r for r in schema.get("required", []) if r not in HIDDEN_PARAMS]
    schema.pop("$defs", None)
    schema.pop("title", None)
    for v in props.values():
        if isinstance(v, dict):
            v.pop("title", None)
    return {
        "name": tool.name,
        "description": (tool.description or "").strip().split("\n")[0],
        "parameters": {"type": "object", "properties": schema["properties"], "required": schema["required"]},
        # Wait until the person has finished. A call sent early can be cancelled and leave the line silent.
        "defer_until_eot": True,
    }


def _text_of(result: Any) -> str:
    """First text block of a CallToolResult, or ''."""
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


class LocalSession:
    """In-process MCP session over a FastMCP server object (same list_tools/call_tool surface as
    mcp.ClientSession). Default transport: no loopback HTTP, no startup ordering problems, and the
    tool schemas are the exact ones the HTTP mount serves to the Inspector."""

    def __init__(self, server: Any):
        self._server = server

    async def list_tools(self) -> Any:
        from mcp import types

        return types.ListToolsResult(tools=await self._server.list_tools())

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        from mcp import types

        try:
            result = await self._server.call_tool(name, arguments)
        except Exception as e:  # noqa: BLE001
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(e))], isError=True)
        content = result[0] if isinstance(result, tuple) else result
        return types.CallToolResult(content=list(content), isError=False)


class MCPAdapter:
    def __init__(
        self,
        sessions: dict[str, _Session] | None = None,
        transport: str = "local",
        base_url: str | None = None,
    ):
        self._stack = AsyncExitStack()
        self._sessions: dict[str, _Session] = sessions or {}
        self._transport = transport
        self._base_url = base_url or f"http://127.0.0.1:{settings.port}"
        self._tools: dict[str, tuple[str, Any]] = {}  # tool name -> (server name, Tool)
        self.ready = asyncio.Event()

    # --- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        """Open one session per registered server, then cache the tool list."""
        if not self._sessions:
            if self._transport == "http":
                from mcp import ClientSession
                from mcp.client.streamable_http import streamablehttp_client

                for name in SERVERS:
                    url = streamable_http_url(self._base_url, name)
                    read, write, _ = await self._stack.enter_async_context(streamablehttp_client(url))
                    session = await self._stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    self._sessions[name] = session
            else:
                self._sessions = {name: LocalSession(server) for name, server in SERVERS.items()}
        await self.refresh_tools()
        self.ready.set()
        log.info("MCP adapter ready (%s): %s", self._transport, ", ".join(sorted(self._tools)))

    async def stop(self) -> None:
        await self._stack.aclose()
        self._sessions.clear()
        self._tools.clear()
        self.ready.clear()

    async def refresh_tools(self) -> None:
        tools: dict[str, tuple[str, Any]] = {}
        for server_name, session in self._sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                if tool.name in tools:
                    log.warning("duplicate tool name %s in %s and %s", tool.name, tools[tool.name][0], server_name)
                tools[tool.name] = (server_name, tool)
        self._tools = tools

    # --- schema conversion ------------------------------------------------
    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def deepgram_functions(self, server_names: list[str] | None = None) -> list[dict]:
        allowed = set(server_names) if server_names else None
        return [
            to_deepgram_function(tool)
            for name, (server_name, tool) in sorted(self._tools.items())
            if allowed is None or server_name in allowed
        ]

    # --- routing ---------------------------------------------------------
    async def call(self, name: str, arguments: dict[str, Any] | None, user_id: str) -> str:
        """Run a tool and return its speak() JSON string. Never raises."""
        entry = self._tools.get(name)
        if entry is None:
            log.warning("unknown tool requested: %s", name)
            return speak("I'm not able to do that one. What else can I help with?")
        server_name, _ = entry
        args = dict(arguments or {})
        args["user_id"] = user_id
        try:
            result = await asyncio.wait_for(self._sessions[server_name].call_tool(name, args), TOOL_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.error("tool %s timed out", name)
            return speak("That's taking longer than usual. Want me to try again?")
        except Exception:  # noqa: BLE001
            log.exception("tool %s failed", name)
            return speak("I couldn't do that just now. Want me to try again?")
        if getattr(result, "isError", False):
            log.error("tool %s returned error: %s", name, _text_of(result)[:200])
            return speak("I couldn't do that just now. Want me to try again?")
        text = _text_of(result)
        return text or speak("Done.")
