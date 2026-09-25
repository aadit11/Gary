import json

import pytest

from voice.mcp_adapter import MCPAdapter, to_deepgram_function


@pytest.fixture
async def adapter():
    a = MCPAdapter()  # local in-process sessions over the real FastMCP servers
    await a.start()
    yield a
    await a.stop()


async def test_lists_all_servers_tools(adapter):
    names = adapter.tool_names()
    assert {"list_bills_due", "get_upcoming_appointments", "get_favorite_orders", "get_ride_status"} <= set(names)
    assert len(names) == len(set(names))


async def test_user_id_hidden_from_llm(adapter):
    for fn in adapter.deepgram_functions():
        assert "user_id" not in fn["parameters"]["properties"]
        assert "user_id" not in fn["parameters"]["required"]
        assert fn["description"] and "\n" not in fn["description"]
        assert set(fn) == {"name", "description", "parameters"}


async def test_server_filter(adapter):
    names = [f["name"] for f in adapter.deepgram_functions(["checkins"])]
    assert names == ["get_upcoming_appointments"]


async def test_call_injects_user_id_and_returns_speak_json(adapter, demo):
    out = json.loads(await adapter.call("list_bills_due", {}, demo["user_id"]))
    assert "$84.20" in out["say"]


async def test_unknown_tool_is_friendly(adapter):
    out = json.loads(await adapter.call("launch_rocket", {}, "u"))
    assert "say" in out and "not able" in out["say"]


def test_schema_conversion_strips_titles():
    class T:
        name = "x"
        description = "Do x.\nMore detail."
        inputSchema = {"type": "object", "title": "xArguments", "properties": {"user_id": {"title": "U", "type": "string"}, "q": {"title": "Q", "type": "string"}}, "required": ["user_id", "q"]}
    fn = to_deepgram_function(T())
    assert fn == {"name": "x", "description": "Do x.", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}
