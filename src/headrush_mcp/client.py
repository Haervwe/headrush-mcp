"""Guarded client for the pedal's undocumented HTTP API.

All device access goes through this class. A POST method call can change the
live device even when its name sounds harmless, so methods are allowlisted, and
there is deliberately no way here to delete or use the cloud. The only way to
overwrite a saved rig is save_loaded_rig, which must be given the loaded rig's name.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

RIGS = "/Evil/API/Rigs"
SETLISTS = "/Evil/API/Setlists"
BLOCKS = "/Evil/API/Blocks"
GUI = "/Evil/Gui"
CHAIN = "/Evil/Engine/Patch/Chain"
RIG = "/Evil/Engine/Patch/Rig"
FOOTSWITCH = "/Evil/Engine/FootSwitch"
SAVE_DIALOG = "/Evil/API/RigSaveDialog"
FILES = "/Evil/API/FileAccess"
GENERAL_SETTINGS = "/Evil/Engine/Settings/General"
EMPTY_SLOT = "Empty Slot"
_SAVE_CONFIRM_ATTEMPTS = 6
_SAVE_CONFIRM_SECONDS = 0.5

READ_METHODS = {
    (FILES, "ls"),  # The official editor's file pickers use this to browse folders.
    (SETLISTS, "getSetlist"),
    (BLOCKS, "blockPresets"),
    (BLOCKS, "categoryBlocks"),
    (BLOCKS, "categoryOfBlock"),
    # The official editor calls these two to fill its footswitch assignment menu.
    (FOOTSWITCH, "operationList"),
    (FOOTSWITCH, "operationEnableList"),
}
WRITE_METHODS = {
    (RIGS, "makeNewRigConfirm"),
    (RIGS, "saveRigAs"),
    (RIGS, "saveRig"),
    (RIGS, "loadRigConfirm"),
    (FOOTSWITCH, "createNewSceneState"),
}

_CHAIN_KEY = re.compile(r"^(ModuleType([1-9]|1[0-4])|Routing)$")
_FOOTSWITCH_KEY = re.compile(
    r"^(Module|Operation|ModeNew|UserFootSwitchText|SceneActive"
    r"|SceneNumberOfStates|SceneState)[1-6]$"
    r"|^(State2)?(SceneDoubleSwitch|ScenePathSwitch|MacroColour)[1-6]$"
    r"|^(State2)?Scene[1-6]_([1-9]|1[0-4])_Mode$"
    r"|^(State2)?Scene[1-6]Slot([1-9]|1[0-4])Preset$"
)
# Block names can contain apostrophes and parentheses, as in Sher'ff and IR (1024).
_READ_PATH = re.compile(r"^/Evil/(API|Cloud|Engine|Gui)(/[\w\-'()]+)*$")
_BLOCK_PATH = re.compile(r"^/Evil/Engine/Patch/[\w\-'()]+$")
# Firing a scene changes what's on, not the rig, so it doesn't count as an edit.
_SCENE_FIRE_KEY = re.compile(r"^SceneActive[1-6]$")
# Methods that leave the loaded rig matching a saved copy, or with nothing written yet.
_CLEARS_EDITS = {(RIGS, "loadRigConfirm"), (RIGS, "makeNewRigConfirm"), (RIGS, "saveRig")}


class HeadRushError(ToolError):
    """A device call failed. As a ToolError, its message reaches the MCP client."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PolicyError(HeadRushError):
    """A call was refused before reaching the device."""


def block_path(block: str) -> str:
    """Return the object path for a block name, as the official editor does."""
    return f"/Evil/Engine/Patch/{block.replace(' ', '_')}"


class HeadRushClient:
    def __init__(
        self,
        host: str = "headrushflexprime.local",
        allow_writes: bool = False,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.allow_writes = allow_writes
        self.own_draft = False  # Whether an unsaved draft on the pedal was built by this server.
        # The pedal doesn't set `dirty` for edits over this API (Flex Prime, 5.2), so the
        # loaded rig's id is kept here once this server has changed it without saving.
        self._edited_rig_id: str | None = None
        self._http = httpx.Client(
            base_url=f"http://{host}/api/v1", transport=transport, timeout=timeout
        )

    def close(self) -> None:
        self._http.close()

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise HeadRushError(f"{method} {url}: {exc}") from exc
        if response.status_code == 403:
            raise HeadRushError(
                "The pedal refused access, so HeadRush Remote seems to be off. Turn it on in "
                "Global Settings > HeadRush Remote on the pedal." + _desc(response),
                status=403,
            )
        if response.status_code == 401:
            raise HeadRushError(
                "The pedal requires approval for this connection. Approve it on the pedal's "
                "screen, or turn off Authorize with PIN in Global Settings > HeadRush Remote. "
                "This server doesn't do PIN pairing." + _desc(response),
                status=401,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HeadRushError(f"{method} {url}: {exc}", status=response.status_code) from exc
        # A write's reply, such as a PUT's, can be empty or plain text. A read's must be JSON,
        # so callers that fail soft on HeadRushError also catch a bad read.
        try:
            return response.json()
        except ValueError:
            if method == "GET":
                raise HeadRushError(
                    f"{method} {url}: reply wasn't JSON", status=response.status_code
                ) from None
            return None

    def _require_writes(self) -> None:
        if not self.allow_writes:
            raise PolicyError("Writes are disabled. Set HEADRUSH_ALLOW_WRITES=1 to enable them.")

    def get_properties(self, path: str) -> dict[str, Any]:
        if not _READ_PATH.match(path):
            raise PolicyError(f"Invalid object path: {path}")
        return self._send("GET", f"/object-properties{path}")

    def get_meta(self, path: str) -> dict[str, Any]:
        if not _READ_PATH.match(path):
            raise PolicyError(f"Invalid object path: {path}")
        return self._send("GET", f"/object-meta{path}")

    def require_block_object(self, block: str) -> None:
        """Refuse a block the firmware lists but has no device object for.

        ReValver Amp 2 and C-Verb 2 are known cases. Writing such a block type crashed a
        pedal in community testing, so it's refused before anything is written.
        """
        if block == EMPTY_SLOT:
            return
        try:
            self.get_meta(block_path(block))
        except HeadRushError as exc:
            if exc.status != 404:
                raise
            raise PolicyError(
                f"{block} is listed by the firmware but has no object on this pedal, so it "
                "can't be placed. Writing a block type like this crashed a pedal in community "
                "testing."
            ) from exc

    def call(self, path: str, method: str, args: list[Any]) -> Any:
        key = (path, method)
        if key in WRITE_METHODS:
            self._require_writes()
        elif key not in READ_METHODS:
            raise PolicyError(f"Method not allowed: {path}/{method}")
        result = self._send("POST", f"/object-method{path}/{method}", json={"arguments": args})
        value = result.get("methodReturnValue") if isinstance(result, dict) else result
        if key in _CLEARS_EDITS and value is not False:
            self._edited_rig_id = None
        elif key in WRITE_METHODS and key not in _CLEARS_EDITS and key != (RIGS, "saveRigAs"):
            self._note_edit()  # Such as adding a scene state.
        return value

    def set_properties(self, path: str, values: dict[str, Any]) -> None:
        """Validate values against the device's schema, then write them."""
        self._require_writes()
        self.validate_values(path, values)
        self._send("PUT", f"/object-properties{path}", json=values)
        if not all(path == FOOTSWITCH and _SCENE_FIRE_KEY.match(k) for k in values):
            self._note_edit()

    def _note_edit(self) -> None:
        """Remember that the loaded rig has changed since it was last saved or loaded."""
        if self._edited_rig_id is None:
            try:
                self._edited_rig_id = self.get_properties(RIGS).get("loadedID") or ""
            except HeadRushError:
                self._edited_rig_id = ""  # Unknown, so it matches only a rig with no id.

    def has_server_edits(self, rigs: dict[str, Any]) -> bool:
        """Return whether this server changed the loaded rig without saving it.

        If another rig has been loaded since, such as on the pedal, those edits are gone.
        """
        if self._edited_rig_id is None:
            return False
        if (rigs.get("loadedID") or "") != self._edited_rig_id:
            self._edited_rig_id = None
            return False
        return True

    def validate_values(self, path: str, values: dict[str, Any]) -> None:
        """Refuse values a write would refuse, without writing anything."""
        self._check_writable_path(path, values)
        properties = self.get_meta(path).get("properties") or {}
        for key, value in values.items():
            _validate(path, key, value, properties.get(key))

    @staticmethod
    def _check_writable_path(path: str, values: dict[str, Any]) -> None:
        if path == CHAIN:
            bad = [k for k in values if not _CHAIN_KEY.match(k)]
        elif path == FOOTSWITCH:
            bad = [k for k in values if not _FOOTSWITCH_KEY.match(k)]
        elif path == RIG or not _BLOCK_PATH.match(path):
            raise PolicyError(f"Writing to {path} is not allowed")
        else:
            return
        if bad:
            raise PolicyError(f"Writing {bad} on {path} is not allowed")

    def status(self) -> dict[str, Any]:
        gui = self.get_properties(GUI)
        rigs = self.get_properties(RIGS)
        cpu = self.get_properties("/Evil/Engine/CPUMeter")
        return {
            "device": gui.get("DeviceName"),
            "firmware": gui.get("AppVersion"),
            "loaded_rig": rigs.get("loadedName"),
            "loaded_rig_id": rigs.get("loadedID"),
            "unsaved_edits": bool(rigs.get("dirty")) or self.has_server_edits(rigs),
            "cpu": cpu.get("CPUTimeSmoothed"),
        }

    def require_clean(self) -> None:
        """Refuse an action that could discard unsaved edits on the loaded rig."""
        rigs = self.get_properties(RIGS)
        if rigs.get("dirty") is None:
            raise PolicyError(
                "The pedal didn't say whether the loaded rig has unsaved edits, so this was "
                "refused to protect them. This firmware may not be supported."
            )
        if rigs["dirty"]:
            raise PolicyError(
                f"'{rigs.get('loadedName')}' has unsaved edits, which this could discard. "
                "Save or discard them on the pedal first."
            )
        if self.has_server_edits(rigs):
            raise PolicyError(
                f"'{rigs.get('loadedName')}' has unsaved edits made through this server, which "
                "this could discard. The pedal doesn't flag them itself. Save them with "
                "save_loaded_rig or save_rig_as_new, or load another rig on the pedal to "
                "discard them."
            )

    def require_new_name(self, name: str) -> None:
        names = self.get_properties(RIGS).get("AllRigNames")
        if not isinstance(names, list):
            raise PolicyError(
                "The pedal didn't list its rig names, so this was refused to avoid replacing "
                "one. This firmware may not be supported."
            )
        if name in names:
            raise PolicyError(f"A rig named '{name}' already exists. Pick another name.")

    def save_as_new(self, name: str, sleep: Callable[[float], None] = time.sleep) -> bool:
        """Save the loaded rig under a name that's new, and return whether the pedal lists it.

        A successful reply doesn't prove a rig exists. The name wasn't there before, so seeing
        it now does. HTTP failures while checking only mean it isn't confirmed yet.
        """
        if self.call(RIGS, "saveRigAs", [name, -1]) is False:
            return False
        for _ in range(_SAVE_CONFIRM_ATTEMPTS):
            try:
                if name in (self.get_properties(RIGS).get("AllRigNames") or []):
                    self._edited_rig_id = None  # The edits are in the new rig now.
                    return True
            except HeadRushError:
                pass
            sleep(_SAVE_CONFIRM_SECONDS)
        return False

    def save_loaded_rig(self, expected_name: str) -> None:
        """Overwrite the loaded rig's saved copy, naming it to prevent saving over the wrong one."""
        loaded = self.get_properties(RIGS).get("loadedName")
        if not expected_name or loaded != expected_name:
            raise PolicyError(f"Refusing to save: '{loaded}' is loaded, not '{expected_name}'.")
        if self.call(RIGS, "saveRig", []) is False:
            raise HeadRushError(f"The device refused to save '{loaded}'")

    def current_chain(self) -> list[dict[str, Any]]:
        types = self.get_properties(BLOCKS)["ModuleTypes"]
        chain = self.get_properties(CHAIN)
        return [
            {"slot": slot, "block": types[chain[f"ModuleType{slot}"]]}
            for slot in range(1, 15)
            if chain.get(f"ModuleType{slot}")
        ]


def _desc(response: httpx.Response) -> str:
    """Return the pedal's own explanation from an error reply, if it gave one."""
    try:
        body = response.json()
    except ValueError:
        return ""
    desc = body.get("desc") if isinstance(body, dict) else None
    return f" The pedal said: {desc}" if desc else ""


def _validate(path: str, key: str, value: Any, meta: dict[str, Any] | None) -> None:
    where = f"{path}.{key}"
    if meta is None:
        raise PolicyError(f"Unknown property: {where}")
    if meta.get("readOnly"):
        raise PolicyError(f"Read-only property: {where}")
    kind = meta.get("type")
    if kind == "boolean":
        valid = isinstance(value, bool)
    elif kind == "string":
        valid = isinstance(value, str)
    elif kind == "integer":
        valid = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and meta.get("minimum", value) <= value <= meta.get("maximum", value)
        )
    elif kind == "number":
        # Numbers are normalized 0-1 on the wire, whatever range the schema displays.
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1
    else:
        valid = False
    if not valid:
        raise PolicyError(f"Invalid value {value!r} for {where} ({kind})")
