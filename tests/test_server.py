import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from headrush_mcp import server
from headrush_mcp.rigs import ROUTINGS


def tool_names() -> set[str]:
    return {tool.name for tool in asyncio.run(server.mcp.list_tools())}


def test_server_loads_with_writes_off_and_exposes_no_destructive_tools():
    assert server.client.allow_writes is False
    names = tool_names()
    assert {"get_status", "list_rigs", "create_rig", "set_scene", "set_mix", "save_loaded_rig"} <= names
    assert not {name for name in names if "delete" in name or "cloud" in name or "upload" in name}


def test_every_tool_is_annotated_for_what_it_does():
    tools = {tool.name: tool.annotations for tool in asyncio.run(server.mcp.list_tools())}
    assert all(hints is not None and hints.open_world_hint is False for hints in tools.values())
    writes = {name for name in tools if name.startswith(("set_", "save_", "load_", "create_", "activate_", "remove_"))}
    assert {name for name, hints in tools.items() if hints.read_only_hint} == set(tools) - writes
    assert {name for name in writes if tools[name].destructive_hint is False} == {
        "load_rig",
        "create_rig",
        "save_rig_as_new",
    }
    assert tools["save_loaded_rig"].destructive_hint is True


def test_refusal_reasons_reach_the_client():
    with pytest.raises(ToolError, match="Writes are disabled"):
        asyncio.run(server.mcp.call_tool("set_mix", {"values": {"ParaXFade": 0.5}}))


def test_routing_table_covers_all_fourteen_slots():
    for routing in ROUTINGS:
        slots = []
        for section in ("before_split", "path_a", "path_b", "after_mix"):
            if routing[section]:
                first, last = map(int, routing[section].split("-"))
                slots += range(first, last + 1)
        assert sorted(slots) == list(range(1, 15)), routing
