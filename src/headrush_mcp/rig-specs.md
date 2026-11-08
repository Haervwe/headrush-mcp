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
| `ParaDelay` | -30000 to +30000 µs | `0.5` is no delay. Negative delays path A, positive delays path B |
| `ParaXFade` | -100 to +100 | `0.5` is an even blend |

See [`rigs/stern-stereo-test.json`](../../rigs/stern-stereo-test.json) for a full example. The `Amp` and `Cab` blocks can also double in place using their `Doubling` and `DoubleMode` parameters, but `create_rig` hasn't been tested with that. Stereo doubling runs both sides. Switch doubling (`DoubleMode` true) runs one, and the guide only offers a footswitch assigned to `Doubling: A <Switch> B`, or a scene's `doubling`, to change it (User Guide p.11, p.32). Without one, the rig probably stays on one side.

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

`set_scene` takes the same fields, and `get_scene` returns them. With `set_scene`, `blocks` is optional, and anything you leave out keeps its current value, so you can change just `doubling`. A scene's second switch state and MIDI out can't be set here, so do those on the pedal. `get_scene` shows a second state under `second_state`, with the same fields.

Switches 1-3 and 4-6 are separate banks, and each switch has its own scene. Two switches with the same label can still behave differently, so check both. Switches 4-6 can only be reached if the user has set a hold to Bank A/B in Global Settings, and `get_footswitches` warns if not. When switches 4-6 can't be reached, put what matters on 1-3.

If Auto Assign Footswitches is on, the pedal gives each new block the next free switch, and `create_rig` warns when that may happen. Assign every switch you care about in the spec.

## File and block limits

From the [User Guide](https://cdn.inmusicbrands.com/Software/SGEE/52/HeadRush%20Flex%20Prime%20-%20User%20Guide%20-%20v5.2.0.pdf), firmware 5.2:

- **C-Verb:** one per rig. Files are usually WAV, AIF or OPUS, up to 10 seconds, and only the first two channels are used (p.24).
- **IR:** cabinet IRs are usually WAV files. `IR (1024)` truncates them to 1024 samples to save DSP (p.24).
- **NAM:** up to two A2 captures at Full quality per rig, as two blocks or one doubled block. Up to four A2 Lite, by doubling two blocks. Only one A1 capture. Captures are forced to Lite with more than two loaded, or with a stereo effect before two NAM blocks (p.23).
- **Tails:** with any NAM block in the rig, reverb and delay tails stop when switching rigs (p.23).
- **Clones:** files end in `.ac` (amp and pedal clones) or `.sc` (SuperClones).
- **Second instances:** only use blocks that `describe_block` can read. `create_rig` and `set_slot_block` refuse ones the pedal lists without an object, like `ReValver Amp 2`.

Values are reported to be snapped to each parameter's step size (community, Core), so `create_rig` accepts a read-back within one step.

## If a build fails

`create_rig` retries writes that don't hold, then reports `mismatches` without saving. The unnamed draft stays loaded. Retry with `resume_draft: true`, or discard it on the pedal.
