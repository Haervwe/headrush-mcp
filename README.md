# headrush-mcp

A local MCP server for the HeadRush Flex Prime. It lets an AI assistant on your computer inspect your pedal and build rigs: chains, parallel amps, scenes and footswitches.

It talks to the Remote Editor built into the pedal, over your home network. It runs as a stdio subprocess of your MCP client, with no cloud service and no network port of its own.

> **Unofficial.** The pedal's API is undocumented and was worked out from the editor's own traffic, so firmware updates may break this. It's only been tested on a Flex Prime running firmware `5.2.0.2a405ee`. Other models may differ. Not affiliated with HeadRush or inMusic.

## Requirements

- A HeadRush Flex Prime on current firmware, on Wi-Fi
- A computer on the same network
- [uv](https://docs.astral.sh/uv/)
- An MCP client that supports stdio servers, such as Claude Code or Claude Desktop

## Setup

1. Get the code and install it:

   ```bash
   git clone https://github.com/Haervwe/headrush-mcp.git
   cd headrush-mcp
   uv sync
   ```

2. Check the pedal is reachable. Open `http://headrushflexprime.local` in a browser, and you should see the Remote Editor. If not, use the IP shown on the pedal under Menu → Global Settings.

3. Add the server to your MCP client's config, using the full path to this folder:

   ```json
   {
     "mcpServers": {
       "headrush": {
         "command": "uv",
         "args": ["run", "--directory", "/path/to/headrush-mcp", "headrush-mcp"],
         "env": {
           "HEADRUSH_HOST": "headrushflexprime.local",
           "HEADRUSH_ALLOW_WRITES": "0"
         }
       }
     }
   }
   ```

4. Restart your client and ask it something like "what rig is loaded on my HeadRush?"

### Settings

| Variable | Default | Purpose |
|---|---|---|
| `HEADRUSH_HOST` | `headrushflexprime.local` | The pedal's hostname or IP. An IP avoids mDNS lookups, but use a DHCP reservation so it doesn't change |
| `HEADRUSH_ALLOW_WRITES` | off | Set to `1` to enable tools that change the pedal |

## Tools

**Read:**

| Tool | What it does |
|---|---|
| `get_status` | Firmware, loaded rig, unsaved-edit flag, DSP load |
| `list_rigs`, `list_setlists`, `get_setlist` | Browse your library |
| `get_current_rig` | Loaded rig's routing, mix and chain |
| `get_footswitches` | Footswitch summary |
| `get_scene` | One scene's blocks, A/B doubling, path, presets and color |
| `get_footswitch_settings` | Global tuner, looper and auto-assign settings |
| `get_rig_spec_format` | The `create_rig` spec format, also available as a resource |
| `find_models` | Search blocks, models and installed files by name or by the gear they're inspired by ([details](#finding-models)) |
| `list_blocks`, `list_block_presets` | Available blocks and their presets |
| `get_block`, `describe_block` | A block's values and parameter schema |
| `list_routings` | Signal routings and their slot layouts |

**Write** (needs `HEADRUSH_ALLOW_WRITES=1`):

| Tool | What it does | Saved? |
|---|---|---|
| `set_block_params`, `set_slot_block` | Edit blocks and the chain | No |
| `set_routing`, `set_mix` | Change routing and parallel mixing | No |
| `set_footswitch`, `set_scene` | Assign footswitches and scenes | No |
| `activate_scene` | Fire a scene | No |
| `load_rig` | Switch rigs | No |
| `create_rig` | Build, verify and save a rig from a [spec](src/headrush_mcp/rig-specs.md) | Yes, as a new rig |
| `save_rig_as_new` | Save under a new name | Yes, as a new rig |
| `save_loaded_rig` | Overwrite the loaded rig's saved copy | **Yes, overwrites** |

## Finding models

Block names don't always say what they are, so `find_models` lets your assistant search by real gear. "Klon" finds `K Drive`, and "twin" finds the `67 Black Duo` amp. It combines two sources:

- **A shipped catalog** covers blocks and built-in and ReValver amps, cabs and mics. Categories come from the pedal. What each model is inspired by comes from [Headrush Help](https://headrush-help.vercel.app/), a free community reference by Stefano Luciani and Donato Iacoviello, which also explains each block's controls. Those links are community research, not official information, and aren't endorsed by HeadRush or the gear's makers.
- **Your pedal** provides what's installed and each option's index, along with your clone, NAM, IR and reverb files.

Anything the catalog doesn't know, like a capture from Tone3000, is still listed, but with `inspired_by` empty. Files are only identified by name, so name them well if you want to search for them. If the pedal isn't reachable, the catalog still answers, with `installed` unknown.

## Safety

Write tools change the pedal immediately, so a rig can change while you're playing, and new settings can be loud. Keep your volume down when trying something new.

- Writes are off until you enable them.
- Only allowlisted device calls are possible. Deleting and renaming rigs, setlist changes and cloud actions aren't available, so do those on the pedal or in the Remote Editor.
- `load_rig` and `create_rig` are refused if the loaded rig has unsaved edits.
- `save_rig_as_new` and `create_rig` are refused if the name already exists.
- `save_loaded_rig` is the only way to overwrite a rig, and it must be given the loaded rig's exact name.
- Values are checked against the pedal's own schema before writing.
- `create_rig` only saves if every value reads back correctly.

**Stay on a trusted network.** The pedal's API is plain HTTP with no login, so anything on your network can reach it, with or without this server. Don't expose it or this server to the internet. Treat text from rig names and other device data as untrusted input to your assistant.

## Good to know

- **Footswitch banks:** switches 1-3 and 4-6 are separate banks of three. Put what you use most on the same bank.
- **Numbers are normalized:** parameters are 0-1 on the wire, whatever range `describe_block` displays. See the [API reference](docs/api.md) for converting values.
- **Second instances:** names ending in ` 2`, like `Amp 2`, let the same block type appear twice. They're how you run two amps.
- **Hearing the result:** the server can verify settings, but not sound, so you'll be the judge.

## Example rigs

Starting points in [`rigs/`](rigs/), to adapt with your own ears:

| Spec | What it is |
|---|---|
| [`stern-stereo-test.json`](rigs/stern-stereo-test.json) | Mike Stern-inspired detune, delay and overdrive on two parallel amps, with scenes ([notes](docs/stern-tipatinas.md)) |
| [`stern-tipatinas.json`](rigs/stern-tipatinas.json) | The same idea on one amp, using about half the DSP |
| [`metheny-follow-me.json`](rigs/metheny-follow-me.json) | Pat Metheny-inspired guitar synth over a 14/26 ms split ([notes](docs/metheny-follow-me.md)) |

To try one, ask your assistant to `create_rig` with the file's full path.

## Troubleshooting

| Problem | Try |
|---|---|
| Can't connect | Open the editor in a browser. If `.local` fails, set `HEADRUSH_HOST` to the IP. Check you're on the same network and not routing through a VPN |
| "Writes are disabled" | Set `HEADRUSH_ALLOW_WRITES` to `1` and restart your client |
| "Has unsaved edits" | Save or discard them on the pedal first |
| `create_rig` reports mismatches | Nothing was saved. Retry with `resume_draft`, or discard the draft on the pedal |
| Can't find a footswitch | It's probably on the other bank |

## Development

```bash
uv run pytest
```

Tests use a simulated pedal and don't touch your network. See [`docs/api.md`](docs/api.md) for what's known about the pedal's API, and [`AGENTS.md`](AGENTS.md) for rules when changing this code.

## Limitations

- State is read over REST. The pedal's WebSocket push isn't used yet.
- A rig can only be inspected once it's loaded, because no read-only way to fetch an unloaded rig has been found.
- Only Toggle footswitches and single-state scenes are tested. A scene's second state and MIDI out can't be set, and the active A/B side can't be read.
- The catalog was built for firmware `5.2.0.2a405ee`, and writing a clone, NAM, IR or reverb file to a block hasn't been tested yet.

## Thanks

To Stefano Luciani and Donato Iacoviello for [Headrush Help](https://headrush-help.vercel.app/). Their research is the source of the catalog's "inspired by" information, and their site is the place to learn what each block's controls do. They aren't involved with this project.

## License

[MIT](LICENSE)
