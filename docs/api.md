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
| GET | `/object-properties<path>` | Read an object |
| PUT | `/object-properties<path>` | Write properties, with a JSON body of properties |
| GET | `/object-meta<path>` | Read an object's schema |
| POST | `/object-method<path>/<method>` | Call a method: request `{"arguments":[...]}`, response `{"methodReturnValue":...}` |
| GET | `/files/...` (not under `/api/v1`) | Static files such as block images |

**A POST isn't necessarily a write, and the method name is the only hint.** Calling a method with the wrong argument order returned a 504 in testing.

## Auth and errors

| Status | Meaning |
|---|---|
| 401 | Authorize with PIN is on and this client isn't paired |
| 403 | HeadRush Remote is off. The body has a `desc` field, `DataModel: Web access temporarily disabled`. Seen on a Core at 5.1.0, where `/subtree` returned 404 instead (community, [ToneCommand](https://github.com/monzta1/ToneCommand/blob/main/docs/HEADRUSH-HARDWARE-FINDINGS.md)) |
| 504 | A method call with the wrong arguments |

Setting **New Connection Attempts** to **Deny** makes the pedal reject new connection attempts (User Guide p.61). That probably shows up as a connection failure rather than an HTTP error (untested).

The PIN exchange on the wire is unverified, and two community clients disagree:

- [RushLink](https://github.com/Rush-Link/RushLink-App/blob/main/src-tauri/src/lib.rs) sends `POST /api/auth` with `{"pin": ...}`, keeps no cookies, and opens the WebSocket without auth.
- [rigsmith](https://github.com/Gavinboley/rigsmith/blob/HEAD/rigsmith/device/client.py) polls an empty POST and uses a `sessionID` cookie, on a Core.

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

Numbers are normalized 0-1 on the wire, whatever range the schema shows. To convert a linear parameter:

```text
normalized = (display - minimum) / (maximum - minimum)
```

For example, on `AIR Delay.Delay` (1-4000 ms), 381 ms is `(381 - 1) / 3999 = 0.095`.

Times, percentages and decibels were linear wherever checked. Some frequency and rate parameters aren't: `Multi Chorus.Rate` appears exponential. The editor has several curves, so check those on the pedal.

Each parameter's schema has an opaque curve id in `x-options.normalizeAlgo` and a step size, `grid`. The curves for each id aren't decoded. The pedal snaps written values to the grid, so a read-back can differ slightly from what was written, and out-of-range values aren't clamped (community, tested on a Core: ToneCommand). Compare read-backs within one grid step, not as exact floats.

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

`ModuleTypes` lists `ReValver Amp 2` and `C-Verb 2`, but neither has an object on firmware `5.2.0.2a405ee`, so reading them returns a 404. **Don't write a module type that has no object.** On a Core at 5.1.0, writing one crashed the audio engine once, and others reverted or stuck as an empty slot (community, ToneCommand). `Neural Amp Modeler 2` only gained an object in 5.2 (community, ToneCommand). Check the `/Evil/Engine/Patch/<Name>` object exists before placing a block, with object-meta or the live subtree; the server's `require_block_object` uses object-meta and treats a 404 as missing. Other names can contain apostrophes and parentheses, like `Sher'ff` and `IR (1024)`, which stay as they are in the path.

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
| `SceneMIDIOut<n>` | MIDI out, encoding unknown (see below) |
| `SceneNumberOfStates<n>`, `SceneState<n>` | Number of switch states, and the current one |
| `AnySwitchDoubling` | Whether any block is switching A/B. The editor disables a scene's doubling control without it |

Switches 1-3 and 4-6 are separate banks, probably labelled A and B (unconfirmed on the pedal). Switches 4-6 are only reachable when a hold is set to Bank A/B (see [Global settings](#global-settings)).

The pedal keeps the old `Module<n>` and `Operation<n>` when a switch becomes a scene, so ignore them on scene switches.

### Scene states

A scene can have two states on one switch, and each press alternates between them (User Guide p.32). Each state has its own On/Off/No Change per block and LED colour (p.32) and MIDI out (p.35); presets, doubling and path are probably set up like any scene. The "+" next to Switch State 1 in the editor adds state 2, which matches the `createNewSceneState` method and the `State2...` keys. The maximum is two. On the older HeadRush FX, No Change in state 2 is relative to state 1 ([support article](https://support.headrushfx.com/en/support/solutions/articles/69000828931-headrush-fx-2-5-creating-and-editing-dual-scenes)), and probably works the same here.

This server doesn't create or edit state 2. Community notes from a Core ([headrush-remote-buttons](https://github.com/thomasborgogno/headrush-remote-buttons)): firing `SceneActive<n>=true` on an already active two-state scene toggles `SceneState<n>` between 0 and 1, and that client never writes `false`. Untested here.

### Scene MIDI out

Since firmware 4.1.0, a scene, a footswitch or a rig load can send up to five MIDI messages (User Guide p.34-35):

- Program Change: channel, MSB, LSB, program
- Control Change: channel, CC number, value
- Note On or Note Off: channel, note, velocity

Commands are saved as named MIDI Out presets, and a scene's SWITCH STATE picks which state sends them. How `SceneMIDIOut<n>` encodes this is unknown. It may refer to a preset under `/Evil/Engine/MIDIOutCtrl`, but that's a guess.

### Doubling

On `Amp` and `Cab`, `Doubling` turns doubling on, and `DoubleMode` true means Switch rather than Stereo. Stereo runs both sides. Switch runs one, and the guide only offers a footswitch (`Doubling: A <Switch> B`, or `Both: A-B-C-D` round-robin across two split paths) or a scene's doubling switch to change it (User Guide p.11, p.32). That probably explains why no field reports the active side. `LastScene` gives the last scene fired, counting from 0.

`Path Mix: A <Switch> B` on a footswitch mutes one path of a split routing, and an expression pedal can crossfade the paths with `Mix > A <Crossfade> B` (User Guide p.15).

## Global settings

Global settings are on `/Evil/Engine/Settings/General`. They affect every rig, and this server only reads them. The pairing of keys to the guide's settings (User Guide p.58) is inferred from names, not confirmed on the pedal:

| Key | Setting in Global Settings > General | Effect |
|---|---|---|
| `TunerFSAssignment` | Assign Tuner Footswitch | Switch 3's hold: Tuner, Bank A/B, Drum Machine or Practice Tool |
| `LooperFSAssignment` | Assign Looper Footswitch | Switch 2's hold: Looper, Bank A/B, Drum Machine or Practice Tool. Probably added in 5.0, as the 4.x guides don't list it |
| `OnPressFS` | Footswitch Function | On Press disables all hold functions, including Bank A/B |
| `AutoAssignments` | Auto Assign Footswitches | A newly placed block takes the next free switch |

The enum values behind these keys haven't been read yet. `get_footswitches` only warns about the holds when the schema names their options, judges On Press by its option name when there is one, and reports `auto_assign_footswitches` as null when the key is missing.

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
