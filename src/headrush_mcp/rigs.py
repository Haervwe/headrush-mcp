"""Build a new rig from a JSON spec. See rigs/ for examples."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .client import BLOCKS, CHAIN, FOOTSWITCH, RIGS, HeadRushClient, HeadRushError, block_path

_TOLERANCE = 0.002
_ATTEMPTS = 6
_SETTLE_SECONDS = 1.5
_MODE_TOGGLE = 0
_MODE_SCENE = 2
_NO_CHANGE = 0
_SCENE_STATES = {"on": 1, "off": 2}

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

    if not resume_draft and client.call(RIGS, "makeNewRigConfirm", [-1]) is False:
        raise HeadRushError("The device refused to create a new rig")

    expected: list[tuple[str, dict[str, Any]]] = [(CHAIN, chain_values)]
    for entry in spec["blocks"]:
        if entry.get("params"):
            expected.append((block_path(entry["block"]), entry["params"]))
    if spec.get("mix"):
        expected.append((block_path("Mix"), spec["mix"]))
    expected += [(FOOTSWITCH, values) for values in footswitch_values(spec)]

    mismatches = _write_until_stable(client, expected, sleep)
    saved = False
    if save and not mismatches:
        saved = client.call(RIGS, "saveRigAs", [name, -1]) is not False
    return {
        "name": name,
        "saved": saved,
        "mismatches": mismatches,
        "chain": client.current_chain(),
        "status": client.status(),
    }


def _check_spec(spec: dict[str, Any]) -> None:
    """Reject malformed specs with a readable reason, before touching the pedal."""
    if not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise HeadRushError("Spec needs a non-empty 'name'")
    blocks = spec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise HeadRushError("Spec needs a non-empty 'blocks' list")
    slots = []
    for entry in blocks:
        if not isinstance(entry, dict) or "slot" not in entry or "block" not in entry:
            raise HeadRushError(f"Each block needs 'slot' and 'block': {entry!r}")
        if not isinstance(entry["slot"], int) or not 1 <= entry["slot"] <= 14:
            raise HeadRushError(f"Slot must be 1-14: {entry['slot']!r}")
        slots.append(entry["slot"])
    if len(slots) != len(set(slots)):
        raise HeadRushError("Spec uses the same slot more than once")
    for number, switch in spec.get("footswitches", {}).items():
        if str(number) not in {"1", "2", "3", "4", "5", "6"}:
            raise HeadRushError(f"Footswitch must be 1-6: {number!r}")
        if "scene" in switch:
            scene = switch["scene"]
            if not scene.get("name") or not isinstance(scene.get("blocks"), dict):
                raise HeadRushError(f"Scene on footswitch {number} needs 'name' and 'blocks'")
            bad = {s for s in scene["blocks"].values() if s not in _SCENE_STATES}
            if bad:
                raise HeadRushError(f"Scene block states must be 'on' or 'off': {sorted(map(str, bad))}")
        elif "module" not in switch:
            raise HeadRushError(f"Footswitch {number} needs 'module' or 'scene'")


def footswitch_values(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a spec's footswitches into property writes, one dict per switch.

    A switch is either a stomp (`module`) or a scene (`scene`). A scene sets the
    listed blocks on or off and leaves the rest of the chain unchanged.
    """
    slots = {entry["block"]: entry["slot"] for entry in spec["blocks"]}
    result = []
    for number, switch in sorted(spec.get("footswitches", {}).items()):
        if "scene" in switch:
            scene = switch["scene"]
            values: dict[str, Any] = {
                f"ModeNew{number}": _MODE_SCENE,
                f"UserFootSwitchText{number}": scene["name"],
            }
            for slot in slots.values():
                values[f"Scene{number}_{slot}_Mode"] = _NO_CHANGE
            for block, state in scene["blocks"].items():
                if block not in slots:
                    raise HeadRushError(f"Scene {scene['name']} uses a block not in the chain: {block}")
                values[f"Scene{number}_{slots[block]}_Mode"] = _SCENE_STATES[state]
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
    for _ in range(_ATTEMPTS):
        for path, values in pending:
            # One write per key, in the order the official editor uses.
            for key, value in values.items():
                client.set_properties(path, {key: value})
        sleep(_SETTLE_SECONDS)
        pending = _differences(client, expected)
        if not pending:
            return []
    return _verify(client, expected)


def _differences(
    client: HeadRushClient, expected: list[tuple[str, dict[str, Any]]]
) -> list[tuple[str, dict[str, Any]]]:
    pending = []
    for path, values in expected:
        actual = client.get_properties(path)
        wrong = {k: v for k, v in values.items() if not _same(actual.get(k), v)}
        if wrong:
            pending.append((path, wrong))
    return pending


def _same(got: Any, wanted: Any) -> bool:
    if isinstance(wanted, float):
        return isinstance(got, (int, float)) and abs(got - wanted) <= _TOLERANCE
    return got == wanted


def _verify(client: HeadRushClient, expected: list[tuple[str, dict[str, Any]]]) -> list[str]:
    problems = []
    for path, values in _differences(client, expected):
        actual = client.get_properties(path)
        problems += [f"{path}.{k}: wanted {v!r}, got {actual.get(k)!r}" for k, v in values.items()]
    return problems
