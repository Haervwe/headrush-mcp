# HeadRush Remote Editor API

Unofficial notes from observing the editor on a Flex Prime, firmware `5.2.0.2a405ee`. They're worked out from traffic and the editor's JavaScript, so anything here may change with firmware.

## Basics

- **Base URL:** `http://<host>/api/v1`, plain HTTP. The default host is `headrushflexprime.local`.
- **Auth:** none was needed on the tested pedal. The guide describes Authorize with PIN as something you turn on, so it's probably off by default. Firmware 5.0.0 added an opt-in **Authorize with PIN** setting under Global Settings > HeadRush Remote: the pedal and the editor show a PIN, and the connection is approved on the pedal's screen (User Guide p.61). The editor contains a pairing flow (`POST /api/auth`) that handles a 401. See [Auth and errors](#auth-and-errors).
- **CORS:** none, so browser pages on other origins can't use the API. Server-side clients are unaffected.
- **mDNS:** the hostname may resolve to an IPv6 link-local address first, so some clients do better with the IPv4 address.

## Endpoints

`<path>` is an object path such as `/Evil/API/Rigs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/subtree` | Full state and schema, about 1 MB and 290 objects |
| GET | `/subtree<path>` | The same, for one object |
| GET | `/object-properties<path>` | Read an object |
| PUT | `/object-properties<path>` | Write properties, with a JSON body of properties |
| GET | `/object-meta<path>` | Read an object's schema |
| POST | `/object-method<path>/<method>` | Call a method: request `{"arguments":[...]}`, response `{"methodReturnValue":...}` |
| GET | `/files/...` (not under `/api/v1`) | Static files such as block images |

**A POST isn't necessarily a write, and the method name is the only hint.** Calling a method with the wrong argument order returned a 504 in testing.

## Auth and errors

| Status | Meaning |
|---|---|
| 401 | Authorize with PIN is on and this client isn't paired. The editor reads `pairState`, `pairPin` and `pairError` from the body |
| 403 | HeadRush Remote is off. The body has a `desc` field, `DataModel: Web access temporarily disabled`. Seen on a Core at 5.1.0, where `/subtree` returned 404 instead (community, [ToneCommand](https://github.com/monzta1/ToneCommand/blob/main/docs/HEADRUSH-HARDWARE-FINDINGS.md)) |
| 504 | A method call with the wrong arguments |

Setting **New Connection Attempts** to **Deny** makes the pedal reject new connection attempts (User Guide p.61). That probably shows up as a connection failure rather than an HTTP error (untested).

Going by the editor's JavaScript, on a 401 whose `pairState` is `notPaired`, it sends `POST /api/auth` with `{}` and shows the returned `pairPin` while `pairState` is `pending`. A `pairError` of `denied`, `blocked` or `disabled` stops it. This wasn't exercised, since the tested pedal has the PIN off.

Community clients differ: [RushLink](https://github.com/Rush-Link/RushLink-App/blob/main/src-tauri/src/lib.rs) posts `{"pin": ...}` instead, and [rigsmith](https://github.com/Gavinboley/rigsmith/blob/HEAD/rigsmith/device/client.py) polls an empty POST and keeps a `sessionID` cookie, on a Core.

This server doesn't pair. It reports a 401 and leaves approval to the user.

## Live updates

After `GET /subtree`, the editor opens `ws://<host>/`. It sends nothing on the socket, and the pedal pushes changes:

```json
{"notification":"propertyValueChanged","objectPath":"/Evil/Engine/CPUMeter","propertyName":"CPUTimeSmoothed","propertyValue":0.275}
```

- `CPUTimeSmoothed` arrives about every 0.83 s, acting as a heartbeat. The editor disconnects after 5 s of silence, which is its own rule.
- Rig changes can burst: 3000 frames in about 0.8 s was observed.
- The editor handles `objectAdded`, `objectRemoved`, `objectPropertyAdded`, `objectPropertyRemoved`, `propertyValueChanged` and `webAccessChanged`. Only `propertyValueChanged` was seen on the wire.

This server doesn't use the WebSocket yet, and non-browser clients haven't been tested.

## Parameter values

Numbers are normalized 0-1 on the wire, whatever range the schema shows. `get_block`, `set_block_params` and `set_mix` convert for you with `display=true`, and rig specs with `display_params` and `display_mix`. They support the four curves below and refuse any other. To convert a linear parameter yourself:

```text
normalized = (display - minimum) / (maximum - minimum)
```

For example, on `AIR Delay.Delay` (1-4000 ms), 381 ms is `(381 - 1) / 3999 = 0.095`.

A parameter with `x-options.normalizeAlgo` in its schema uses a curve instead. These are the editor's formulas, where `v` is the 0-1 value:

| `normalizeAlgo` | Curve | Display value |
|---|---|---|
| none or `0` | Linear | `minimum + (maximum - minimum) * v` |
| `5` | Squared | `minimum + (maximum - minimum) * v * v` |
| `6` | Exponential | `minimum * (maximum / minimum) ** v` |
| `10` | Reverb time | `(0.45 + v) / (1 - v)`, and infinite above 0.99 |

Those are the only ids on firmware `5.2.0.2a405ee`, with `6` on most frequency and rate parameters, like `Multi Chorus.Rate`, and `10` on `AIR Reverb.Time`. The editor also defines ids 1-4 and 7-9.

`x-options.grid` is the step size **in displayed units**, like 1 for a 0-100 knob or 0.1 for a dB value, so convert it through the curve before comparing 0-1 values. The pedal is reported to snap written values to the grid and not to clamp out-of-range values (community, tested on a Core: ToneCommand; not tested here). Compare read-backs within one grid step, not as exact floats.

Integers such as `Amp.Type` are indexes into `x-options.strings` in the schema, and aren't normalized. In `display` mode they go by name, and a number is read as a name, because some names are digits: on `Jimmy OD.SoftClip`, `2` is the second option, index 1. Booleans can have two names as well, like `Amp.DoubleMode`, where false is `Stereo` and true is `Switch`.

The editor renames two mic options on the `8x10 Blue Line` cab, showing `Dyn 409` as `Dyn 20` and `Cond 87` as `Dyn 12`. `display` mode uses the schema's names, `Dyn 409` and `Cond 87`, for every cab.

## Key objects

| Object | Contents |
|---|---|
| `/Evil/Gui` | `AppVersion`, `DeviceName` |
| `/Evil/API/Rigs` | Rig lists, `loadedID`, `loadedName`, `dirty` |
| `/Evil/API/Setlists` | Setlist lists |
| `/Evil/API/Blocks` | `ModuleTypes`, the names indexed by `ModuleType#` |
| `/Evil/API/FileAccess` | The `ls` method for browsing installed files |
| `/Evil/Engine/Patch/Chain` | `ModuleType1-14`, `Routing` |
| `/Evil/Engine/Patch/Mix` | Parallel path level, pan, delay and crossfade |
| `/Evil/Engine/Patch/<block>` | Block parameters; spaces become underscores |
| `/Evil/Engine/FootSwitch` | Footswitches and scenes |
| `/Evil/Engine/CPUMeter` | `CPUTimeSmoothed` |

`ModuleTypes` lists `ReValver Amp 2` and `C-Verb 2`, but neither has an object on firmware `5.2.0.2a405ee`, so reading them returns a 404. **Don't write a module type that has no object.** On a Core at 5.1.0, writing one crashed the audio engine once, and others reverted or stuck as an empty slot (community, ToneCommand). `Neural Amp Modeler 2` has an object on 5.2, with its own second-capture fields like `LoadedClone2`, `LightMode2` and `OutputMode2`. It reportedly had none before 5.2 (community, ToneCommand). Check the `/Evil/Engine/Patch/<Name>` object exists before placing a block, with object-meta or the live subtree; the server's `require_block_object` uses object-meta and treats a 404 as missing. Other names can contain apostrophes and parentheses, like `Sher'ff` and `IR (1024)`, which stay as they are in the path.

## Installed models and files

What's installed differs per pedal, because ReValver models, clones, NAM captures and IRs can be downloaded.

**Options:** model lists are in the schema, like `x-options.strings` on `Amp.Type` and `ReValver Amp.Type`. An option's index can differ between pedals, so read it rather than storing it.

**Files:** a file parameter's schema gives its root and type in `x-options`, as `startPath` and `fileType`. `POST .../Evil/API/FileAccess/ls` with `[folder, fileType]` returns the file names directly in that folder, and type `0` returns its subfolders. The editor's file pickers use this call, and files usually sit in subfolders.

| `fileType` | Root | Parameter | Blocks |
|---|---|---|---|
| `2` | `Impulse Responses` | `IR` | `IR`, `IR (1024)` |
| `7` | `Amp Clones` | `LoadedClone` | `Amp Clone`, `Pedal Clone` |
| `8` | `SuperClones` | `LoadedClone` | `SuperClone` |
| `9` | `Neural Amp Modeler` | `LoadedClone` | `Neural Amp Modeler` |
| `12` | `Reverbs` | `ReverbFile` | `C-Verb` |

Going by the editor's JavaScript, a chosen file's value is its path from the root folder, like `Neural Amp Modeler/Tone 3000/Name.nam`. This server hasn't tested writing one yet.

The editor saves Tone3000 downloads to `Neural Amp Modeler/Tone 3000`, and HeadRush Cloud clones to `Amp Clones/HeadRush Cloud` or `SuperClones/HeadRush Cloud`. Clone files end in `.ac` (amp and pedal clones) or `.sc` (SuperClones). Per-rig file limits are in the [rig spec format](../src/headrush_mcp/rig-specs.md#file-and-block-limits).

`/Evil/API/Blocks/categoryOfBlock` returns a block's category, or an empty string for second instances and a few others.

## Building a rig

The editor does this with plain property writes:

1. `POST .../Evil/API/Rigs/makeNewRigConfirm` with `[-1]`.
2. `PUT` `ModuleType<slot>` on `Chain`, with the block's index in `ModuleTypes`.
3. `PUT` parameters on each block.
4. `POST .../Evil/API/Rigs/saveRigAs` with `[name, -1]`.

**Timing matters:** creating a rig and placing a block both finish asynchronously. Early slot writes can be cleared, and new blocks reset their parameters to defaults, so verify after a settle period and rewrite what didn't stick.

## Footswitches and scenes

Keys on `/Evil/Engine/FootSwitch`, for switch `n` from 1 to 6:

| Key | Meaning |
|---|---|
| `ModeNew<n>` | `0` toggle, `1` hold, `2` scene |
| `Module<n>`, `Operation<n>` | Block and action, for toggle and hold |
| `UserFootSwitchText<n>` | Custom label |
| `FootSwitchText<n>` | Label shown, read-only in practice |
| `Scene<n>_<slot>_Mode` | `0` no change, `1` on, `2` off |
| `SceneActive<n>` | Write `true` to fire a scene |
| `Scene<n>_<slot>_Effect` | The block in that slot, read-only in practice |
| `SceneDoubleSwitch<n>`, `ScenePathSwitch<n>` | `0` no change, `1` A, `2` B |
| `Scene<n>Slot<slot>Preset` | Block preset to recall, or `No Preset` |
| `MacroColour<n>` | Scene color, 0-13 |
| `SceneMIDIOut<n>` | Name of a MIDI Out preset, or empty or `--` for none (see below) |
| `SceneNumberOfStates<n>` | `1` or `2` |
| `SceneState<n>` | On a two-state scene, the state in use: `0` first, `1` second. It can read `1` on a one-state scene |
| `State2...` | The second state's versions: `State2Scene<n>_<slot>_Mode`, `State2Scene<n>Slot<slot>Preset`, `State2MacroColour<n>`, `State2SceneDoubleSwitch<n>`, `State2ScenePathSwitch<n>`, `State2SceneMIDIOut<n>` |
| `LastScene`, `LastSceneState` | The last scene fired, counting from 0, and its state |
| `AnySwitchDoubling` | Whether any block is switching A/B. The editor disables a scene's doubling control without it |

Switches 1-3 and 4-6 are separate banks. Switches 4-6 are only reachable when a hold is set to Bank A/B (see [Global settings](#global-settings)). No object on firmware `5.2.0.2a405ee` has a field named for the current bank, and the editor's code never mentions banks, so software probably can't tell which bank the pedal is showing, or which set it calls A.

The pedal keeps the old `Module<n>` and `Operation<n>` when a switch becomes a scene, so ignore them on scene switches.

`ModuleList<n>` lists what switch `n` can be assigned, including non-block modules such as `Tempo`, `Signal Chain` and `Hold Functions`. The `operationList` and `operationEnableList` methods take `[zero-based switch, module name]` and return its operations and whether each can be chosen. The editor calls them to fill its assignment menu, and assigns `Unassigned` with an empty operation. `MIDI Out`'s only operation, `New/Edit...`, opens a dialog in the editor rather than being a real assignment.

### Scene states

A scene can have two states on one switch, and each press alternates between them (User Guide p.32). Each state has its own On/Off/No Change per block and LED colour (p.32) and MIDI out (p.35); presets, doubling and path are probably set up like any scene. The editor adds state 2 by calling `createNewSceneState` with `[zero-based switch, 0]`, then writing `SceneNumberOfStates<n>` as `2`. Selecting a state to edit writes `SceneState<n>`. The maximum is two. On the older HeadRush FX, No Change in state 2 is relative to state 1 ([support article](https://support.headrushfx.com/en/support/solutions/articles/69000828931-headrush-fx-2-5-creating-and-editing-dual-scenes)), and probably works the same here.

`get_scene` reads state 2 and `set_scene` with `state` 2 edits it, creating it first if needed with the editor's sequence: `createNewSceneState` with the zero-based switch and 0, then `SceneNumberOfStates<n>` = 2. Removing it writes `SceneNumberOfStates<n>` = 1, then `SceneState<n>` = 0. Both sequences follow the editor's JavaScript and read back correctly on a Flex Prime on firmware 5.2, through a save. Community notes from a Core ([headrush-remote-buttons](https://github.com/thomasborgogno/headrush-remote-buttons)): firing `SceneActive<n>=true` on an already active two-state scene toggles `SceneState<n>` between 0 and 1, and that client never writes `false`. A Flex Prime on firmware 5.2 didn't do this: four `SceneActive<n>=true` writes on a two-state scene left `SceneState<n>` at 0, and its second state's block changes didn't apply.

### Scene MIDI out

Since firmware 4.1.0, a scene, a footswitch or a rig load can send up to five MIDI messages (User Guide p.34-35):

- Program Change: channel, MSB, LSB, program
- Control Change: channel, CC number, value
- Note On or Note Off: channel, note, velocity

Commands are saved as named MIDI Out presets, and `SceneMIDIOut<n>` holds the preset's name, going by the editor's JavaScript. A footswitch stores one under its `MIDI Out` operation, and a rig in `Rig.MIDIOut`. `/Evil/Engine/MIDIOutCtrl` is the editing buffer, with `Type#`, `Chan#`, `MSB#`, `LSB#`, `Val1#` and `Val2#` for messages 1-5 and `Alt` versions for the second switch state. It has `presets`, `loadPreset`, `createPreset`, `saveCurrentPreset`, `renamePreset`, `deletePreset` and `test` methods, none of which this server calls.

### Doubling

On `Amp` and `Cab`, `Doubling` turns doubling on, and `DoubleMode` true means Switch rather than Stereo. Stereo runs both sides. Switch runs one, and the guide only offers a footswitch (`Doubling: A <Switch> B`, or `Both: A-B-C-D` round-robin across two split paths) or a scene's doubling switch to change it (User Guide p.11, p.32). No field reports the active side.

`Path Mix: A <Switch> B` on a footswitch mutes one path of a split routing, and an expression pedal can crossfade the paths with `Mix > A <Crossfade> B` (User Guide p.15).

## Global settings

Global settings are on `/Evil/Engine/Settings/General`. They affect every rig, and this server only reads them. The object's own `labels` and `order` tie each key to the setting named in the User Guide (p.58):

| Key | Setting in Global Settings > General | Effect |
|---|---|---|
| `TunerFSAssignment` | Assign Tuner Footswitch | Switch 3's hold, index into `Tuner`, `Bank A/B`, `Drums`, `Practice` |
| `LooperFSAssignment` | Assign Looper Footswitch | Switch 2's hold, index into `Looper`, `Bank A/B`, `Drums`, `Practice`. Probably added in 5.0, as the 4.x guides don't list it |
| `OnPressFS` | Footswitch Functions | Boolean: `false` On Release, `true` On Press, which disables all hold functions, including Bank A/B |
| `AutoAssignments` | Auto Assign Footswitches | A newly placed block takes the next free switch |

`get_footswitches` only warns about the holds when the schema names their options, judges On Press by its option name when there is one, and reports `auto_assign_footswitches` as null when the key is missing.

## State-changing methods to be careful with

- **Rigs:** `loadRig`, `loadRigConfirm`, `saveRig`, `saveRigAs`, `renameRig`, `deleteRig`, `makeNewRig`
- **Setlists:** `loadSetlist`, `saveSetlist`, `deleteSetlist`
- **Cloud and Tone3000:** `uploadRig`, `uploadClone`, `downloadRig`, `downloadModelToDevice`
- **Drums:** `togglePlay`

`loadRigConfirm` on a rig with unsaved edits doesn't load anything, though it still returns `true`. It sets `displayDialog` on `/Evil/API/RigSaveDialog`, and the editor then calls `save`, `saveRigAs`, `discard` or `cancel`. `discard` throws away the unsaved rig and finishes the load. This server doesn't expose those calls, and its `load_rig` refuses unsaved rigs first. The dialog later cleared by itself in one test.

Clicking a rig in the official editor's list may load it. The editor's own startup also calls cloud and Tone3000 lookups.

## Firmware and models

| Firmware | Added |
|---|---|
| 4.0.0 | HeadRush Remote, and so this API |
| 4.1.0 | MIDI out commands on footswitches, scenes and rig load. More MIDI CC control |
| 5.0.0 | Authorize with PIN |
| 5.1.0 | NAM and Tone3000 |
| 5.2.0 | Several NAM captures per rig |

From the [release notes](https://cdn.inmusicbrands.com/Software/SGEE/52/READ%20ME%20-%20HeadRush%20Flex%20Prime%20Firmware%20Update%20Instructions%20v5.2.0.pdf). Flex Primes shipped with 4.0 or later ([Sonicstate](https://sonicstate.com/amped/2024/11/15/headrush-expands-its-lineup/)).

The Core and Prime run the same API, and community clients built on a Core use the same paths. Footswitch counts differ: the Core has 5 switches (10 `ModeNew` keys), and the Prime has 12, of which 8 are assignable, with no Bank A/B. Neither is tested here. The Pedalboard, Gigboard and MX5 have no HeadRush Remote ([compare boards](https://headrushfx.com/compare-boards)).

## Sources

- [Flex Prime User Guide v5.2.0](https://cdn.inmusicbrands.com/Software/SGEE/52/HeadRush%20Flex%20Prime%20-%20User%20Guide%20-%20v5.2.0.pdf), the page numbers cited here
- [Flex Prime firmware release notes v5.2.0](https://cdn.inmusicbrands.com/Software/SGEE/52/READ%20ME%20-%20HeadRush%20Flex%20Prime%20Firmware%20Update%20Instructions%20v5.2.0.pdf)
- [Flex Prime FAQ](https://support.headrushfx.com/en/support/solutions/articles/69000862403-headrush-flex-prime-frequently-asked-questions)
- [Transferring clones](https://support.headrushfx.com/en/support/solutions/articles/69000864040-revalver-amp-cloner-transferring-clones-to-the-headrush-prime-core-and-flex-prime-boards)
- Community, tested on other units or unverified:
  - [ToneCommand hardware findings](https://github.com/monzta1/ToneCommand/blob/main/docs/HEADRUSH-HARDWARE-FINDINGS.md) (Core, 5.1.0)
  - [RushLink](https://github.com/Rush-Link/RushLink-App)
  - [headrush-remote-buttons](https://github.com/thomasborgogno/headrush-remote-buttons), an earlier client tested on a Core
  - [headrush-core-toolkit](https://github.com/venyavekk-dev/headrush-core-toolkit/blob/main/skill/headrush-core/references/api.md) (Core)
  - [rigsmith](https://github.com/Gavinboley/rigsmith)
