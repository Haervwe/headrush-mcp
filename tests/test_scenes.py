import asyncio
import json
from pathlib import Path

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from headrush_mcp import server
from headrush_mcp.client import (
    BLOCKS,
    CHAIN,
    FOOTSWITCH,
    RIGS,
    HeadRushClient,
    PolicyError,
)
from headrush_mcp.rigs import _check_spec, apply_rig

GENERAL = "/Evil/Engine/Settings/General"


class Pedal:
    """A pedal with one scene on switch 4 and a toggle on switch 1."""

    def __init__(self, doubling: bool = True, routing: int = 1) -> None:
        self.puts: list[dict] = []
        self.methods: list[str] = []
        self.ignore: set[str] = set()
        self.missing: set[str] = set()  # Objects that answer 404, like a block with no object.
        self.operations: dict[str, tuple[list, list]] = {}  # Module: names and enabled flags.
        self.puts_before_create: int | None = None
        self.arguments: dict[str, list] = {}  # Last arguments by method name.
        chain = {f"ModuleType{n}": 0 for n in range(1, 15)} | {"ModuleType1": 1, "ModuleType3": 2}
        fs = {
            "AnySwitchDoubling": doubling,
            "ModeNew1": 0,
            "Module1": "Amp",
            "Operation1": "On",
            "FootSwitchText1": "AMP",
            "ModeNew4": 2,
            "Module4": "Tuner",
            "Operation4": "AccessTuner",
            "FootSwitchText4": "LEAD",
            "UserFootSwitchText4": "LEAD",
            "SceneActive4": True,
            "SceneDoubleSwitch4": 2,
            "ScenePathSwitch4": 0,
            "MacroColour4": 3,
            "SceneMIDIOut4": "",
            "SceneNumberOfStates4": 1,
        }
        for slot in range(1, 15):
            block = {1: "Amp", 3: "Delay"}.get(slot, "Empty Slot")
            fs |= {f"Scene4_{slot}_Effect": block, f"Scene4_{slot}_Mode": 0, f"Scene4Slot{slot}Preset": "No Preset"}
        fs |= {"Scene4_1_Mode": 1, "Scene4_3_Mode": 2, "Scene4Slot1Preset": "Warm"}
        self.objects = {
            BLOCKS: {"ModuleTypes": ["Empty Slot", "Amp", "Delay"]},
            CHAIN: chain | {"Routing": routing},
            FOOTSWITCH: fs,
            RIGS: {"dirty": False, "loadedName": "Mine", "loadedID": "x", "AllRigNames": ["Mine"]},
            GENERAL: {"TunerFSAssignment": 1, "LooperFSAssignment": 0, "AutoAssignments": True, "OnPressFS": False},
            "/Evil/Gui": {"AppVersion": "1", "DeviceName": "d"},
            "/Evil/Engine/CPUMeter": {"CPUTimeSmoothed": 0.1},
        }
        switch_meta = {}
        for n in range(1, 7):
            switch_meta |= {
                f"ModeNew{n}": {"type": "integer", "minimum": 0, "maximum": 2},
                f"UserFootSwitchText{n}": {"type": "string"},
                f"SceneDoubleSwitch{n}": {"type": "integer", "minimum": 0, "maximum": 2},
                f"ScenePathSwitch{n}": {"type": "integer", "minimum": 0, "maximum": 2},
                f"MacroColour{n}": {"type": "integer", "minimum": 0, "maximum": 13},
                f"State2SceneDoubleSwitch{n}": {"type": "integer", "minimum": 0, "maximum": 2},
                f"State2ScenePathSwitch{n}": {"type": "integer", "minimum": 0, "maximum": 2},
                f"State2MacroColour{n}": {"type": "integer", "minimum": 0, "maximum": 13},
                f"SceneNumberOfStates{n}": {"type": "integer", "minimum": 1, "maximum": 2},
                f"SceneState{n}": {"type": "integer", "minimum": 0, "maximum": 1},
                f"Module{n}": {"type": "string"},
                f"Operation{n}": {"type": "string"},
            }
            for slot in range(1, 15):
                switch_meta |= {
                    f"Scene{n}_{slot}_Mode": {"type": "integer", "minimum": 0, "maximum": 2},
                    f"Scene{n}Slot{slot}Preset": {"type": "string"},
                    f"State2Scene{n}_{slot}_Mode": {"type": "integer", "minimum": 0, "maximum": 2},
                    f"State2Scene{n}Slot{slot}Preset": {"type": "string"},
                }
        self.meta = {
            FOOTSWITCH: switch_meta,
            CHAIN: {k: {"type": "integer", "minimum": 0, "maximum": 300} for k in chain | {"Routing": 0}},
            GENERAL: {
                "TunerFSAssignment": {"x-options": {"strings": ["Tuner", "Bank A/B"]}},
                "LooperFSAssignment": {"x-options": {"strings": ["Looper", "Bank A/B"]}},
            },
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if "/" + path.split("/", 2)[-1] in self.missing:
            return httpx.Response(404, json={"desc": "no such object"})
        if path.startswith("/object-method"):
            self.methods.append(path)
            self.arguments[path.rsplit("/", 1)[-1]] = json.loads(request.content)["arguments"]
            if path.endswith("/blockPresets"):
                return httpx.Response(200, json={"methodReturnValue": ["Warm", "+Factory"]})
            if path.endswith("/createNewSceneState"):
                self.puts_before_create = len(self.puts)
            if path.endswith(("/operationList", "/operationEnableList")):
                arguments = json.loads(request.content)["arguments"]
                module = arguments[1]
                if module in self.operations:
                    which = 0 if path.endswith("/operationList") else 1
                    return httpx.Response(200, json={"methodReturnValue": self.operations[module][which]})
            return httpx.Response(200, json={"methodReturnValue": True})
        if path.startswith("/object-meta"):
            return httpx.Response(200, json={"properties": self.meta.get(path[len("/object-meta") :], {})})
        target = path[len("/object-properties") :]
        if request.method == "PUT":
            body = json.loads(request.content)
            self.puts.append(body)
            kept = {k: v for k, v in body.items() if k not in self.ignore}
            self.objects.setdefault(target, {}).update(kept)
            return httpx.Response(200, json={})
        return httpx.Response(200, json=self.objects.get(target, {}))


def connect(pedal: Pedal, allow_writes: bool = True) -> HeadRushClient:
    return HeadRushClient(host="fake", allow_writes=allow_writes, transport=httpx.MockTransport(pedal))


@pytest.fixture
def pedal(monkeypatch: pytest.MonkeyPatch) -> Pedal:
    instance = Pedal()
    monkeypatch.setattr(server, "client", connect(instance))
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    return instance


def call(tool: str, **args):
    result = asyncio.run(server.mcp.call_tool(tool, args))
    data = result.structured_content
    return data["result"] if set(data) == {"result"} else data


def test_get_scene_returns_the_scene_in_the_shape_set_scene_uses(pedal):
    assert call("get_scene", switch=4) == {
        "switch": 4,
        "name": "LEAD",
        "active": True,
        "blocks": {"Amp": "on", "Delay": "off"},
        "doubling": "B",
        "path": "nochange",
        "presets": {"Amp": "Warm"},
        "color": 3,
        "midi_out": "",
        "states": 1,
    }


def test_get_scene_returns_a_second_state(pedal):
    fs = pedal.objects[FOOTSWITCH]
    fs |= {
        "SceneNumberOfStates4": 2,
        "SceneState4": 1,
        "State2SceneDoubleSwitch4": 1,
        "State2ScenePathSwitch4": 2,
        "State2MacroColour4": 9,
        "State2SceneMIDIOut4": "Lead On",
    }
    for slot in range(1, 15):
        block = {1: "Amp", 3: "Delay"}.get(slot, "Empty Slot")
        fs |= {f"State2Scene4_{slot}_Effect": block, f"State2Scene4_{slot}_Mode": 0, f"State2Scene4Slot{slot}Preset": "No Preset"}
    fs |= {"State2Scene4_1_Mode": 2, "State2Scene4_3_Mode": 1, "State2Scene4Slot3Preset": "Long"}

    scene = call("get_scene", switch=4)

    assert scene["blocks"] == {"Amp": "on", "Delay": "off"}
    assert scene["states"] == 2
    assert scene["current_state"] == 2
    assert scene["second_state"] == {
        "blocks": {"Amp": "off", "Delay": "on"},
        "doubling": "A",
        "path": "B",
        "presets": {"Delay": "Long"},
        "color": 9,
        "midi_out": "Lead On",
    }
    assert pedal.puts == []


def test_get_scene_reports_the_first_state_as_current(pedal):
    pedal.objects[FOOTSWITCH] |= {"SceneNumberOfStates4": 2, "SceneState4": 0}
    assert call("get_scene", switch=4)["current_state"] == 1


def test_get_scene_refuses_a_switch_that_is_not_a_scene(pedal):
    with pytest.raises(ToolError, match="isn't a scene"):
        call("get_scene", switch=1)
    with pytest.raises(ToolError, match="must be 1-6"):
        call("get_scene", switch=9)


def test_set_scene_writes_every_setting_and_reads_it_back(pedal):
    result = call(
        "set_scene",
        switch=2,
        name="CLEAN",
        blocks={"Amp": "on", "Delay": "nochange"},
        doubling="A",
        path="B",
        presets={"Amp": "+Factory"},
        color=5,
    )
    fs = pedal.objects[FOOTSWITCH]
    assert fs["ModeNew2"] == 2
    assert fs["SceneDoubleSwitch2"] == 1
    assert fs["ScenePathSwitch2"] == 2
    assert fs["MacroColour2"] == 5
    assert fs["Scene2Slot1Preset"] == "+Factory"
    assert fs["Scene2_1_Mode"] == 1
    assert fs["Scene2_3_Mode"] == 0
    assert result["mismatches"] == []
    assert result["warnings"] == []


def test_set_scene_leaves_settings_it_was_not_given(pedal):
    result = call("set_scene", switch=4, name="LEAD", doubling="A")
    assert result["scene"]["doubling"] == "A"
    assert result["scene"]["blocks"] == {"Amp": "on", "Delay": "off"}
    assert result["scene"]["presets"] == {"Amp": "Warm"}
    assert result["scene"]["color"] == 3
    written = {key for put in pedal.puts for key in put}
    assert written == {"ModeNew4", "UserFootSwitchText4", "SceneDoubleSwitch4"}


def test_set_scene_can_clear_a_preset(pedal):
    result = call("set_scene", switch=4, name="LEAD", presets={"Amp": "No Preset"})
    assert result["scene"]["presets"] == {}


def test_set_scene_reports_a_write_that_did_not_hold(pedal):
    pedal.ignore = {"SceneDoubleSwitch2"}
    result = call("set_scene", switch=2, name="X", doubling="B")
    assert len(result["mismatches"]) == 1
    assert "SceneDoubleSwitch2" in result["mismatches"][0]


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"doubling": "C"}, "doubling must be"),
        ({"path": "left"}, "path must be"),
        ({"color": 14}, "color must be"),
        ({"blocks": {"Amp": "maybe"}}, "'on', 'off' or 'nochange'"),
        ({"blocks": {"Chorus": "on"}}, "not in the chain"),
        ({"presets": {"Amp": "Nope"}}, "no preset named"),
        ({"presets": {"Chorus": "Warm"}}, "not in the chain"),
    ],
)
def test_set_scene_refuses_bad_values_without_writing(pedal, args, reason):
    with pytest.raises(ToolError, match=reason):
        call("set_scene", switch=2, name="X", **args)
    assert pedal.puts == []


def test_set_scene_needs_writes_enabled(monkeypatch):
    pedal = Pedal()
    monkeypatch.setattr(server, "client", connect(pedal, allow_writes=False))
    with pytest.raises(ToolError, match="Writes are disabled"):
        call("set_scene", switch=2, name="X", doubling="A")
    assert pedal.puts == []


def test_set_scene_warns_when_doubling_and_path_would_do_nothing(monkeypatch):
    monkeypatch.setattr(server, "client", connect(Pedal(doubling=False, routing=0)))
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    warnings = call("set_scene", switch=2, name="X", doubling="A", path="B")["warnings"]
    assert any("'doubling' has no effect" in w for w in warnings)
    assert any("'path' has no effect" in w for w in warnings)


def test_get_footswitches_hides_stale_assignments_on_scene_switches(pedal):
    switches = {entry["switch"]: entry for entry in call("get_footswitches")["switches"]}
    assert "module" not in switches[4]
    assert "operation" not in switches[4]
    assert switches[4]["doubling"] == "B"
    assert switches[4]["scene_active"] is True
    assert switches[1]["module"] == "Amp"
    assert "doubling" not in switches[1]


def test_get_footswitch_settings_names_options_and_never_writes(pedal):
    assert call("get_footswitch_settings") == {
        "tuner_switch": "Bank A/B",
        "looper_switch": "Looper",
        "auto_assign_footswitches": True,
        "on_press": False,
    }
    assert pedal.puts == []


@pytest.mark.parametrize("key", ["SceneMIDIOut1", "State2SceneMIDIOut1", "State2Scene1_1_Effect"])
def test_midi_out_and_scene_contents_stay_unwritable(key):
    client = connect(Pedal())
    with pytest.raises(PolicyError, match="not allowed"):
        client.set_properties(FOOTSWITCH, {key: 1})


def spec_with(**extra) -> dict:
    return {"name": "New", "blocks": [{"slot": 1, "block": "Amp"}], **extra}


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        (spec_with(scenes=[{"name": "A"}]), "footswitches.<number>.scene"),
        (spec_with(tempo=120), "Unknown spec keys: \\['tempo'\\]"),
        ({"name": "New", "blocks": [{"slot": 1, "block": "Amp", "parms": {}}]}, "Unknown block"),
        (spec_with(footswitches={"1": {"module": "Amp", "colour": 1}}), "Unknown footswitch 1 keys"),
        (spec_with(footswitches={"1": {"scene": {"name": "A", "blocks": {}}, "module": "Amp"}}), "Unknown footswitch 1 keys"),
        (spec_with(footswitches={"4": {"scene": {"name": "A", "blocks": {}, "double": "A"}}}), "Unknown scene"),
        (spec_with(footswitches={"4": {"scene": {"name": "A"}}}), "needs 'name' and 'blocks'"),
        (spec_with(footswitches={"4": "Amp"}), "must be an object"),
    ],
)
def test_specs_with_keys_we_would_ignore_are_refused_before_touching_the_pedal(spec, reason):
    pedal = Pedal()
    with pytest.raises(ToolError, match=reason):
        apply_rig(connect(pedal), spec, sleep=lambda _: None)
    assert pedal.puts == [] and pedal.methods == []


def test_comment_keys_are_allowed_and_every_bundled_rig_is_valid():
    _check_spec(spec_with(_notes="why this rig exists"))
    rigs = list((Path(__file__).parent.parent / "rigs").glob("*.json"))
    assert rigs
    for path in rigs:
        _check_spec(json.loads(path.read_text(encoding="utf-8")))


def scene_spec(**scene) -> dict:
    return spec_with(footswitches={"4": {"scene": {"name": "A", "blocks": {"Amp": "on"}, **scene}}})


def test_create_rig_applies_scene_settings():
    pedal = Pedal()
    result = apply_rig(connect(pedal), scene_spec(doubling="B", presets={"Amp": "Warm"}, color=2), sleep=lambda _: None)
    fs = pedal.objects[FOOTSWITCH]
    assert (fs["SceneDoubleSwitch4"], fs["Scene4Slot1Preset"], fs["MacroColour4"]) == (2, "Warm", 2)
    assert result["mismatches"] == [] and result["saved"] is True


def test_create_rig_reports_doubling_that_would_do_nothing():
    result = apply_rig(connect(Pedal(doubling=False)), scene_spec(doubling="A"), sleep=lambda _: None)
    assert any("'doubling' has no effect" in w for w in result["warnings"])


@pytest.mark.parametrize(
    ("scene", "reason"),
    [({"presets": {"Amp": "Nope"}}, "no preset named"), ({"blocks": {"Chorus": "on"}}, "not in the chain")],
)
def test_create_rig_refuses_bad_scenes_before_making_a_new_rig(scene, reason):
    pedal = Pedal()
    with pytest.raises(ToolError, match=reason):
        apply_rig(connect(pedal), scene_spec(**scene), sleep=lambda _: None)
    assert not [m for m in pedal.methods if "makeNewRig" in m]
    assert pedal.puts == []


def test_spec_format_is_available_as_a_tool_and_a_resource():
    text = call("get_rig_spec_format")
    assert "doubling" in text and "footswitches" in text
    contents = asyncio.run(server.mcp.read_resource("headrush://docs/rig-specs"))
    assert "doubling" in str(contents)


def test_get_footswitches_reports_settings_without_warnings_when_both_banks_are_reachable(pedal):
    result = call("get_footswitches")
    assert result["warnings"] == []
    assert result["auto_assign_footswitches"] is True
    assert pedal.puts == []


def test_get_footswitches_warns_when_switches_1_to_3_have_no_way_in(pedal):
    pedal.objects[GENERAL]["TunerFSAssignment"] = 0
    warnings = call("get_footswitches")["warnings"]
    assert len(warnings) == 1
    assert "[1]" in warnings[0] and "Bank A/B" in warnings[0]


@pytest.mark.parametrize("module", ["", "Empty Slot"])
def test_get_footswitches_ignores_an_empty_bank_behind_the_hold(pedal, module):
    pedal.objects[GENERAL]["TunerFSAssignment"] = 0
    pedal.objects[FOOTSWITCH]["Module1"] = module
    assert call("get_footswitches")["warnings"] == []


def test_get_footswitches_skips_the_bank_warning_when_holds_have_no_names(pedal):
    pedal.objects[GENERAL]["TunerFSAssignment"] = 0
    pedal.meta[GENERAL] = {}
    assert call("get_footswitches")["warnings"] == []


def test_get_footswitches_warns_that_on_press_disables_holds(pedal):
    pedal.objects[GENERAL]["OnPressFS"] = True
    warnings = call("get_footswitches")["warnings"]
    assert any("On Press" in w for w in warnings)


@pytest.mark.parametrize(("value", "warns"), [(0, True), (1, False)])
def test_get_footswitches_reads_on_press_by_its_option_name(pedal, value, warns):
    pedal.objects[GENERAL]["OnPressFS"] = value
    pedal.meta[GENERAL]["OnPressFS"] = {"x-options": {"strings": ["On Press", "On Release"]}}
    warnings = call("get_footswitches")["warnings"]
    assert any("On Press" in w for w in warnings) is warns


def test_get_footswitches_reports_unknown_auto_assign_as_null(pedal):
    del pedal.objects[GENERAL]["AutoAssignments"]
    assert call("get_footswitches")["auto_assign_footswitches"] is None


def test_get_footswitches_still_works_when_settings_cannot_be_read(pedal):
    pedal.missing = {GENERAL}
    result = call("get_footswitches")
    assert len(result["switches"]) == 6
    assert result["warnings"] == [] and result["auto_assign_footswitches"] is None


def test_set_slot_block_warns_when_auto_assign_may_take_a_switch(pedal):
    result = call("set_slot_block", slot=2, block="Delay")
    assert {"slot": 2, "block": "Delay"} in result["chain"]
    assert any("Auto Assign Footswitches" in w for w in result["warnings"])
    pedal.objects[GENERAL]["AutoAssignments"] = False
    assert call("set_slot_block", slot=2, block="Amp")["warnings"] == []


def test_set_slot_block_does_not_warn_when_clearing_a_slot(pedal):
    assert call("set_slot_block", slot=3, block="Empty Slot")["warnings"] == []


def test_set_slot_block_keeps_its_result_when_settings_reply_is_not_json(pedal, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(GENERAL):
            return httpx.Response(200, text="busy")
        return pedal(request)

    client = HeadRushClient(host="fake", allow_writes=True, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "client", client)
    result = call("set_slot_block", slot=2, block="Delay")
    assert {"slot": 2, "block": "Delay"} in result["chain"] and result["warnings"] == []


def test_set_slot_block_refuses_a_block_with_no_object(pedal):
    pedal.objects[BLOCKS]["ModuleTypes"].append("ReValver Amp 2")
    pedal.missing = {"/Evil/Engine/Patch/ReValver_Amp_2"}
    with pytest.raises(ToolError, match="ReValver Amp 2.*no object.*crashed"):
        call("set_slot_block", slot=2, block="ReValver Amp 2")
    assert pedal.puts == []


def test_create_rig_refuses_a_block_with_no_object_before_making_a_new_rig():
    pedal = Pedal()
    pedal.objects[BLOCKS]["ModuleTypes"].append("C-Verb 2")
    pedal.missing = {"/Evil/Engine/Patch/C-Verb_2"}
    spec = {"name": "New", "blocks": [{"slot": 1, "block": "Amp"}, {"slot": 2, "block": "C-Verb 2"}]}
    with pytest.raises(ToolError, match="C-Verb 2.*no object"):
        apply_rig(connect(pedal), spec, sleep=lambda _: None)
    assert pedal.methods == [] and pedal.puts == []


def test_create_rig_warns_when_auto_assign_may_take_a_switch():
    pedal = Pedal()
    result = apply_rig(connect(pedal), spec_with(), sleep=lambda _: None)
    assert any("Auto Assign Footswitches" in w for w in result["warnings"])
    pedal.objects[GENERAL]["AutoAssignments"] = False
    result = apply_rig(connect(pedal), spec_with(name="Other"), sleep=lambda _: None)
    assert result["warnings"] == []


def set_second_state(**args):
    return call("set_scene", switch=4, name="LEAD", state=2, **args)


def test_set_scene_adds_a_second_state_the_way_the_editor_does(pedal):
    result = set_second_state(blocks={"Amp": "off", "Delay": "on"}, doubling="A", path="B", color=9, presets={"Delay": "Warm"})

    assert pedal.methods.count("/object-method/Evil/Engine/FootSwitch/createNewSceneState") == 1
    assert pedal.puts_before_create == 0
    assert pedal.arguments["createNewSceneState"] == [3, 0]
    assert any(put.get("UserFootSwitchText4") == "LEAD" for put in pedal.puts)
    assert pedal.puts[0] == {"SceneNumberOfStates4": 2}
    fs = pedal.objects[FOOTSWITCH]
    assert fs["State2Scene4_1_Mode"] == 2 and fs["State2Scene4_3_Mode"] == 1
    assert fs["State2SceneDoubleSwitch4"] == 1 and fs["State2ScenePathSwitch4"] == 2
    assert fs["State2MacroColour4"] == 9 and fs["State2Scene4Slot3Preset"] == "Warm"
    assert result["mismatches"] == []


def test_set_scene_second_state_leaves_the_first_alone(pedal):
    before = dict(pedal.objects[FOOTSWITCH])
    set_second_state(blocks={"Amp": "off"}, color=9)
    fs = pedal.objects[FOOTSWITCH]
    first = [k for k in before if k.startswith(("Scene4", "MacroColour4", "ModeNew4")) and k != "SceneNumberOfStates4"]
    assert {k: fs[k] for k in first} == {k: before[k] for k in first}
    assert not any("ModeNew4" in put for put in pedal.puts)


def test_set_scene_does_not_recreate_an_existing_second_state(pedal):
    pedal.objects[FOOTSWITCH]["SceneNumberOfStates4"] = 2
    set_second_state(color=2)
    assert not [m for m in pedal.methods if m.endswith("createNewSceneState")]
    assert {"SceneNumberOfStates4": 2} not in pedal.puts


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"switch": 1, "state": 2}, "isn't a scene"),
        ({"switch": 4, "state": 3}, "must be 1 or 2"),
        ({"switch": 4, "state": 2, "blocks": {"Amp": "loud"}}, "on.*off"),
        ({"switch": 4, "state": 2, "blocks": {"Chorus": "on"}}, "not in the chain"),
    ],
)
def test_set_scene_second_state_refuses_without_writing(pedal, args, reason):
    with pytest.raises(ToolError, match=reason):
        call("set_scene", name="X", **args)
    assert pedal.puts == [] and not [m for m in pedal.methods if m.endswith("createNewSceneState")]


def test_creating_a_second_state_needs_writes_enabled(monkeypatch):
    instance = Pedal()
    monkeypatch.setattr(server, "client", connect(instance, allow_writes=False))
    with pytest.raises(ToolError, match="disabled"):
        set_second_state(color=2)
    assert instance.methods == []


def test_remove_second_state_uses_the_editors_two_writes(pedal):
    pedal.objects[FOOTSWITCH] |= {"SceneNumberOfStates4": 2, "SceneState4": 1}
    assert call("remove_scene_second_state", switch=4)["states"] == 1
    assert pedal.puts == [{"SceneNumberOfStates4": 1}, {"SceneState4": 0}]


def test_remove_second_state_is_harmless_without_one(pedal):
    assert call("remove_scene_second_state", switch=4)["states"] == 1
    assert pedal.puts == []


def test_remove_second_state_refuses_a_switch_that_is_not_a_scene(pedal):
    with pytest.raises(ToolError, match="isn't a scene"):
        call("remove_scene_second_state", switch=1)


def test_list_footswitch_actions_lists_modules(pedal):
    pedal.objects[FOOTSWITCH]["ModuleList2"] = ["Unassigned", "Amp"]
    assert call("list_footswitch_actions", switch=2) == {"switch": 2, "modules": ["Unassigned", "Amp"]}
    assert pedal.methods == [] and pedal.puts == []


def test_list_footswitch_actions_lists_operations_with_zero_based_switch(pedal):
    pedal.operations["Amp"] = (["On", "Mod"], [True, False])
    result = call("list_footswitch_actions", switch=2, module="Amp")
    assert result["operations"] == [
        {"operation": "On", "enabled": True},
        {"operation": "Mod", "enabled": False},
    ]
    assert pedal.arguments["operationList"] == [1, "Amp"]
    assert pedal.arguments["operationEnableList"] == [1, "Amp"]
    assert pedal.puts == []


def test_list_footswitch_actions_handles_the_empty_enable_list(pedal):
    pedal.operations["Unassigned"] = ([""], [])
    result = call("list_footswitch_actions", switch=2, module="Unassigned")
    assert result["operations"] == [{"operation": "", "enabled": True}]


def test_set_footswitch_can_clear_a_switch_with_the_default_operation(pedal):
    pedal.operations["Unassigned"] = ([""], [])
    call("set_footswitch", switch=1, module="Unassigned")
    assert pedal.objects[FOOTSWITCH]["Module1"] == "Unassigned"
    assert pedal.objects[FOOTSWITCH]["Operation1"] == ""


def test_create_rig_refuses_midi_out_before_touching_the_pedal():
    instance = Pedal()
    bad = {"name": "New", "blocks": [{"slot": 1, "block": "Amp"}], "footswitches": {"1": {"module": "MIDI Out"}}}
    with pytest.raises(ToolError, match="MIDI Out"):
        apply_rig(connect(instance), bad, sleep=lambda _: None)
    assert instance.puts == [] and instance.methods == []


def test_create_rig_clears_a_switch_with_an_empty_operation():
    instance = Pedal()
    spec = {"name": "New", "blocks": [{"slot": 1, "block": "Amp"}], "footswitches": {"1": {"module": "Unassigned"}}}
    apply_rig(connect(instance), spec, sleep=lambda _: None)
    assert instance.objects[FOOTSWITCH]["Operation1"] == ""


def test_an_unassigned_switch_behind_the_hold_is_not_called_unreachable(pedal):
    pedal.objects[GENERAL] |= {"TunerFSAssignment": 0, "LooperFSAssignment": 0}
    pedal.objects[FOOTSWITCH]["Module1"] = "Unassigned"
    assert call("get_footswitches")["warnings"] == []


def test_midi_out_is_not_offered_or_assignable(pedal):
    pedal.operations["MIDI Out"] = (["New/Edit..."], [True])
    assert call("list_footswitch_actions", switch=1, module="MIDI Out")["operations"] == []
    with pytest.raises(ToolError, match="MIDI Out"):
        call("set_footswitch", switch=1, module="MIDI Out", operation="New/Edit...")
    assert pedal.puts == []


def test_list_footswitch_actions_works_with_writes_off(monkeypatch):
    instance = Pedal()
    instance.operations["Amp"] = (["On"], [True])
    monkeypatch.setattr(server, "client", connect(instance, allow_writes=False))
    assert call("list_footswitch_actions", switch=1, module="Amp")["operations"][0]["enabled"]


def test_list_footswitch_actions_refuses_a_bad_switch(pedal):
    with pytest.raises(ToolError, match="1-6"):
        call("list_footswitch_actions", switch=7)


@pytest.mark.parametrize("operation", ["Nope", "Mod"])
def test_set_footswitch_refuses_an_operation_the_pedal_does_not_offer(pedal, operation):
    pedal.operations["Amp"] = (["On", "Mod"], [True, False])
    with pytest.raises(ToolError, match="Options:.*On"):
        call("set_footswitch", switch=2, module="Amp", operation=operation)
    assert pedal.puts == []


def test_set_footswitch_accepts_an_offered_operation(pedal):
    pedal.operations["Amp"] = (["On", "Mod"], [True, True])
    call("set_footswitch", switch=1, module="Amp", operation="Mod")
    assert pedal.objects[FOOTSWITCH]["Operation1"] == "Mod"


def test_set_footswitch_still_works_without_the_operation_list(pedal):
    pedal.missing.add("/Evil/Engine/FootSwitch/operationList")
    call("set_footswitch", switch=1, module="Amp", operation="On")
    assert pedal.objects[FOOTSWITCH]["Module1"] == "Amp"
