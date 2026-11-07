"""Local MCP tools for the pedal, over stdio. Write tools fail unless HEADRUSH_ALLOW_WRITES=1."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .client import (
    BLOCKS,
    CHAIN,
    FOOTSWITCH,
    RIG,
    RIGS,
    SETLISTS,
    HeadRushClient,
    HeadRushError,
    block_path,
)
from .rigs import ROUTINGS, apply_rig, footswitch_values

mcp = MCPServer("headrush")
client = HeadRushClient(
    host=os.environ.get("HEADRUSH_HOST", "headrushflexprime.local"),
    allow_writes=os.environ.get("HEADRUSH_ALLOW_WRITES") == "1",
)
_MIX = block_path("Mix")
_LABEL_UPDATE_SECONDS = 1.0  # The pedal updates footswitch labels shortly after a write.


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Get firmware, loaded rig, unsaved-edit flag and DSP load."""
    return client.status()


@mcp.tool()
def list_rigs() -> list[dict[str, str]]:
    """List every rig on the pedal with its id."""
    rigs = client.get_properties(RIGS)
    return [{"id": i, "name": n} for i, n in zip(rigs["AllRigIds"], rigs["AllRigNames"])]


@mcp.tool()
def list_setlists() -> list[dict[str, Any]]:
    """List setlists with their ids and rig counts."""
    s = client.get_properties(SETLISTS)
    return [
        {"id": i, "name": n, "rigs": c}
        for i, n, c in zip(s["SetlistIds"], s["SetlistNames"], s["SetlistCounts"])
    ]


@mcp.tool()
def get_setlist(setlist_id: str) -> Any:
    """Read one setlist."""
    result = client.call(SETLISTS, "getSetlist", [setlist_id])
    return json.loads(result) if isinstance(result, str) else result


@mcp.tool()
def get_current_rig() -> dict[str, Any]:
    """Get the loaded rig's name, routing, parallel mix and block chain."""
    routing = client.get_properties(CHAIN)["Routing"]
    rig = {
        "name": client.get_properties(RIG).get("PresetName"),
        "routing": ROUTINGS[routing] if routing < len(ROUTINGS) else routing,
        "chain": client.current_chain(),
    }
    if routing:
        rig["mix"] = {k: v for k, v in client.get_properties(_MIX).items() if k.startswith("Para")}
    return rig


@mcp.tool()
def list_routings() -> list[dict[str, Any]]:
    """List signal routings and which chain slots belong to each section."""
    return ROUTINGS


@mcp.tool()
def get_block(block: str) -> dict[str, Any]:
    """Read a block's current values. Numbers are normalized 0-1."""
    return client.get_properties(block_path(block))


@mcp.tool()
def describe_block(block: str) -> dict[str, Any]:
    """Read a block's parameter schema: types, display ranges and options."""
    return client.get_meta(block_path(block)).get("properties") or {}


@mcp.tool()
def list_blocks() -> list[str]:
    """List block names usable in a chain slot. Names ending in ' 2' are second instances."""
    return client.get_properties(BLOCKS)["ModuleTypes"]


@mcp.tool()
def list_block_presets(block: str) -> list[str]:
    """List a block's factory and user presets."""
    return client.call(BLOCKS, "blockPresets", [block])


@mcp.tool()
def get_footswitches() -> list[dict[str, Any]]:
    """Summarise footswitches. Switches 1-3 and 4-6 are separate banks."""
    fs = client.get_properties(FOOTSWITCH)
    return [
        {
            "switch": n,
            "type": {0: "toggle", 1: "hold", 2: "scene"}.get(fs.get(f"ModeNew{n}")),
            "module": fs.get(f"Module{n}"),
            "operation": fs.get(f"Operation{n}"),
            "label": fs.get(f"FootSwitchText{n}"),
            "on": fs.get(f"FootSwitchOn{n}"),
            "scene_active": fs.get(f"SceneActive{n}"),
        }
        for n in range(1, 7)
    ]


@mcp.tool()
def set_block_params(block: str, values: dict[str, Any]) -> dict[str, Any]:
    """Change parameters on the loaded rig without saving. Numbers are normalized 0-1."""
    client.set_properties(block_path(block), values)
    current = client.get_properties(block_path(block))
    return {key: current.get(key) for key in values}


@mcp.tool()
def set_slot_block(slot: int, block: str) -> list[dict[str, Any]]:
    """Put a block in chain slot 1-14 without saving. Its parameters reset shortly afterwards."""
    types = client.get_properties(BLOCKS)["ModuleTypes"]
    if block not in types:
        raise HeadRushError(f"Unknown block: {block}")
    client.set_properties(CHAIN, {f"ModuleType{slot}": types.index(block)})
    return client.current_chain()


@mcp.tool()
def set_routing(routing: int) -> dict[str, Any]:
    """Change signal routing without saving. See list_routings for the slot layout."""
    client.set_properties(CHAIN, {"Routing": routing})
    return get_current_rig()


@mcp.tool()
def set_mix(values: dict[str, float]) -> dict[str, Any]:
    """Set parallel path mixing without saving.

    Keys: Para1Level, Para2Level, Para1Pan, Para2Pan, ParaDelay, ParaXFade. Values are
    normalized 0-1: for pans 0 is left, 0.5 centre and 1 right; for level 0.75 is -6 dB.
    """
    client.set_properties(_MIX, values)
    current = client.get_properties(_MIX)
    return {key: current.get(key) for key in values}


def _write_switch(switch: int, config: dict[str, Any]) -> list[dict[str, Any]]:
    spec = {"blocks": client.current_chain(), "footswitches": {str(switch): config}}
    for key, value in footswitch_values(spec)[0].items():
        client.set_properties(FOOTSWITCH, {key: value})
    time.sleep(_LABEL_UPDATE_SECONDS)
    return get_footswitches()


@mcp.tool()
def set_footswitch(switch: int, module: str, operation: str = "On", name: str = "") -> list[dict[str, Any]]:
    """Make footswitch 1-6 toggle one block, without saving."""
    return _write_switch(switch, {"module": module, "operation": operation, "name": name})


@mcp.tool()
def set_scene(switch: int, name: str, blocks: dict[str, str]) -> list[dict[str, Any]]:
    """Make footswitch 1-6 a scene, without saving.

    `blocks` maps block names in the chain to "on" or "off". Others stay unchanged.
    """
    return _write_switch(switch, {"scene": {"name": name, "blocks": blocks}})


@mcp.tool()
def activate_scene(switch: int) -> list[dict[str, Any]]:
    """Fire the scene on footswitch 1-6 of the loaded rig, without saving."""
    if client.get_properties(FOOTSWITCH).get(f"ModeNew{switch}") != 2:
        raise HeadRushError(f"Footswitch {switch} isn't a scene")
    client.set_properties(FOOTSWITCH, {f"SceneActive{switch}": True})
    return get_footswitches()


@mcp.tool()
def load_rig(rig_id: str, sr_id: str = "") -> dict[str, Any]:
    """Load a rig by id. Refused if the current rig has unsaved edits."""
    client.require_clean()
    client.call(RIGS, "loadRigConfirm", [rig_id, sr_id])
    return client.status()


@mcp.tool()
def save_rig_as_new(name: str) -> dict[str, Any]:
    """Save the loaded rig under a new name. Refused if the name already exists."""
    client.require_new_name(name)
    client.call(RIGS, "saveRigAs", [name, -1])
    return client.status()


@mcp.tool()
def save_loaded_rig(expected_name: str) -> dict[str, Any]:
    """Overwrite the loaded rig's saved copy. Refused unless the exact loaded name is given."""
    client.save_loaded_rig(expected_name)
    return client.status()


@mcp.tool()
def create_rig(
    spec: dict[str, Any] | None = None,
    spec_path: str | None = None,
    save: bool = True,
    resume_draft: bool = False,
) -> dict[str, Any]:
    """Build a new rig from a spec, verify it, and save it only if everything matches.

    Pass `spec` or a local JSON `spec_path`; docs/rig-specs.md has the format. Refused if
    the name exists or the loaded rig has unsaved edits. If a build fails, retry with
    `resume_draft` to reuse the unnamed draft it left, which overwrites that draft.
    """
    if (spec is None) == (spec_path is None):
        raise HeadRushError("Pass exactly one of spec or spec_path")
    if spec is None:
        try:
            spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HeadRushError(f"Couldn't read spec file {spec_path}: {exc}") from exc
    return apply_rig(client, spec, save=save, resume_draft=resume_draft)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
