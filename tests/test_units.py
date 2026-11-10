"""Real-unit values, checked against the official editor's curves."""

import asyncio
import json

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
    block_path,
)
from headrush_mcp.rigs import _wire_step, apply_rig, to_display, to_wire


def number(low, high, fmt="%.1f dB", algo=None, grid=0.1):
    options = {"format": fmt, "grid": grid}
    if algo is not None:
        options["normalizeAlgo"] = algo
    return {"type": "number", "minimum": low, "maximum": high, "x-options": options}


LINEAR = number(-12.0, 12.0)
SQUARED = number(0.25, 20.0, "%.2f Hz", 5, 0.01)
EXPONENTIAL = number(20.0, 16000.0, "%.0f Hz", 6, 1.0)
REVERB = number(0.45, 144.0, "%.1f sec", 10)
REVERSED = number(3.0, -3.0, "%.1f inches")


@pytest.mark.parametrize(
    ("schema", "stored", "shown"),
    [
        (LINEAR, 0.5, "0.0 dB"),
        (LINEAR, 0.0, "-12.0 dB"),
        (SQUARED, 0.5, "5.19 Hz"),
        (EXPONENTIAL, 1.0, "16000 Hz"),
        (EXPONENTIAL, 0.5, "566 Hz"),
        (REVERB, 0.0, "0.5 sec"),
        (REVERB, 0.5, "1.9 sec"),
        (REVERB, 0.995, "Inf"),
        (REVERSED, 0.0, "3.0 inches"),
    ],
)
def test_to_display_matches_what_the_editor_shows(schema, stored, shown):
    assert to_display(schema, stored) == shown


@pytest.mark.parametrize(
    ("schema", "display", "stored"),
    [
        (LINEAR, -6, 0.25),
        (LINEAR, 12, 1.0),
        (SQUARED, 0.25, 0.0),
        (EXPONENTIAL, 20, 0.0),
        (EXPONENTIAL, 16000, 1.0),
        (REVERB, 0.45, 0.0),
        (REVERB, 144, 0.99),
        (REVERSED, 3, 0.0),
        (REVERSED, -3, 1.0),
    ],
)
def test_to_wire_inverts_the_curves(schema, display, stored):
    assert to_wire("/o", "k", display, schema) == pytest.approx(stored)


def test_infinite_reverb_is_the_top_of_the_knob():
    assert to_wire("/o", "k", "Inf", REVERB) == 1.0
    assert to_wire("/o", "k", "inf", REVERB) == 1.0


def test_to_wire_always_returns_a_float_so_read_backs_get_the_tolerance():
    assert isinstance(to_wire("/o", "k", 12, LINEAR), float)


def test_a_value_at_a_32_bit_limit_is_accepted():
    schema = number(3.200000047683716, 17.0, "%.1f kHz")
    assert to_wire("/o", "k", 3.2, schema) == 0.0


@pytest.mark.parametrize(
    ("schema", "value", "reason"),
    [
        (LINEAR, 13, "between -12 and 12"),
        (LINEAR, -13, "between -12 and 12"),
        (REVERSED, 4, "between -3 and 3"),
        (LINEAR, "loud", "expected a number"),
        (LINEAR, True, "expected a number"),
        (LINEAR, "Inf", "expected a number"),
        (number(0.0, 1.0, algo=2), 0.5, "0-1 value"),
        (number(1.0, 1.0), 1.0, "0-1 value"),
        (number(0.0, 100.0, algo=6), 50, "0-1 value"),
    ],
)
def test_to_wire_refuses_what_it_cannot_convert(schema, value, reason):
    with pytest.raises(PolicyError, match=reason):
        to_wire("/o", "k", value, schema)


def test_an_unknown_curve_stays_normalized_when_read():
    assert to_display(number(0.0, 1.0, algo=2), 0.5) == 0.5


def test_an_invalid_firmware_format_still_shows_the_number():
    assert to_display(number(-50.0, 50.0, "%.0f %"), 0.75) == "25"


def test_options_read_and_write_by_name():
    schema = {"type": "integer", "minimum": 0, "maximum": 1, "x-options": {"strings": ["Clean", "Lead"]}}
    assert to_display(schema, 1) == "Lead"
    assert to_wire("/o", "k", "Lead", schema) == 1


def test_a_number_means_an_option_name_not_an_index():
    schema = {"type": "integer", "x-options": {"strings": ["1", "2", "3"]}}
    assert to_display(schema, 1) == "2"
    assert to_wire("/o", "k", 2, schema) == 1
    assert to_wire("/o", "k", "2", schema) == 1


@pytest.mark.parametrize("value", [0, 5, 2.0])
def test_a_number_that_is_not_an_option_name_is_refused(value):
    schema = {"type": "integer", "x-options": {"strings": ["1", "2", "3"]}}
    with pytest.raises(PolicyError, match="isn't an option"):
        to_wire("/o", "k", value, schema)


def test_an_index_for_named_options_is_refused_in_display_mode():
    schema = {"type": "integer", "x-options": {"strings": ["Clean", "Lead"]}}
    with pytest.raises(PolicyError, match="isn't an option"):
        to_wire("/o", "k", 1, schema)


def test_an_integer_without_names_passes_through():
    assert to_wire("/o", "k", 3, {"type": "integer", "minimum": 0, "maximum": 5}) == 3


def test_booleans_read_and_write_by_name():
    schema = {"type": "boolean", "x-options": {"strings": ["Stereo", "Switch"]}}
    assert to_display(schema, True) == "Switch"
    assert to_display(schema, False) == "Stereo"
    assert to_wire("/o", "k", "Switch", schema) is True
    assert to_wire("/o", "k", "Stereo", schema) is False
    assert to_wire("/o", "k", True, schema) is True


def test_a_boolean_whose_first_name_is_on_is_not_inverted():
    schema = {"type": "boolean", "x-options": {"strings": ["On", "Off"]}}
    assert to_display(schema, False) == "On"
    assert to_wire("/o", "k", "Off", schema) is True


def test_a_wrong_boolean_name_is_refused():
    schema = {"type": "boolean", "x-options": {"strings": ["Stereo", "Switch"]}}
    with pytest.raises(PolicyError, match="isn't an option"):
        to_wire("/o", "k", "Mono", schema)


def test_the_longest_finite_reverb_is_not_shown_as_infinite():
    stored_as_float32 = 0.9900000095367432
    assert to_display(REVERB, stored_as_float32) == "144.0 sec"
    assert to_display(REVERB, to_wire("/o", "k", 144, REVERB)) == "144.0 sec"
    assert to_display(REVERB, 0.9900001) == "Inf"


@pytest.mark.parametrize(
    ("schema", "wanted"),
    [(REVERB, 0.5697), (REVERSED, 0.2917)],
)
def test_read_backs_allow_a_grid_step_on_every_curve(schema, wanted):
    step = _wire_step(schema, wanted)
    assert step is not None and step > 0.002


def test_a_reverb_at_infinite_has_no_step():
    assert _wire_step(REVERB, 1.0) is None


@pytest.mark.parametrize("names", [["Clean"], ["Lead", "Lead"]])
def test_a_missing_or_ambiguous_option_is_refused(names):
    schema = {"type": "integer", "x-options": {"strings": names}}
    with pytest.raises(PolicyError, match="isn't an option"):
        to_wire("/o", "k", "Lead", schema)


def test_booleans_and_strings_pass_through():
    assert to_wire("/o", "k", True, {"type": "boolean"}) is True
    assert to_display({"type": "string"}, "x") == "x"


AMP = block_path("Amp")
MIX = block_path("Mix")


class Pedal:
    def __init__(self):
        self.puts = []
        self.methods = []
        chain = {f"ModuleType{n}": 0 for n in range(1, 15)} | {"ModuleType1": 1, "Routing": 1}
        self.objects = {
            BLOCKS: {"ModuleTypes": ["Empty Slot", "Amp"]},
            CHAIN: chain,
            FOOTSWITCH: {},
            RIGS: {"dirty": False, "loadedName": "Mine", "loadedID": "x", "AllRigNames": ["Mine"]},
            AMP: {"PreGain": 0.5, "Rate": 1.0, "On": True, "Type": 1},
            MIX: {"Para1Level": 0.75},
            "/Evil/Gui": {"AppVersion": "1", "DeviceName": "d"},
            "/Evil/Engine/CPUMeter": {"CPUTimeSmoothed": 0.1},
        }
        self.meta = {
            AMP: {
                "PreGain": LINEAR,
                "Rate": EXPONENTIAL,
                "On": {"type": "boolean"},
                "Type": {"type": "integer", "minimum": 0, "maximum": 1, "x-options": {"strings": ["Clean", "Lead"]}},
            },
            MIX: {"Para1Level": number(-60.0, 12.0)},
            CHAIN: {k: {"type": "integer", "minimum": 0, "maximum": 300} for k in chain},
        }

    def __call__(self, request):
        path = request.url.path.removeprefix("/api/v1")
        if path.startswith("/object-method"):
            self.methods.append(path)
            if path.endswith("/saveRigAs"):
                self.objects[RIGS]["AllRigNames"].append(json.loads(request.content)["arguments"][0])
            return httpx.Response(200, json={"methodReturnValue": True})
        if path.startswith("/object-meta"):
            return httpx.Response(200, json={"properties": self.meta.get(path[len("/object-meta") :], {})})
        target = path[len("/object-properties") :]
        if request.method == "PUT":
            body = json.loads(request.content)
            self.puts.append(body)
            self.objects.setdefault(target, {}).update(body)
            return httpx.Response(200, json={})
        return httpx.Response(200, json=self.objects.get(target, {}))


@pytest.fixture
def pedal(monkeypatch):
    instance = Pedal()
    client = HeadRushClient(host="fake", allow_writes=True, transport=httpx.MockTransport(instance))
    monkeypatch.setattr(server, "client", client)
    return instance


def call(tool, **args):
    result = asyncio.run(server.mcp.call_tool(tool, args))
    data = result.structured_content
    return data["result"] if set(data) == {"result"} else data


def test_get_block_stays_normalized_by_default(pedal):
    assert call("get_block", block="Amp")["PreGain"] == 0.5


def test_get_block_can_read_displayed_values(pedal):
    assert call("get_block", block="Amp", display=True) == {
        "PreGain": "0.0 dB",
        "Rate": "16000 Hz",
        "On": True,
        "Type": "Lead",
    }


def test_set_block_params_writes_displayed_units_and_reads_them_back(pedal):
    pedal.meta[AMP]["Stereo"] = {"type": "boolean", "x-options": {"strings": ["Off", "On"]}}
    pedal.objects[AMP]["Stereo"] = False
    assert call("set_block_params", block="Amp", values={"Stereo": "On"}, display=True) == {"Stereo": "On"}
    assert pedal.objects[AMP]["Stereo"] is True
    pedal.puts.clear()
    result = call("set_block_params", block="Amp", values={"PreGain": -6, "Type": "Clean"}, display=True)
    assert pedal.puts == [{"PreGain": 0.25, "Type": 0}]
    assert result == {"PreGain": "-6.0 dB", "Type": "Clean"}


def test_set_block_params_refuses_out_of_range_without_writing(pedal):
    with pytest.raises(ToolError, match="between"):
        call("set_block_params", block="Amp", values={"PreGain": 40}, display=True)
    assert pedal.puts == []


def test_set_block_params_keeps_normalized_values_by_default(pedal):
    assert call("set_block_params", block="Amp", values={"PreGain": 0.25}) == {"PreGain": 0.25}
    assert pedal.puts == [{"PreGain": 0.25}]


def test_set_mix_takes_displayed_units(pedal):
    assert call("set_mix", values={"Para1Level": -6}, display=True) == {"Para1Level": "-6.0 dB"}
    assert pedal.puts[0]["Para1Level"] == pytest.approx(0.75)


def spec(**extra):
    return {"name": "New", "blocks": [{"slot": 1, "block": "Amp", **extra}]}


def test_create_rig_converts_displayed_units(pedal):
    client = server.client
    result = apply_rig(client, spec(params={"On": False}, display_params={"PreGain": -6}), sleep=lambda _: None)
    assert result["mismatches"] == [] and result["saved"]
    assert pedal.objects[AMP]["PreGain"] == pytest.approx(0.25)
    assert pedal.objects[AMP]["On"] is False


def test_create_rig_converts_a_displayed_mix(pedal):
    apply_rig(server.client, {**spec(), "display_mix": {"Para1Level": -12}}, sleep=lambda _: None)
    assert pedal.objects[MIX]["Para1Level"] == pytest.approx(48 / 72)


@pytest.mark.parametrize("routing", ["x", 999])
def test_create_rig_refuses_a_bad_routing_before_touching_the_pedal(pedal, routing):
    with pytest.raises(PolicyError, match="Routing"):
        apply_rig(server.client, {**spec(), "routing": routing}, sleep=lambda _: None)
    assert pedal.puts == [] and pedal.methods == []


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ({"params": {"PreGain": 0.5}, "display_params": {"PreGain": 0}}, "once"),
        ({"display_params": {"PreGain": 99}}, "between"),
        ({"display_params": {"Type": 9999}}, "isn't an option"),
        ({"display_params": {"Nope": 1}}, "Unknown property"),
        ({"params": {"Type": 9999}}, "Invalid value"),
        ({"params": {"Nope": 1}}, "Unknown property"),
    ],
)
def test_create_rig_refuses_bad_displayed_values_before_touching_the_pedal(pedal, entry, reason):
    with pytest.raises(Exception, match=reason):
        apply_rig(server.client, spec(**entry), sleep=lambda _: None)
    assert pedal.puts == [] and pedal.methods == []


def test_load_rig_is_refused_after_an_edit_through_the_server(pedal):
    asyncio.run(server.mcp.call_tool("set_block_params", {"block": "Amp", "values": {"PreGain": 0.4}}))
    with pytest.raises(ToolError, match="made through this server"):
        asyncio.run(server.mcp.call_tool("load_rig", {"rig_id": "other"}))
    assert not any(m.endswith("loadRigConfirm") for m in pedal.methods)
