"""Local MCP tools for the pedal, over stdio. Write tools fail unless HEADRUSH_ALLOW_WRITES=1."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .catalog import find_models as _find_models
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
from .rigs import (
    ROUTINGS,
    apply_rig,
    check_scene,
    check_scene_presets,
    find_mismatches,
    footswitch_values,
    read_scene,
    scene_warnings,
)

mcp = MCPServer("headrush")
client = HeadRushClient(
    host=os.environ.get("HEADRUSH_HOST", "headrushflexprime.local"),
    allow_writes=os.environ.get("HEADRUSH_ALLOW_WRITES") == "1",
)
_MIX = block_path("Mix")
_GENERAL_SETTINGS = "/Evil/Engine/Settings/General"
_LABEL_UPDATE_SECONDS = 1.0  # The pedal updates footswitch labels shortly after a write.
_RIG_SPEC_FORMAT = Path(__file__).with_name("rig-specs.md")
_SWITCH_TYPES = {0: "toggle", 1: "hold", 2: "scene"}
_SCENE_SIDES = {0: "nochange", 1: "A", 2: "B"}


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
def find_models(
    query: str = "", kind: str = "", category: str = "", limit: int = 50
) -> dict[str, Any]:
    """Find blocks, models and files by name or by the gear they're inspired by.

    `query` matches words, like "klon", "twin" or "ac30". `kind` is one of block, amp, cab,
    mic, clone, superclone, nam, ir or reverb; ir and reverb are only searched when asked for.
    `category` filters blocks, like "overdrive".

    `installed` is true, false, or null if the pedal couldn't be checked. For a model, write
    `index` to `param` on `block`. For a file, write `file` to `param` on one of `blocks`.
    Trust `inspired_by` only as far as `notes` says, and never guess it for an unknown model.
    """
    return _find_models(client, query, kind, category, limit)


@mcp.tool()
def list_block_presets(block: str) -> list[str]:
    """List a block's factory and user presets."""
    return client.call(BLOCKS, "blockPresets", [block])


@mcp.tool()
def get_footswitches() -> list[dict[str, Any]]:
    """Summarise footswitches. Switches 1-3 and 4-6 are separate banks.

    Scene switches show doubling and path; use get_scene for the rest. The pedal keeps an old
    module and operation on scene switches, so those only appear on toggle and hold switches.
    """
    fs = client.get_properties(FOOTSWITCH)
    summary = []
    for n in range(1, 7):
        kind = _SWITCH_TYPES.get(fs.get(f"ModeNew{n}"))
        entry: dict[str, Any] = {
            "switch": n,
            "type": kind,
            "label": fs.get(f"FootSwitchText{n}"),
            "on": fs.get(f"FootSwitchOn{n}"),
        }
        if kind == "scene":
            entry["scene_active"] = fs.get(f"SceneActive{n}")
            entry["doubling"] = _SCENE_SIDES.get(fs.get(f"SceneDoubleSwitch{n}"), "nochange")
            entry["path"] = _SCENE_SIDES.get(fs.get(f"ScenePathSwitch{n}"), "nochange")
        else:
            entry["module"] = fs.get(f"Module{n}")
            entry["operation"] = fs.get(f"Operation{n}")
        summary.append(entry)
    return summary


@mcp.tool()
def get_scene(switch: int) -> dict[str, Any]:
    """Read a scene on footswitch 1-6: blocks, doubling, path, presets, color and MIDI out.

    Uses the same shape as set_scene. `states` of 2 means the switch also has a second state,
    which this server can't read or change. The pedal doesn't report which A/B side is active.
    """
    return read_scene(client, switch)


@mcp.tool()
def get_footswitch_settings() -> dict[str, Any]:
    """Read global settings that affect every rig: tuner and looper switch behaviour and more.

    This server can't change them, so do that on the pedal.
    """
    values = client.get_properties(_GENERAL_SETTINGS)
    properties = client.get_meta(_GENERAL_SETTINGS).get("properties") or {}

    def option(key: str) -> Any:
        names = ((properties.get(key) or {}).get("x-options") or {}).get("strings") or []
        value = values.get(key)
        return names[value] if isinstance(value, int) and value < len(names) else value

    return {
        "tuner_switch": option("TunerFSAssignment"),
        "looper_switch": option("LooperFSAssignment"),
        "auto_assign_footswitches": values.get("AutoAssignments"),
        "on_press": values.get("OnPressFS"),
    }


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
def set_scene(
    switch: int,
    name: str,
    blocks: dict[str, str] | None = None,
    doubling: str | None = None,
    path: str | None = None,
    presets: dict[str, str] | None = None,
    color: int | None = None,
) -> dict[str, Any]:
    """Make footswitch 1-6 a scene, or edit one, without saving. Reads the result back.

    `blocks` maps blocks in the chain to "on", "off" or "nochange", and replaces the scene's
    whole map: blocks it doesn't list become "nochange". `doubling` and `path` are "A", "B" or
    "nochange". `presets` maps blocks to a preset to recall, or "No Preset" to clear one.
    `color` is 0-13. Anything you leave out keeps its current value.

    Check `mismatches` and `warnings` in the result. Second switch states aren't supported.
    """
    optional = {"blocks": blocks, "doubling": doubling, "path": path, "presets": presets, "color": color}
    scene = {"name": name} | {key: value for key, value in optional.items() if value is not None}
    check_scene(switch, scene, require_blocks=False)
    check_scene_presets(client, scene)
    values = footswitch_values(
        {"blocks": client.current_chain(), "footswitches": {str(switch): {"scene": scene}}}
    )[0]
    for key, value in values.items():
        client.set_properties(FOOTSWITCH, {key: value})
    time.sleep(_LABEL_UPDATE_SECONDS)
    return {
        "scene": read_scene(client, switch),
        "mismatches": find_mismatches(client, [(FOOTSWITCH, values)]),
        "warnings": scene_warnings(client, scene),
    }


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
def get_rig_spec_format() -> str:
    """Get the create_rig spec format, including footswitches, scenes and routings."""
    return _RIG_SPEC_FORMAT.read_text(encoding="utf-8")


@mcp.resource("headrush://docs/rig-specs", mime_type="text/markdown")
def rig_spec_format() -> str:
    """The create_rig spec format, for clients that read resources."""
    return get_rig_spec_format()


@mcp.tool()
def create_rig(
    spec: dict[str, Any] | None = None,
    spec_path: str | None = None,
    save: bool = True,
    resume_draft: bool = False,
) -> dict[str, Any]:
    """Build a new rig from a spec, verify it, and save it only if everything matches.

    Pass `spec` or a local JSON `spec_path`; get_rig_spec_format has the format, including
    scenes. Unknown keys are refused. Refused if the name exists or the loaded rig has unsaved
    edits. If a build fails, retry with `resume_draft` to reuse the unnamed draft it left,
    which overwrites that draft.
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
