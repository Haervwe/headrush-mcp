import json
from math import log, sqrt
from pathlib import Path

import httpx
import pytest

from headrush_mcp.client import (
    BLOCKS,
    CHAIN,
    FOOTSWITCH,
    RIGS,
    HeadRushClient,
    HeadRushError,
    PolicyError,
    block_path,
)
from headrush_mcp.rigs import _wire_step, apply_rig, find_mismatches, footswitch_values

SPEC = {
    "name": "New Rig",
    "blocks": [{"slot": 1, "block": "Amp", "params": {"Bass": 0.4, "On": True}}],
    "footswitches": {"1": {"module": "Amp"}},
}


class FakePedal:
    """In-memory pedal that records every state-changing request."""

    def __init__(self, dirty: bool = False, drop_writes_to: str | None = None) -> None:
        self.calls: list[str] = []
        self.drop_writes_to = drop_writes_to
        chain = {f"ModuleType{n}": 2 for n in range(1, 15)} | {"Routing": 1}
        self.objects = {
            RIGS: {"dirty": dirty, "loadedName": "Mine", "loadedID": "x", "AllRigNames": ["Mine"]},
            BLOCKS: {"ModuleTypes": ["Empty Slot", "Amp", "Cab"]},
            CHAIN: chain,
            FOOTSWITCH: {},
            "/Evil/Gui": {"AppVersion": "1", "DeviceName": "d"},
            "/Evil/Engine/CPUMeter": {"CPUTimeSmoothed": 0.1},
            "/Evil/Engine/Patch/Amp": {"Bass": 0.5, "On": False},
        }
        chain_meta = {k: {"type": "integer", "minimum": 0, "maximum": 263} for k in chain}
        self.meta = {
            CHAIN: chain_meta,
            FOOTSWITCH: {
                "ModeNew1": {"type": "integer", "minimum": 0, "maximum": 2},
                "Module1": {"type": "string"},
                "Operation1": {"type": "string"},
                "UserFootSwitchText1": {"type": "string"},
            },
            "/Evil/Engine/Patch/Amp": {
                "Bass": {"type": "number", "minimum": 0, "maximum": 100},
                "On": {"type": "boolean"},
                "Serial": {"type": "string", "readOnly": True},
            },
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path.startswith("/object-method"):
            self.calls.append(path)
            return httpx.Response(200, json={"methodReturnValue": True})
        if path.startswith("/object-meta"):
            target = path[len("/object-meta") :]
            if target not in self.meta:
                return httpx.Response(404, json={"desc": "no such object"})
            return httpx.Response(200, json={"properties": self.meta[target]})
        target = path[len("/object-properties") :]
        if target not in self.objects:
            return httpx.Response(404, json={"desc": "no such object"})
        if request.method == "PUT":
            self.calls.append(f"PUT {target}")
            if target != self.drop_writes_to:
                self.objects[target].update(json.loads(request.content))
            return httpx.Response(200, json={})
        return httpx.Response(200, json=self.objects[target])


def make(pedal: FakePedal, allow_writes: bool = True) -> HeadRushClient:
    return HeadRushClient(host="pedal", allow_writes=allow_writes, transport=httpx.MockTransport(pedal))


def test_writes_are_off_by_default():
    pedal = FakePedal()
    client = make(pedal, allow_writes=False)
    with pytest.raises(PolicyError, match="disabled"):
        client.set_properties("/Evil/Engine/Patch/Amp", {"Bass": 0.2})
    with pytest.raises(PolicyError, match="disabled"):
        client.call(RIGS, "saveRigAs", ["x", -1])
    assert pedal.calls == []


@pytest.mark.parametrize(
    "path,method",
    [
        (RIGS, "deleteRig"),
        (RIGS, "renameRig"),
        ("/Evil/Cloud/Master", "uploadRig"),
        ("/Evil/API/Setlists", "deleteSetlist"),
    ],
)
def test_dangerous_methods_never_reach_the_device(path, method):
    pedal = FakePedal()
    with pytest.raises(PolicyError, match="not allowed"):
        make(pedal).call(path, method, [])
    assert pedal.calls == []


@pytest.mark.parametrize(
    "path,values",
    [
        ("/Evil/Engine/Patch/Amp", {"Bass": 50}),
        ("/Evil/Engine/Patch/Amp", {"Bass": True}),
        ("/Evil/Engine/Patch/Amp", {"Nope": 0.5}),
        ("/Evil/Engine/Patch/Amp", {"Serial": "x"}),
        ("/Evil/Engine/Patch/Rig", {"PresetName": "x"}),
        ("/Evil/Engine/Settings/General", {"Anything": 1}),
        (CHAIN, {"Lock": True}),
        (FOOTSWITCH, {"SceneMIDIOut1": ""}),
        (FOOTSWITCH, {"Scene1_15_Mode": 1}),
    ],
)
def test_bad_writes_are_refused(path, values):
    pedal = FakePedal()
    with pytest.raises(PolicyError):
        make(pedal).set_properties(path, values)
    assert not [c for c in pedal.calls if c.startswith("PUT")]


def no_sleep(_: float) -> None:
    pass


def test_apply_rewrites_values_reset_by_block_initialization():
    pedal = FakePedal()
    naps = []

    def sleep_then_reset(seconds: float) -> None:
        # The first settle period is when the real block resets to defaults.
        if not naps:
            pedal.objects["/Evil/Engine/Patch/Amp"].update(Bass=0.5, On=False)
        naps.append(seconds)

    result = apply_rig(make(pedal), SPEC, sleep=sleep_then_reset)
    assert result["saved"] is True and result["mismatches"] == []
    assert pedal.objects["/Evil/Engine/Patch/Amp"] == {"Bass": 0.4, "On": True}
    assert len(naps) == 2


def test_save_loaded_rig_requires_the_exact_loaded_name():
    pedal = FakePedal()
    client = make(pedal)
    for wrong in ("Other", ""):
        with pytest.raises(PolicyError, match="Refusing"):
            client.save_loaded_rig(wrong)
    assert pedal.calls == []
    client.save_loaded_rig("Mine")
    assert pedal.calls[-1].endswith("saveRig")


def test_save_loaded_rig_needs_writes_enabled():
    pedal = FakePedal()
    with pytest.raises(PolicyError, match="disabled"):
        make(pedal, allow_writes=False).save_loaded_rig("Mine")
    assert pedal.calls == []


def test_apply_rewrites_chain_cleared_by_new_rig_creation():
    pedal = FakePedal()
    naps = []

    def sleep_then_clear(seconds: float) -> None:
        # The real pedal can finish clearing the new rig after slots were written.
        if not naps:
            pedal.objects[CHAIN]["ModuleType1"] = 0
        naps.append(seconds)

    result = apply_rig(make(pedal), SPEC, sleep=sleep_then_clear)
    assert result["saved"] is True and result["mismatches"] == []
    assert pedal.objects[CHAIN]["ModuleType1"] == 1


def test_resume_draft_retries_on_unnamed_draft_without_new_rig():
    pedal = FakePedal(dirty=True)
    pedal.objects[RIGS]["loadedName"] = ""
    result = apply_rig(make(pedal), SPEC, resume_draft=True, sleep=no_sleep)
    assert result["saved"] is True
    assert not any(c.endswith("makeNewRigConfirm") for c in pedal.calls)


def test_resume_draft_refuses_when_a_saved_rig_is_loaded():
    pedal = FakePedal()
    with pytest.raises(HeadRushError, match="unnamed draft"):
        apply_rig(make(pedal), SPEC, resume_draft=True, sleep=no_sleep)
    assert pedal.calls == []


def test_apply_builds_verifies_and_saves():
    pedal = FakePedal()
    result = apply_rig(make(pedal), SPEC, sleep=no_sleep)
    assert result["saved"] is True and result["mismatches"] == []
    assert pedal.objects[CHAIN]["ModuleType1"] == 1
    assert pedal.objects[CHAIN]["ModuleType2"] == 0
    assert pedal.objects["/Evil/Engine/Patch/Amp"]["Bass"] == 0.4
    assert pedal.calls[0].endswith("makeNewRigConfirm")
    assert pedal.calls[-1].endswith("saveRigAs")


def test_apply_refuses_when_edits_would_be_lost():
    pedal = FakePedal(dirty=True)
    with pytest.raises(PolicyError, match="unsaved"):
        apply_rig(make(pedal), SPEC)
    assert pedal.calls == []


def test_apply_refuses_existing_name():
    pedal = FakePedal()
    with pytest.raises(PolicyError, match="already exists"):
        apply_rig(make(pedal), SPEC | {"name": "Mine"})
    assert pedal.calls == []


def test_apply_does_not_save_when_readback_differs():
    pedal = FakePedal(drop_writes_to="/Evil/Engine/Patch/Amp")
    result = apply_rig(make(pedal), SPEC, sleep=no_sleep)
    assert result["saved"] is False
    assert any("Bass" in m for m in result["mismatches"])
    assert not any(c.endswith("saveRigAs") for c in pedal.calls)


def test_apply_writes_mix_settings_for_parallel_paths():
    pedal = FakePedal()
    pedal.objects["/Evil/Engine/Patch/Mix"] = {"Para1Pan": 0.5}
    pedal.meta["/Evil/Engine/Patch/Mix"] = {"Para1Pan": {"type": "number", "minimum": -100, "maximum": 100}}
    result = apply_rig(make(pedal), SPEC | {"routing": 1, "mix": {"Para1Pan": 0.0}}, sleep=no_sleep)
    assert result["saved"] is True
    assert pedal.objects["/Evil/Engine/Patch/Mix"]["Para1Pan"] == 0.0
    assert pedal.objects[CHAIN]["Routing"] == 1


@pytest.mark.parametrize(
    "spec,reason",
    [
        ({}, "name"),
        ({"name": "X"}, "blocks"),
        ({"name": "X", "blocks": [{"block": "Amp"}]}, "slot"),
        ({"name": "X", "blocks": [{"slot": 15, "block": "Amp"}]}, "1-14"),
        ({"name": "X", "blocks": [{"slot": 1, "block": "Amp"}, {"slot": 1, "block": "Cab"}]}, "same slot"),
        ({"name": "X", "blocks": [{"slot": 1, "block": "Amp"}], "footswitches": {"7": {"module": "Amp"}}}, "1-6"),
        ({"name": "X", "blocks": [{"slot": 1, "block": "Amp"}], "footswitches": {"1": {}}}, "module"),
        (
            {
                "name": "X",
                "blocks": [{"slot": 1, "block": "Amp"}],
                "footswitches": {"4": {"scene": {"name": "A", "blocks": {"Amp": "maybe"}}}},
            },
            "on.*off",
        ),
    ],
)
def test_malformed_specs_are_refused_before_touching_the_pedal(spec, reason):
    pedal = FakePedal()
    with pytest.raises(HeadRushError, match=reason):
        apply_rig(make(pedal), spec, sleep=no_sleep)
    assert pedal.calls == []


def test_scene_sets_listed_blocks_and_leaves_the_rest_unchanged():
    spec = {
        "blocks": [{"slot": 1, "block": "Drive"}, {"slot": 2, "block": "Amp"}, {"slot": 5, "block": "Delay"}],
        "footswitches": {
            "4": {"scene": {"name": "SOLO", "blocks": {"Drive": "on", "Delay": "off"}}},
            "1": {"module": "Drive"},
        },
    }
    stomp, scene = footswitch_values(spec)
    assert stomp == {"ModeNew1": 0, "Module1": "Drive", "Operation1": "On", "UserFootSwitchText1": ""}
    assert scene == {
        "ModeNew4": 2,
        "UserFootSwitchText4": "SOLO",
        "Scene4_1_Mode": 1,
        "Scene4_2_Mode": 0,
        "Scene4_5_Mode": 2,
    }


def test_scene_refuses_block_missing_from_chain():
    spec = {
        "blocks": [{"slot": 1, "block": "Amp"}],
        "footswitches": {"4": {"scene": {"name": "X", "blocks": {"Drive": "on"}}}},
    }
    with pytest.raises(HeadRushError, match="not in the chain"):
        footswitch_values(spec)


def test_bundled_rig_has_scenes_on_the_visible_bank():
    root = Path(__file__).parent.parent / "rigs"
    spec = json.loads((root / "stern-tipatinas.json").read_text(encoding="utf-8"))
    for number in ("4", "5", "6"):
        assert "scene" in spec["footswitches"][number]
    assert footswitch_values(spec)


def test_bundled_rig_spec_is_well_formed():
    root = Path(__file__).parent.parent / "rigs"
    spec = json.loads((root / "stern-tipatinas.json").read_text(encoding="utf-8"))
    slots = [b["slot"] for b in spec["blocks"]]
    assert len(slots) == len(set(slots)) and all(1 <= s <= 14 for s in slots)
    for entry in spec["blocks"]:
        for value in entry["params"].values():
            assert not isinstance(value, float) or 0 <= value <= 1


@pytest.mark.parametrize("block", ["Sher'ff", "IR (1024)", "8-Bit Crush"])
def test_real_block_names_with_punctuation_pass_the_path_check(block):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"On": False})

    client = HeadRushClient(host="fake", transport=httpx.MockTransport(handler))
    assert client.get_properties(block_path(block)) == {"On": False}
    assert seen


@pytest.mark.parametrize("path", ["/Evil/Engine/Patch/../Gui", "/Evil/Engine/Patch/a;b", "/Evil/Other"])
def test_unexpected_paths_are_still_refused(path):
    client = HeadRushClient(host="fake", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(PolicyError):
        client.get_properties(path)


def reply(response: httpx.Response) -> HeadRushClient:
    return HeadRushClient(host="fake", allow_writes=True, transport=httpx.MockTransport(lambda r: response))


def test_remote_off_is_explained_with_the_pedals_reason():
    response = httpx.Response(403, json={"desc": "DataModel: Web access temporarily disabled"})
    with pytest.raises(HeadRushError, match="HeadRush Remote seems to be off.*Web access temporarily"):
        reply(response).get_properties(RIGS)


def test_pin_approval_is_explained():
    with pytest.raises(HeadRushError, match="Authorize with PIN.*doesn't do PIN pairing"):
        reply(httpx.Response(401, text="Unauthorized")).get_properties(RIGS)


def test_other_http_errors_keep_their_status():
    with pytest.raises(HeadRushError) as error:
        reply(httpx.Response(404, text="nope")).get_properties(RIGS)
    assert error.value.status == 404


@pytest.mark.parametrize("body", [{"text": "OK"}, {}])
def test_write_replies_that_are_not_json_are_accepted(body):
    pedal = FakePedal()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, **body) if request.method == "PUT" else pedal(request)

    client = HeadRushClient(host="fake", allow_writes=True, transport=httpx.MockTransport(handler))
    assert client.set_properties(CHAIN, {"ModuleType1": 2}) is None


@pytest.mark.parametrize("response", [httpx.Response(200, text="OK"), httpx.Response(200)])
def test_read_replies_that_are_not_json_are_errors(response):
    with pytest.raises(HeadRushError, match="wasn't JSON"):
        reply(response).get_properties(RIGS)


@pytest.mark.parametrize(("status", "message"), [(403, "HeadRush Remote seems to be off"), (500, "500")])
def test_block_object_check_passes_other_errors_through(status, message):
    pedal = FakePedal()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/v1/object-meta"):
            return httpx.Response(status, json={})
        return pedal(request)

    client = HeadRushClient(host="fake", allow_writes=True, transport=httpx.MockTransport(handler))
    with pytest.raises(HeadRushError, match=message) as error:
        client.require_block_object("Amp")
    assert not isinstance(error.value, PolicyError)
    assert error.value.status == status
    assert pedal.calls == []


def test_a_block_with_no_object_is_refused_before_creating_a_rig():
    pedal = FakePedal()
    pedal.objects[BLOCKS]["ModuleTypes"].append("ReValver Amp 2")
    spec = SPEC | {"blocks": [{"slot": 1, "block": "ReValver Amp 2"}], "footswitches": {}}
    with pytest.raises(PolicyError, match="no object"):
        apply_rig(make(pedal), spec, sleep=no_sleep)
    assert pedal.calls == []


def grid_pedal(grid: float | None) -> FakePedal:
    """A pedal that snaps Bass a little off the written value, as the real grid does."""
    pedal = FakePedal()
    if grid is not None:
        pedal.meta[block_path("Amp")]["Bass"]["x-options"] = {"grid": grid}
    return pedal


def snap_bass(pedal: FakePedal, value: float):
    def sleep(_: float) -> None:
        pedal.objects[block_path("Amp")]["Bass"] = value

    return sleep


def test_readback_within_one_grid_step_still_saves():
    pedal = grid_pedal(1.0)  # 1 of 0-100, so 0.01 on the wire.
    result = apply_rig(make(pedal), SPEC, sleep=snap_bass(pedal, 0.408))
    assert result["saved"] is True and result["mismatches"] == []


@pytest.mark.parametrize("grid", [None, 1.0])
def test_readback_beyond_the_grid_or_tolerance_is_a_mismatch(grid):
    pedal = grid_pedal(grid)
    off = 0.408 if grid is None else 0.42
    result = apply_rig(make(pedal), SPEC, sleep=snap_bass(pedal, off))
    assert result["saved"] is False
    assert any("Bass" in m for m in result["mismatches"])


@pytest.mark.parametrize(
    ("schema", "wanted", "step"),
    [
        # A 0.1 dB grid on a -12 to 12 dB range, as on the real Amp.PreGain.
        ({"minimum": -12, "maximum": 12, "x-options": {"grid": 0.1}}, 0.5, 0.1 / 24),
        ({"minimum": 0, "maximum": 100, "x-options": {"grid": 1.0}}, 0.4, 0.01),
    ],
)
def test_wire_step_converts_a_linear_grid_from_display_units(schema, wanted, step):
    assert _wire_step(schema, wanted) == pytest.approx(step)


def test_wire_step_follows_the_squared_curve():
    schema = {"minimum": 0.25, "maximum": 20, "x-options": {"grid": 0.01, "normalizeAlgo": 5}}
    # 0.5 on the wire is 5.1875 Hz, and one step down is the wider side of a squared curve.
    expected = 0.5 - sqrt((5.1775 - 0.25) / 19.75)
    assert _wire_step(schema, 0.5) == pytest.approx(expected)


def test_wire_step_follows_the_exponential_curve():
    schema = {"minimum": 0.1, "maximum": 10, "x-options": {"grid": 0.1, "normalizeAlgo": 6}}
    # 0.5 on the wire is 1 Hz, and one step down is the wider side.
    expected = 0.5 - log(0.9 / 0.1) / log(100)
    assert _wire_step(schema, 0.5) == pytest.approx(expected)


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"minimum": 0, "maximum": 1, "x-options": {}},
        {"minimum": 0, "maximum": 1, "x-options": {"grid": 0}},
        {"minimum": 1, "maximum": 1, "x-options": {"grid": 0.1}},
        {"minimum": 0, "maximum": 10, "x-options": {"grid": 0.1, "normalizeAlgo": 6}},
        {"minimum": 0, "maximum": 10, "x-options": {"grid": 0.1, "normalizeAlgo": 3}},
    ],
)
def test_wire_step_is_unknown_when_it_cant_be_worked_out(schema):
    assert _wire_step(schema, 0.5) is None


def test_grid_check_reads_no_schema_for_integer_values():
    pedal = FakePedal()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return pedal(request)

    client = HeadRushClient(host="fake", transport=httpx.MockTransport(handler))
    assert find_mismatches(client, [(CHAIN, {"ModuleType1": 2})]) == []
    assert not [p for p in seen if "object-meta" in p]
