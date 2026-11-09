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
    EMPTY_SLOT,
    FOOTSWITCH,
    GENERAL_SETTINGS,
    RIG,
    RIGS,
    SETLISTS,
    HeadRushClient,
    HeadRushError,
    block_path,
)
from .rigs import (
    MIDI_OUT,
    ROUTINGS,
    UNASSIGNED,
    apply_rig,
    auto_assign_warnings,
    check_scene,
    check_scene_presets,
    display_values,
    find_mismatches,
    footswitch_values,
    read_scene,
    scene_warnings,
    wire_values,
)

mcp = MCPServer("headrush")
client = HeadRushClient(
    host=os.environ.get("HEADRUSH_HOST", "headrushflexprime.local"),
    allow_writes=os.environ.get("HEADRUSH_ALLOW_WRITES") == "1",
)
_MIX = block_path("Mix")
_GENERAL_SETTINGS = GENERAL_SETTINGS
_LABEL_UPDATE_SECONDS = 1.0  # The pedal updates footswitch labels shortly after a write.
_RIG_SPEC_FORMAT = Path(__file__).with_name("rig-specs.md")
_SWITCH_TYPES = {0: "toggle", 1: "hold", 2: "scene"}
_SCENE_SIDES = {0: "nochange", 1: "A", 2: "B"}
_MODE_SCENE = 2


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
def get_block(block: str, display: bool = False) -> dict[str, Any]:
    """Read a block's current values. Numbers are normalized 0-1.

    With `display`, values read as on the pedal, like "-3.0 dB", and options by name. A number
    with an unknown curve stays 0-1.
    """
    path = block_path(block)
    return display_values(client, path) if display else client.get_properties(path)


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
    `index` to `param` on `block`, or its name when using displayed units. For a file, write `file` to `param` on one of `blocks`.
    Trust `inspired_by` only as far as `notes` says, and never guess it for an unknown model.
    """
    return _find_models(client, query, kind, category, limit)


@mcp.tool()
def list_block_presets(block: str) -> list[str]:
    """List a block's factory and user presets."""
    return client.call(BLOCKS, "blockPresets", [block])


def _read_general_settings() -> tuple[dict[str, Any], dict[str, Any]]:
    """Read global settings and their schema. Read-only: this server never writes them."""
    values = client.get_properties(_GENERAL_SETTINGS)
    properties = client.get_meta(_GENERAL_SETTINGS).get("properties") or {}
    return values, properties


def _option(values: dict[str, Any], properties: dict[str, Any], key: str) -> Any:
    """Return a setting's option name, or its raw value if the schema doesn't name it."""
    names = ((properties.get(key) or {}).get("x-options") or {}).get("strings") or []
    value = values.get(key)
    return names[value] if isinstance(value, int) and 0 <= value < len(names) else value


def _on_press(values: dict[str, Any], properties: dict[str, Any]) -> bool:
    """Return whether Footswitch Function is On Press, by option name when the schema has one."""
    option = _option(values, properties, "OnPressFS")
    if isinstance(option, str):
        return "press" in option.lower()
    return bool(option)


def _bank_warnings(
    switches: list[dict[str, Any]], values: dict[str, Any], properties: dict[str, Any]
) -> list[str]:
    """Explain why switches 4-6 or the hold functions might be out of reach."""
    warnings = []
    holds = [_option(values, properties, k) for k in ("TunerFSAssignment", "LooperFSAssignment")]
    # Only judge the holds if the schema named them; a raw number can't be read as Bank A/B.
    readable = any(isinstance(hold, str) for hold in holds)
    has_bank = any("Bank" in hold for hold in holds if isinstance(hold, str))
    used_b = [
        entry["switch"]
        for entry in switches[3:]
        if entry["type"] == "scene"
        or entry["type"] in ("toggle", "hold")
        and entry.get("module") not in (None, "", EMPTY_SLOT, UNASSIGNED)
    ]
    if used_b and readable and not has_bank:
        warnings.append(
            f"Switches {used_b} are on the second bank (switches 4-6), which can't be reached "
            "until a hold function is set to Bank A/B in Global Settings > General (Assign Tuner "
            "Footswitch is the FS3 hold, Assign Looper Footswitch the FS2 hold)."
        )
    if _on_press(values, properties):
        warnings.append(
            "Footswitch Function is On Press, which disables hold functions, including Bank "
            "A/B. Set it to On Release in Global Settings > General to use them."
        )
    return warnings


@mcp.tool()
def get_footswitches() -> dict[str, Any]:
    """Summarise footswitches, with warnings about switches you can't reach.

    Switches 1-3 and 4-6 are separate banks. Switches 4-6 are only reachable by holding a
    switch whose hold function is Bank A/B, and holds don't work with Footswitch Function set
    to On Press; `warnings` says when either gets in the way.
    `auto_assign_footswitches` is whether the pedal puts newly placed blocks on free switches,
    or null if settings couldn't be read.

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
    result: dict[str, Any] = {"switches": summary, "warnings": [], "auto_assign_footswitches": None}
    try:
        values, properties = _read_general_settings()
    except HeadRushError:
        return result  # Without settings there's nothing to warn about, so don't fail.
    result["warnings"] = _bank_warnings(summary, values, properties)
    auto = values.get("AutoAssignments")
    result["auto_assign_footswitches"] = None if auto is None else bool(auto)
    return result


@mcp.tool()
def get_scene(switch: int) -> dict[str, Any]:
    """Read a scene on footswitch 1-6: blocks, doubling, path, presets, color and MIDI out.

    Uses the same shape as set_scene. When `states` is 2, each press alternates between two
    states: the top-level fields are the first, `second_state` holds the second, and
    `current_state` is 1 or 2. The pedal doesn't report which A/B side is active.
    """
    return read_scene(client, switch)


@mcp.tool()
def get_footswitch_settings() -> dict[str, Any]:
    """Read global settings that affect every rig: tuner and looper switch behaviour and more.

    This server can't change them, so do that on the pedal.
    """
    values, properties = _read_general_settings()
    return {
        "tuner_switch": _option(values, properties, "TunerFSAssignment"),
        "looper_switch": _option(values, properties, "LooperFSAssignment"),
        "auto_assign_footswitches": values.get("AutoAssignments"),
        "on_press": values.get("OnPressFS"),
    }


@mcp.tool()
def set_block_params(block: str, values: dict[str, Any], display: bool = False) -> dict[str, Any]:
    """Change parameters on the loaded rig without saving. Numbers are normalized 0-1.

    With `display`, give numbers in the units the pedal shows, like -3 for -3.0 dB or 800 for
    800 Hz, and options by name. Infinite reverb time is "Inf". describe_block has the ranges,
    and a value outside them is refused. Returns the values read back, in the same units.
    """
    return _write_values(block_path(block), values, display)


def _write_values(path: str, values: dict[str, Any], display: bool) -> dict[str, Any]:
    client.set_properties(path, wire_values(client, path, values) if display else values)
    current = display_values(client, path) if display else client.get_properties(path)
    return {key: current.get(key) for key in values}


@mcp.tool()
def set_slot_block(slot: int, block: str) -> dict[str, Any]:
    """Put a block in chain slot 1-14 without saving. Its parameters reset shortly afterwards.

    Refused for blocks the firmware lists but has no object for, such as ReValver Amp 2 and
    C-Verb 2. Returns the chain and `warnings`, such as when Auto Assign Footswitches may
    have put the block on a free switch.
    """
    types = client.get_properties(BLOCKS)["ModuleTypes"]
    if block not in types:
        raise HeadRushError(f"Unknown block: {block}")
    client.require_block_object(block)
    client.set_properties(CHAIN, {f"ModuleType{slot}": types.index(block)})
    # Clearing a slot can't put a block on a footswitch, so only warn when placing one.
    warnings = auto_assign_warnings(client) if block != EMPTY_SLOT else []
    return {"chain": client.current_chain(), "warnings": warnings}


@mcp.tool()
def set_routing(routing: int) -> dict[str, Any]:
    """Change signal routing without saving. See list_routings for the slot layout."""
    client.set_properties(CHAIN, {"Routing": routing})
    return get_current_rig()


@mcp.tool()
def set_mix(values: dict[str, float], display: bool = False) -> dict[str, Any]:
    """Set parallel path mixing without saving.

    Keys: Para1Level, Para2Level, Para1Pan, Para2Pan, ParaDelay, ParaXFade. Values are
    normalized 0-1: for pans 0 is left, 0.5 centre and 1 right; for level 0.75 is -6 dB.
    With `display`, give dB, percent (-100 is left) and microseconds instead.
    """
    return _write_values(_MIX, values, display)


def _check_switch(switch: int) -> None:
    if switch not in range(1, 7):
        raise HeadRushError(f"Footswitch must be 1-6: {switch!r}")


def _operations(switch: int, module: str) -> list[dict[str, Any]]:
    """Read what a module can do on a switch, as the official editor's assignment menu does."""
    if module == MIDI_OUT:
        return []  # Its one entry, New/Edit..., opens a dialog in the editor and isn't an operation.
    args = [switch - 1, module]
    names = client.call(FOOTSWITCH, "operationList", args)
    if not isinstance(names, list):
        return []
    enabled = client.call(FOOTSWITCH, "operationEnableList", args)
    flags = enabled if isinstance(enabled, list) else []
    return [
        {"operation": name, "enabled": not (index < len(flags) and flags[index] is False)}
        for index, name in enumerate(names)
    ]


@mcp.tool()
def list_footswitch_actions(switch: int, module: str = "") -> dict[str, Any]:
    """List what footswitch 1-6 can control, for choosing set_footswitch's arguments.

    Without `module`, returns the modules the switch can be assigned. With one, returns its
    operations; those with `enabled` false can't be chosen right now. MIDI Out is listed by
    the pedal but can't be assigned here.
    """
    _check_switch(switch)
    if not module:
        fs = client.get_properties(FOOTSWITCH)
        return {"switch": switch, "modules": fs.get(f"ModuleList{switch}") or []}
    return {"switch": switch, "module": module, "operations": _operations(switch, module)}


def _write_switch(switch: int, config: dict[str, Any]) -> dict[str, Any]:
    spec = {"blocks": client.current_chain(), "footswitches": {str(switch): config}}
    for key, value in footswitch_values(spec)[0].items():
        client.set_properties(FOOTSWITCH, {key: value})
    time.sleep(_LABEL_UPDATE_SECONDS)
    return get_footswitches()


@mcp.tool()
def set_footswitch(switch: int, module: str, operation: str = "On", name: str = "") -> dict[str, Any]:
    """Make footswitch 1-6 control one module, without saving.

    The switch becomes a Toggle, and `name` replaces its label. list_footswitch_actions has the
    valid modules and operations; an operation the pedal doesn't offer is refused. "Unassigned"
    clears the switch and ignores `operation`. MIDI Out can't be assigned here.
    """
    _check_switch(switch)
    if module == MIDI_OUT:
        raise HeadRushError("MIDI Out can't be assigned here. Do that on the pedal.")
    if module == UNASSIGNED:
        operation = ""
    try:
        operations = _operations(switch, module)
    except HeadRushError:
        operations = []  # Firmware without this list can still take the assignment.
    if operations and not any(o["operation"] == operation and o["enabled"] for o in operations):
        choices = [o["operation"] for o in operations if o["enabled"]]
        raise HeadRushError(f"{module} can't do '{operation}' on switch {switch}. Options: {choices}")
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
    state: int = 1,
) -> dict[str, Any]:
    """Make footswitch 1-6 a scene, or edit one, without saving. Reads the result back.

    `blocks` maps blocks in the chain to "on", "off" or "nochange", and replaces the scene's
    whole map: blocks it doesn't list become "nochange". `doubling` and `path` are "A", "B" or
    "nochange". `presets` maps blocks to a preset to recall, or "No Preset" to clear one.
    `color` is 0-13. Anything you leave out keeps its current value.

    `state` 2 edits the second state, which each press alternates with the first. It needs an
    existing scene, and creates the second state if there isn't one.
    `name` is shared by both states.

    Check `mismatches` and `warnings` in the result.
    """
    if state not in (1, 2):
        raise HeadRushError(f"Scene state must be 1 or 2: {state!r}")
    optional = {"blocks": blocks, "doubling": doubling, "path": path, "presets": presets, "color": color}
    scene = {"name": name} | {key: value for key, value in optional.items() if value is not None}
    check_scene(switch, scene, require_blocks=False)
    check_scene_presets(client, scene)
    values = footswitch_values(
        {"blocks": client.current_chain(), "footswitches": {str(switch): {"scene": scene}}}, state
    )[0]
    if state == 2:
        _ensure_second_state(switch)
    for key, value in values.items():
        client.set_properties(FOOTSWITCH, {key: value})
    time.sleep(_LABEL_UPDATE_SECONDS)
    return {
        "scene": read_scene(client, switch),
        "mismatches": find_mismatches(client, [(FOOTSWITCH, values)]),
        "warnings": scene_warnings(client, scene),
    }


def _require_scene(switch: int) -> dict[str, Any]:
    _check_switch(switch)
    fs = client.get_properties(FOOTSWITCH)
    if fs.get(f"ModeNew{switch}") != _MODE_SCENE:
        raise HeadRushError(f"Footswitch {switch} isn't a scene")
    return fs


def _ensure_second_state(switch: int) -> None:
    """Add a second state the way the official editor does: create it, then enable it."""
    if _require_scene(switch).get(f"SceneNumberOfStates{switch}") == 2:
        return
    client.call(FOOTSWITCH, "createNewSceneState", [switch - 1, 0])
    client.set_properties(FOOTSWITCH, {f"SceneNumberOfStates{switch}": 2})
    time.sleep(_LABEL_UPDATE_SECONDS)


@mcp.tool()
def remove_scene_second_state(switch: int) -> dict[str, Any]:
    """Go back to one state on the scene on footswitch 1-6, without saving."""
    if _require_scene(switch).get(f"SceneNumberOfStates{switch}") == 2:
        # The same two writes, in the same order, as the official editor's remove button.
        client.set_properties(FOOTSWITCH, {f"SceneNumberOfStates{switch}": 1})
        client.set_properties(FOOTSWITCH, {f"SceneState{switch}": 0})
    return read_scene(client, switch)


@mcp.tool()
def activate_scene(switch: int) -> dict[str, Any]:
    """Fire the scene on footswitch 1-6 of the loaded rig, without saving.

    On a two-state scene this applies the current state. It doesn't alternate to the other
    state, which takes a press on the pedal.
    """
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
    scenes. Unknown keys are refused. Refused if the name exists, the loaded rig has unsaved
    edits, or a block has no object on the pedal (such as ReValver Amp 2 and C-Verb 2). If a
    build fails, retry with `resume_draft` to reuse the unnamed draft it left, which
    overwrites that draft.

    Numbers count as matching within one step of the parameter's grid, since the pedal snaps
    to it. Check `warnings`: with Auto Assign Footswitches on, the pedal may have put new
    blocks on switches the spec didn't set.
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
