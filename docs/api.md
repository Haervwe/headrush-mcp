# HeadRush Remote Editor API

Unofficial notes from observing the editor on a Flex Prime, firmware `5.2.0.2a405ee`. They're worked out from traffic and the editor's JavaScript, so anything here may change with firmware.

## Basics

- **Base URL:** `http://<host>/api/v1`, plain HTTP. The default host is `headrushflexprime.local`.
- **Auth:** none was needed. The editor also contains a pairing flow (`POST /api/auth`) that handles a 401, so other firmware or settings may require it.
- **CORS:** none, so browser pages on other origins can't use the API. Server-side clients are unaffected.
- **mDNS:** the hostname may resolve to an IPv6 link-local address first, so some clients do better with the IPv4 address.

## Endpoints

`<path>` is an object path such as `/Evil/API/Rigs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/subtree` | Full state and schema, about 1 MB and 290 objects |
| GET | `/object-properties<path>` | Read an object |
| PUT | `/object-properties<path>` | Write properties, with a JSON body of properties |
| GET | `/object-meta<path>` | Read an object's schema |
| POST | `/object-method<path>/<method>` | Call a method: request `{"arguments":[...]}`, response `{"methodReturnValue":...}` |
| GET | `/files/...` (not under `/api/v1`) | Static files such as block images |

**A POST isn't necessarily a write, and the method name is the only hint.** Calling a method with the wrong argument order returned a 504 in testing.

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

Numbers are normalized 0-1 on the wire, whatever range the schema shows. To convert a linear parameter:

```text
normalized = (display - minimum) / (maximum - minimum)
```

For example, on `AIR Delay.Delay` (1-4000 ms), 381 ms is `(381 - 1) / 3999 = 0.095`.

Times, percentages and decibels were linear wherever checked. Some frequency and rate parameters aren't: `Multi Chorus.Rate` appears exponential. The editor has several curves, so check those on the pedal.

Integers such as `Amp.Type` are indexes into `x-options.strings` in the schema, and aren't normalized.

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

`ModuleTypes` lists `ReValver Amp 2` and `C-Verb 2`, but neither has an object on firmware `5.2.0.2a405ee`, so reading them returns a 404. Other names can contain apostrophes and parentheses, like `Sher'ff` and `IR (1024)`, which stay as they are in the path.

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

The editor saves Tone3000 downloads to `Neural Amp Modeler/Tone 3000`, and HeadRush Cloud clones to `Amp Clones/HeadRush Cloud` or `SuperClones/HeadRush Cloud`.

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
| `SceneMIDIOut<n>` | MIDI out, format not yet checked |
| `SceneNumberOfStates<n>`, `SceneState<n>` | Number of switch states, and the current one |
| `AnySwitchDoubling` | Whether any block is switching A/B. The editor disables a scene's doubling control without it |

Switches 1-3 and 4-6 appear as separate banks. Scenes also have a second state (`State2...` keys and `createNewSceneState`), which this server doesn't use.

The pedal keeps the old `Module<n>` and `Operation<n>` when a switch becomes a scene, so ignore them on scene switches.

On `Amp` and `Cab`, `Doubling` turns doubling on, and `DoubleMode` true means Switch rather than Stereo. No field reporting the active A/B side has been found, though `LastScene` gives the last scene fired, counting from 0.

Global settings are on `/Evil/Engine/Settings/General`, including `TunerFSAssignment`, `LooperFSAssignment` and `AutoAssignments`. They affect every rig, and this server only reads them.

## State-changing methods to be careful with

- **Rigs:** `loadRig`, `loadRigConfirm`, `saveRig`, `saveRigAs`, `renameRig`, `deleteRig`, `makeNewRig`
- **Setlists:** `loadSetlist`, `saveSetlist`, `deleteSetlist`
- **Cloud and Tone3000:** `uploadRig`, `uploadClone`, `downloadRig`, `downloadModelToDevice`
- **Drums:** `togglePlay`

`loadRigConfirm` on a rig with unsaved edits doesn't load anything, though it still returns `true`. It sets `displayDialog` on `/Evil/API/RigSaveDialog`, and the editor then calls `save`, `saveRigAs`, `discard` or `cancel`. `discard` throws away the unsaved rig and finishes the load. This server doesn't expose those calls, and its `load_rig` refuses unsaved rigs first. The dialog later cleared by itself in one test.

Clicking a rig in the official editor's list may load it. The editor's own startup also calls cloud and Tone3000 lookups.

## Related project

[headrush-remote-buttons](https://github.com/thomasborgogno/headrush-remote-buttons) is an earlier client tested on a HeadRush Core. Its paths match, but the footswitch count differs by model.
