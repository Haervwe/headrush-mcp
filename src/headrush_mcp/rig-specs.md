# Rig specs

`create_rig` builds a new rig from a JSON spec. Empty slots are cleared, so list everything you want. Unknown keys are refused, except comments that start with `_`.

```json
{
  "name": "My Rig",
  "routing": 0,
  "blocks": [
    { "slot": 1, "block": "S1 Drive", "params": { "On": false, "Drive": 0.35 } },
    { "slot": 2, "block": "Amp", "params": { "Type": 15, "GainA": 0.3 } },
    { "slot": 3, "block": "Cab", "params": { "CabType": 5 } }
  ],
  "footswitches": {
    "1": { "module": "S1 Drive" },
    "4": { "scene": { "name": "LEAD", "blocks": { "S1 Drive": "on" } } }
  }
}
```

| Field | Required | Meaning |
|---|---|---|
| `name` | Yes | A rig name not already on the pedal |
| `routing` | No | Routing number, default `0` |
| `mix` | No | Parallel path settings |
| `blocks` | Yes | Blocks by `slot` (1-14), with optional `params` |
| `footswitches` | No | By switch number (1-6) |

Parameter names and option indexes vary by block, so use `describe_block` to find them. For example, `Type` on `Amp` is an index into its list of models. Numbers are normalized 0-1, and the [API reference](../../docs/api.md) explains converting them.

## Routings

| `routing` | Name | Before split | Path A | Path B | After mix |
|---|---|---|---|---|---|
| 0 | Straight Path | 1-14 | | | |
| 1 | Middle Split 3-4-3 | 1-3 | 4-7 | 8-11 | 12-14 |
| 2 | Middle Split 5-3-3 | 1-5 | 6-8 | 9-11 | 12-14 |
| 3 | Middle Split 7-2-3 | 1-7 | 8-9 | 10-11 | 12-14 |
| 4 | Immediate Split | | 1-5 | 6-10 | 11-14 |

Routings 0 and 1 have been played through. Routings 2-4 are accepted by the pedal, but their slot layouts come from the editor's code and haven't been checked by ear.

## Two amps

Use a split routing, with `Amp` and `Cab` on path A and `Amp 2` and `Cab 2` on path B. `mix` sets how they combine:

| Key | Display range | Example |
|---|---|---|
| `Para1Level`, `Para2Level` | -60 to +12 dB | `0.75` is -6 dB |
| `Para1Pan`, `Para2Pan` | -100 to +100 | `0` is hard left, `1` hard right |
| `ParaDelay` | -30000 to +30000 µs | `0.5` is no delay |
| `ParaXFade` | -100 to +100 | `0.5` is an even blend |

See [`rigs/stern-stereo-test.json`](../../rigs/stern-stereo-test.json) for a full example. The `Amp` and `Cab` blocks can also double in place using their `Doubling` and `DoubleMode` parameters, but `create_rig` hasn't been tested with that.

Check the sound in mono if you pan hard, as it depends on how your output is connected.

## Footswitches

**Toggle** a block:

```json
{ "module": "S1 Drive", "operation": "On", "name": "" }
```

`operation` defaults to `On`. `name` overrides the label shown on the pedal. `mode` can be `1` for hold, which hasn't been tested.

**Scene:** sets several things at once with one press.

```json
{
  "scene": {
    "name": "SOLO",
    "blocks": { "S1 Drive": "on", "AIR Delay 2": "off", "Chorus": "nochange" },
    "doubling": "B",
    "path": "nochange",
    "presets": { "S1 Drive": "My Lead" },
    "color": 5
  }
}
```

| Field | Required | Meaning |
|---|---|---|
| `name` | Yes | The label on the pedal |
| `blocks` | Yes in a spec | Blocks in the chain as `on`, `off` or `nochange`. Blocks you don't list become `nochange` |
| `doubling` | No | `A`, `B` or `nochange`, for blocks with `Doubling` on and `DoubleMode` set to Switch |
| `path` | No | `A`, `B` or `nochange`, for split routings |
| `presets` | No | A block preset to recall, from `list_block_presets`. `No Preset` clears one |
| `color` | No | The scene's color, 0-13. The editor shows color 1 onward, and names for the numbers haven't been mapped |

`create_rig` adds a `warnings` list if `doubling` or `path` would do nothing on that rig.

Scene names display in capitals on the official editor, so use capitals for consistency.

`set_scene` takes the same fields, and `get_scene` returns them. With `set_scene`, `blocks` is optional, and anything you leave out keeps its current value, so you can change just `doubling`. A scene's second switch state and MIDI out can't be set here. Do those on the pedal.

Switches 1-3 and 4-6 are separate banks, and each switch has its own scene. Two switches with the same label can still behave differently, so check both.

## If a build fails

`create_rig` retries writes that don't hold, then reports `mismatches` without saving. The unnamed draft stays loaded. Retry with `resume_draft: true`, or discard it on the pedal.
