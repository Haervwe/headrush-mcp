"""Build a new rig from a JSON spec. See rigs/ for examples."""

from __future__ import annotations

import time
from collections.abc import Callable
from math import log, sqrt
from typing import Any

from .client import (
    BLOCKS,
    CHAIN,
    EMPTY_SLOT,
    FOOTSWITCH,
    GENERAL_SETTINGS,
    RIGS,
    HeadRushClient,
    HeadRushError,
    block_path,
)

_TOLERANCE = 0.002
_EXPONENTIAL = 6
# The official editor's curves by normalizeAlgo, as (0-1 to displayed, displayed to 0-1).
# 0 is linear, and 10 (reverb time) is left to the fixed tolerance.
_CURVES: dict[int, tuple[Callable[[float, float, float], float], ...]] = {
    0: (lambda v, lo, hi: lo + (hi - lo) * v, lambda d, lo, hi: (d - lo) / (hi - lo)),
    5: (lambda v, lo, hi: lo + (hi - lo) * v * v, lambda d, lo, hi: sqrt((d - lo) / (hi - lo))),
    _EXPONENTIAL: (
        lambda v, lo, hi: lo * (hi / lo) ** v,
        lambda d, lo, hi: log(d / lo) / log(hi / lo),
    ),
}
_ATTEMPTS = 6
_SETTLE_SECONDS = 1.5
_MODE_TOGGLE = 0
_MODE_SCENE = 2
_NO_CHANGE = 0
_NO_PRESET = "No Preset"
_MAX_COLOUR = 13
_SCENE_STATES = {"on": 1, "off": 2, "nochange": _NO_CHANGE}
_SCENE_SIDES = {"A": 1, "B": 2, "nochange": _NO_CHANGE}
_SPEC_HELP = "See get_rig_spec_format for the format."
_SPEC_KEYS = {"name", "routing", "mix", "blocks", "footswitches"}
_BLOCK_KEYS = {"slot", "block", "params"}
_STOMP_KEYS = {"module", "operation", "name", "mode"}
_SCENE_KEYS = {"name", "blocks", "doubling", "path", "presets", "color"}

ROUTINGS = [
    {"routing": 0, "name": "Straight Path", "before_split": "1-14", "path_a": None, "path_b": None, "after_mix": None},
    {"routing": 1, "name": "Middle Split 3-4-3", "before_split": "1-3", "path_a": "4-7", "path_b": "8-11", "after_mix": "12-14"},
    {"routing": 2, "name": "Middle Split 5-3-3", "before_split": "1-5", "path_a": "6-8", "path_b": "9-11", "after_mix": "12-14"},
    {"routing": 3, "name": "Middle Split 7-2-3", "before_split": "1-7", "path_a": "8-9", "path_b": "10-11", "after_mix": "12-14"},
    {"routing": 4, "name": "Immediate Split", "before_split": None, "path_a": "1-5", "path_b": "6-10", "after_mix": "11-14"},
]


def apply_rig(
    client: HeadRushClient,
    spec: dict[str, Any],
    save: bool = True,
    resume_draft: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Create a new rig, read every value back, and save only if they all match.

    Existing rigs are never overwritten: this refuses to run if the name is taken
    or the loaded rig has unsaved edits. If anything fails, nothing is saved.

    With `resume_draft`, a failed build can be retried on the unnamed draft it left
    behind. That overwrites the draft, so it's only allowed when no saved rig is loaded.

    Creating a rig and placing blocks both finish asynchronously and can undo earlier
    writes, so writes are repeated until they hold through a settle period.

    Blocks the firmware lists but has no object for are refused before anything is written.
    """
    _check_spec(spec)
    name = spec["name"]
    client.require_new_name(name)
    if resume_draft:
        if client.get_properties(RIGS).get("loadedName"):
            raise HeadRushError("resume_draft needs an unnamed draft, but a saved rig is loaded")
    else:
        client.require_clean()

    types = client.get_properties(BLOCKS)["ModuleTypes"]
    wanted = {entry["slot"]: entry for entry in spec["blocks"]}
    chain_values: dict[str, Any] = {"Routing": spec.get("routing", 0)}
    for slot in range(1, 15):
        block = wanted[slot]["block"] if slot in wanted else "Empty Slot"
        if block not in types:
            raise HeadRushError(f"Unknown block: {block}")
        chain_values[f"ModuleType{slot}"] = types.index(block)
    for block in sorted({entry["block"] for entry in spec["blocks"]}):
        client.require_block_object(block)

    # Everything that can be refused is checked before the pedal changes.
    switch_values = footswitch_values(spec)
    scenes = [s["scene"] for s in spec.get("footswitches", {}).values() if "scene" in s]
    for scene in scenes:
        check_scene_presets(client, scene)

    if not resume_draft and client.call(RIGS, "makeNewRigConfirm", [-1]) is False:
        raise HeadRushError("The device refused to create a new rig")

    expected: list[tuple[str, dict[str, Any]]] = [(CHAIN, chain_values)]
    for entry in spec["blocks"]:
        if entry.get("params"):
            expected.append((block_path(entry["block"]), entry["params"]))
    if spec.get("mix"):
        expected.append((block_path("Mix"), spec["mix"]))
    expected += [(FOOTSWITCH, values) for values in switch_values]

    mismatches = _write_until_stable(client, expected, sleep)
    saved = False
    if save and not mismatches:
        saved = client.call(RIGS, "saveRigAs", [name, -1]) is not False
    warnings = sorted({w for scene in scenes for w in scene_warnings(client, scene)})
    warnings += auto_assign_warnings(client)
    return {
        "name": name,
        "saved": saved,
        "mismatches": mismatches,
        "warnings": warnings,
        "chain": client.current_chain(),
        "status": client.status(),
    }


def _check_keys(found: Any, allowed: set[str], where: str) -> None:
    """Refuse keys we'd otherwise ignore. Keys starting with _ are comments."""
    unknown = sorted(str(k) for k in found if not str(k).startswith("_") and k not in allowed)
    if unknown:
        raise HeadRushError(
            f"Unknown {where} keys: {unknown}. Allowed: {sorted(allowed)}. {_SPEC_HELP}"
        )


def check_scene(number: Any, scene: Any, require_blocks: bool = True) -> None:
    """Reject a malformed scene with a readable reason, before touching the pedal."""
    if str(number) not in {"1", "2", "3", "4", "5", "6"}:
        raise HeadRushError(f"Footswitch must be 1-6: {number!r}")
    if not isinstance(scene, dict):
        raise HeadRushError(f"Scene on footswitch {number} must be an object. {_SPEC_HELP}")
    _check_keys(scene, _SCENE_KEYS, f"scene (footswitch {number})")
    if not scene.get("name"):
        raise HeadRushError(f"Scene on footswitch {number} needs 'name' and 'blocks'")
    blocks = scene.get("blocks")
    if blocks is None and require_blocks or blocks is not None and not isinstance(blocks, dict):
        raise HeadRushError(f"Scene on footswitch {number} needs 'name' and 'blocks'")
    bad = {s for s in (blocks or {}).values() if s not in _SCENE_STATES}
    if bad:
        raise HeadRushError(
            f"Scene block states must be 'on', 'off' or 'nochange': {sorted(map(str, bad))}"
        )
    for key in ("doubling", "path"):
        if key in scene and scene[key] not in _SCENE_SIDES:
            raise HeadRushError(f"Scene {key} must be 'A', 'B' or 'nochange': {scene[key]!r}")
    presets = scene.get("presets", {})
    if not isinstance(presets, dict) or not all(isinstance(p, str) for p in presets.values()):
        raise HeadRushError(f"Scene presets must map block names to preset names: {presets!r}")
    color = scene.get("color", 0)
    if not isinstance(color, int) or isinstance(color, bool) or not 0 <= color <= _MAX_COLOUR:
        raise HeadRushError(f"Scene color must be 0-{_MAX_COLOUR}: {color!r}")


def check_scene_presets(client: HeadRushClient, scene: dict[str, Any]) -> None:
    """Refuse presets the block doesn't have. 'No Preset' clears a block's recall."""
    for block, preset in (scene.get("presets") or {}).items():
        if preset != _NO_PRESET and preset not in client.call(BLOCKS, "blockPresets", [block]):
            raise HeadRushError(
                f"{block} has no preset named '{preset}'. See list_block_presets."
            )


def scene_warnings(client: HeadRushClient, scene: dict[str, Any]) -> list[str]:
    """Explain scene settings the pedal accepts but that won't do anything."""
    warnings = []
    if scene.get("doubling", "nochange") != "nochange":
        if not client.get_properties(FOOTSWITCH).get("AnySwitchDoubling"):
            warnings.append(
                "No block is switching between A and B, so 'doubling' has no effect. "
                "Set Doubling on and DoubleMode to Switch on an Amp or Cab."
            )
    if scene.get("path", "nochange") != "nochange":
        if not client.get_properties(CHAIN).get("Routing"):
            warnings.append("'path' has no effect on a Straight Path routing.")
    return warnings


def auto_assign_warnings(client: HeadRushClient) -> list[str]:
    """Warn that Auto Assign Footswitches may have put newly placed blocks on free switches.

    Never fails: if the global settings can't be read, there's no warning.
    """
    try:
        auto = client.get_properties(GENERAL_SETTINGS).get("AutoAssignments")
    except HeadRushError:
        return []
    if not auto:
        return []
    return [
        "Auto Assign Footswitches is on in Global Settings > General, so the pedal may have "
        "assigned a newly placed block to a free footswitch. Check get_footswitches."
    ]


def _read_scene_state(fs: dict[str, Any], switch: int, prefix: str = "") -> dict[str, Any]:
    """Read one state of a scene. The second state's keys start with State2."""
    states = {value: name for name, value in _SCENE_STATES.items()}
    sides = {value: name for name, value in _SCENE_SIDES.items()}
    blocks = {}
    presets = {}
    for slot in range(1, 15):
        block = fs.get(f"{prefix}Scene{switch}_{slot}_Effect")
        if not block or block == EMPTY_SLOT:
            continue
        blocks[block] = states.get(fs.get(f"{prefix}Scene{switch}_{slot}_Mode"), "nochange")
        preset = fs.get(f"{prefix}Scene{switch}Slot{slot}Preset")
        if preset and preset != _NO_PRESET:
            presets[block] = preset
    return {
        "blocks": blocks,
        "doubling": sides.get(fs.get(f"{prefix}SceneDoubleSwitch{switch}"), "nochange"),
        "path": sides.get(fs.get(f"{prefix}ScenePathSwitch{switch}"), "nochange"),
        "presets": presets,
        "color": fs.get(f"{prefix}MacroColour{switch}"),
        "midi_out": fs.get(f"{prefix}SceneMIDIOut{switch}"),
    }


def read_scene(client: HeadRushClient, switch: int) -> dict[str, Any]:
    """Read a scene in the same shape set_scene and rig specs use."""
    if switch not in range(1, 7):
        raise HeadRushError(f"Footswitch must be 1-6: {switch!r}")
    fs = client.get_properties(FOOTSWITCH)
    if fs.get(f"ModeNew{switch}") != _MODE_SCENE:
        raise HeadRushError(f"Footswitch {switch} isn't a scene")
    scene = {
        "switch": switch,
        "name": fs.get(f"UserFootSwitchText{switch}") or fs.get(f"FootSwitchText{switch}"),
        "active": fs.get(f"SceneActive{switch}"),
        **_read_scene_state(fs, switch),
        "states": fs.get(f"SceneNumberOfStates{switch}"),
    }
    if scene["states"] == 2:
        scene["current_state"] = 2 if fs.get(f"SceneState{switch}") == 1 else 1
        scene["second_state"] = _read_scene_state(fs, switch, "State2")
    return scene


def _check_spec(spec: dict[str, Any]) -> None:
    """Reject malformed specs with a readable reason, before touching the pedal."""
    if "scenes" in spec:
        raise HeadRushError(f"Scenes go under footswitches.<number>.scene. {_SPEC_HELP}")
    _check_keys(spec, _SPEC_KEYS, "spec")
    if not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise HeadRushError("Spec needs a non-empty 'name'")
    blocks = spec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise HeadRushError("Spec needs a non-empty 'blocks' list")
    slots = []
    for entry in blocks:
        if not isinstance(entry, dict) or "slot" not in entry or "block" not in entry:
            raise HeadRushError(f"Each block needs 'slot' and 'block': {entry!r}")
        _check_keys(entry, _BLOCK_KEYS, f"block ({entry['block']})")
        if not isinstance(entry["slot"], int) or not 1 <= entry["slot"] <= 14:
            raise HeadRushError(f"Slot must be 1-14: {entry['slot']!r}")
        slots.append(entry["slot"])
    if len(slots) != len(set(slots)):
        raise HeadRushError("Spec uses the same slot more than once")
    for number, switch in spec.get("footswitches", {}).items():
        if str(number) not in {"1", "2", "3", "4", "5", "6"}:
            raise HeadRushError(f"Footswitch must be 1-6: {number!r}")
        if not isinstance(switch, dict):
            raise HeadRushError(f"Footswitch {number} must be an object. {_SPEC_HELP}")
        if "scene" in switch:
            _check_keys(switch, {"scene"}, f"footswitch {number}")
            check_scene(number, switch["scene"])
        elif "module" in switch:
            _check_keys(switch, _STOMP_KEYS, f"footswitch {number}")
        else:
            raise HeadRushError(f"Footswitch {number} needs 'module' or 'scene'")


def _scene_values(number: Any, scene: dict[str, Any], slots: dict[str, int]) -> dict[str, Any]:
    def slot_of(block: str) -> int:
        if block not in slots:
            raise HeadRushError(f"Scene {scene['name']} uses a block not in the chain: {block}")
        return slots[block]

    values: dict[str, Any] = {
        f"ModeNew{number}": _MODE_SCENE,
        f"UserFootSwitchText{number}": scene["name"],
    }
    if scene.get("blocks") is not None:
        for slot in slots.values():
            values[f"Scene{number}_{slot}_Mode"] = _NO_CHANGE
        for block, state in scene["blocks"].items():
            values[f"Scene{number}_{slot_of(block)}_Mode"] = _SCENE_STATES[state]
    for block, preset in (scene.get("presets") or {}).items():
        values[f"Scene{number}Slot{slot_of(block)}Preset"] = preset
    if "doubling" in scene:
        values[f"SceneDoubleSwitch{number}"] = _SCENE_SIDES[scene["doubling"]]
    if "path" in scene:
        values[f"ScenePathSwitch{number}"] = _SCENE_SIDES[scene["path"]]
    if "color" in scene:
        values[f"MacroColour{number}"] = scene["color"]
    return values


def footswitch_values(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a spec's footswitches into property writes, one dict per switch.

    A switch is either a stomp (`module`) or a scene (`scene`). A scene's `blocks`
    replaces its whole on/off map, and blocks it doesn't list become no change.
    Other scene settings are only written when present.
    """
    slots = {entry["block"]: entry["slot"] for entry in spec["blocks"]}
    result = []
    for number, switch in sorted(spec.get("footswitches", {}).items()):
        if "scene" in switch:
            values = _scene_values(number, switch["scene"], slots)
        else:
            values = {
                f"ModeNew{number}": switch.get("mode", _MODE_TOGGLE),
                f"Module{number}": switch["module"],
                f"Operation{number}": switch.get("operation", "On"),
                f"UserFootSwitchText{number}": switch.get("name", ""),
            }
        result.append(values)
    return result


def _write_until_stable(
    client: HeadRushClient,
    expected: list[tuple[str, dict[str, Any]]],
    sleep: Callable[[float], None],
) -> list[str]:
    """Write values, then rewrite whatever didn't stick until a full pass holds."""
    pending = expected
    steps = _steps(client, expected)
    for _ in range(_ATTEMPTS):
        for path, values in pending:
            # One write per key, in the order the official editor uses.
            for key, value in values.items():
                client.set_properties(path, {key: value})
        sleep(_SETTLE_SECONDS)
        pending = _differences(client, expected, steps)
        if not pending:
            return []
    return find_mismatches(client, expected, steps)


def _wire_step(schema: dict[str, Any], wanted: float) -> float | None:
    """Return one grid step around a 0-1 value, in 0-1 units, or None if it can't be worked out.

    The schema's grid is in displayed units, such as 0.1 dB, so it depends on the range and curve.
    """
    options = schema.get("x-options") or {}
    algo = options.get("normalizeAlgo") or 0
    grid, low, high = options.get("grid"), schema.get("minimum"), schema.get("maximum")
    numbers = (grid, low, high)
    if algo not in _CURVES or not all(
        isinstance(n, (int, float)) and not isinstance(n, bool) for n in numbers
    ):
        return None
    if grid <= 0 or high <= low or (algo == _EXPONENTIAL and low <= 0):
        return None
    to_display, to_wire = _CURVES[algo]
    display = to_display(wanted, low, high)
    return max(
        abs(to_wire(min(display + grid, high), low, high) - wanted),
        abs(to_wire(max(display - grid, low), low, high) - wanted),
    )


def _steps(
    client: HeadRushClient, expected: list[tuple[str, dict[str, Any]]]
) -> dict[tuple[str, str], float]:
    """Work out each float parameter's grid step from the schema, one meta read per object.

    The pedal is reported to snap a written number to its grid, so it can read back a little
    off. Only objects with float values being verified are read, and a step that can't be
    worked out leaves the fixed tolerance in place.
    """
    steps: dict[tuple[str, str], float] = {}
    seen: set[str] = set()
    for path, values in expected:
        floats = [k for k, v in values.items() if isinstance(v, float)]
        if not floats or path in seen:
            continue
        seen.add(path)
        try:
            properties = client.get_meta(path).get("properties") or {}
        except HeadRushError:
            continue
        for key in floats:
            step = _wire_step(properties.get(key) or {}, values[key])
            if step is not None:
                steps[(path, key)] = step
    return steps


def _differences(
    client: HeadRushClient,
    expected: list[tuple[str, dict[str, Any]]],
    steps: dict[tuple[str, str], float] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    steps = steps or {}
    pending = []
    for path, values in expected:
        actual = client.get_properties(path)
        wrong = {
            k: v for k, v in values.items() if not _same(actual.get(k), v, steps.get((path, k)))
        }
        if wrong:
            pending.append((path, wrong))
    return pending


def _same(got: Any, wanted: Any, step: float | None = None) -> bool:
    if isinstance(wanted, float):
        # Allow a whole grid step, not half: snapping is community-documented, and nobody
        # has reported whether the pedal rounds to the nearest step or down.
        tolerance = max(_TOLERANCE, step or 0)
        return isinstance(got, (int, float)) and abs(got - wanted) <= tolerance
    return got == wanted


def find_mismatches(
    client: HeadRushClient,
    expected: list[tuple[str, dict[str, Any]]],
    steps: dict[tuple[str, str], float] | None = None,
) -> list[str]:
    """List values that didn't read back. Floats may differ by up to one grid step."""
    if steps is None:
        steps = _steps(client, expected)
    problems = []
    for path, values in _differences(client, expected, steps):
        actual = client.get_properties(path)
        problems += [f"{path}.{k}: wanted {v!r}, got {actual.get(k)!r}" for k, v in values.items()]
    return problems
