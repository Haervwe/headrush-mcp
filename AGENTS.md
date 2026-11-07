# Agent notes

This server can change a real pedal that someone may be playing. It's meant to be shared, so anyone with a HeadRush should be able to use it from the tools and docs alone.

## Rules

- Route all device access through `HeadRushClient`. Don't call the HTTP API directly.
- A POST method call can change the device even if its name sounds like a read. Add methods to the allowlists one at a time, and only after reading how the official editor uses them.
- Don't add delete, rename, cloud or setlist-writing tools without an explicit request from the repo owner.
- Don't bypass the unsaved-edits guard. It protects work you can't see.
- Keep the server local: stdio only, with no network listener.
- Every capability must be a tool or documented. If you needed a throwaway script to do something, it belongs in a tool.
- Keep personal details out of the repo, including IP addresses, users' rig libraries and their installed files.
- Installed models and files differ per pedal, so read them live. `catalog.json` only says what known things are. Don't state what a model with a null `inspired_by` is based on.

## Device behaviour

- Creating a rig and placing blocks finish asynchronously and can undo earlier writes. Verify after a settle period (`rigs.py`).
- Footswitches 1-3 and 4-6 are separate banks. Switches 4-6 are only reachable when a hold is set to Bank A/B in Global Settings, so a correct assignment can still be out of reach.
- Never write a `ModuleType` whose `/Evil/Engine/Patch/<Name>` object is missing, even if `ModuleTypes` lists it. One crashed a Core's audio engine. Check the object exists first (object-meta or the live subtree; `HeadRushClient.require_block_object` uses object-meta).
- Global settings are read-only by policy. They affect every rig, so tell the user what to change on the pedal instead.
- The pedal is reported to snap values to each parameter's `grid` (community, Core), so compare read-backs within one step.
- Other clients and the footswitches can change state at any time, so re-read state rather than assuming it.
- You can verify settings, but not sound. Don't claim a tone is right; ask the user to listen.

See `docs/api.md` for the API, `docs/midi.md` for MIDI control and `src/headrush_mcp/rig-specs.md` for the spec format.

## Sources

Cite the public [User Guide](https://cdn.inmusicbrands.com/Software/SGEE/52/HeadRush%20Flex%20Prime%20-%20User%20Guide%20-%20v5.2.0.pdf) with page numbers, never a local copy or text extract, as those aren't in the repo. Mark community findings and inferences as such, and note which model they were tested on.

## Before committing

Run `uv run pytest`. Tests use a simulated pedal.
