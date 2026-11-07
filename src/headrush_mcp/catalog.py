"""Find blocks and models by joining the shipped catalog with what this pedal has installed.

catalog.json says what known blocks and models are. Installed lists differ per pedal, since
ReValver models, clones, NAM captures and IRs can be downloaded, so those are read live.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, NamedTuple

from .client import BLOCKS, FILES, HeadRushClient, HeadRushError, block_path

_CATALOG = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
_SOURCE = _CATALOG["source"]
_SKIPPED_BLOCKS = {"Empty Slot"}
_SECOND_INSTANCE = re.compile(r" 2$")
_FOLDER_TYPE = 0
_MAX_FOLDER_DEPTH = 6

NOTE = (
    f"inspired_by comes from {_SOURCE['name']}, a community reference, and isn't official. "
    "A null inspired_by means unknown. Files are identified only by their file names."
)


class FileKind(NamedTuple):
    folder: str
    file_type: int
    blocks: tuple[str, ...]
    param: str


# Roots and file types come from the x-options of each block's file parameter.
FILE_KINDS = {
    "clone": FileKind("Amp Clones", 7, ("Amp Clone", "Pedal Clone"), "LoadedClone"),
    "superclone": FileKind("SuperClones", 8, ("SuperClone",), "LoadedClone"),
    "nam": FileKind("Neural Amp Modeler", 9, ("Neural Amp Modeler",), "LoadedClone"),
    "ir": FileKind("Impulse Responses", 2, ("IR", "IR (1024)"), "IR"),
    "reverb": FileKind("Reverbs", 12, ("C-Verb",), "ReverbFile"),
}
MODEL_PARAMS = {
    "amp": (("Amp", "Type"), ("ReValver Amp", "Type")),
    "cab": (("Cab", "CabType"), ("ReValver Cab", "CabType")),
    "mic": (("Cab", "MicType"), ("ReValver Cab", "MicType")),
}
KINDS = ("block", *MODEL_PARAMS, *FILE_KINDS)
# IR and reverb folders hold hundreds of files, so they're only read when asked for.
_DEFAULT_KINDS = set(KINDS) - {"ir", "reverb"}


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).lower()
    return re.sub(r"[^a-z0-9+]", "", folded)


def _matches(entry: dict[str, Any], query: str) -> bool:
    fields = (entry.get(k) for k in ("name", "inspired_by", "category", "file"))
    haystack = _normalize(" ".join(f for f in fields if f))
    return all(_normalize(token) in haystack for token in query.split())


def _walk(client: HeadRushClient, folder: str, file_type: int, depth: int = 0) -> list[str]:
    """List file paths under a folder. Files usually sit in subfolders, not at the root."""
    files = [f"{folder}/{name}" for name in client.call(FILES, "ls", [folder, file_type]) or []]
    if depth < _MAX_FOLDER_DEPTH:
        for sub in client.call(FILES, "ls", [folder, _FOLDER_TYPE]) or []:
            files += _walk(client, f"{folder}/{sub}", file_type, depth + 1)
    return files


def _file_entries(client: HeadRushClient, kind: str) -> list[dict[str, Any]]:
    spec = FILE_KINDS[kind]
    return [
        {
            "kind": kind,
            "name": path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
            "file": path,
            "blocks": list(spec.blocks),
            "param": spec.param,
            "inspired_by": None,
            "installed": True,
        }
        for path in _walk(client, spec.folder, spec.file_type)
    ]


def _option_list(client: HeadRushClient, block: str, param: str) -> list[str]:
    properties = client.get_meta(block_path(block)).get("properties") or {}
    return ((properties.get(param) or {}).get("x-options") or {}).get("strings") or []


def _merge_models(
    client: HeadRushClient, kind: str, entries: list[dict[str, Any]], warnings: list[str]
) -> None:
    """Mark catalog models as installed or not, and add any the catalog doesn't know."""
    for block, param in MODEL_PARAMS[kind]:
        try:
            options = _option_list(client, block, param)
        except HeadRushError as exc:
            warnings.append(f"Couldn't read {block}.{param}: {exc}")
            continue
        known = [e for e in entries if e.get("block") == block and e.get("param") == param]
        for entry in known:
            entry["installed"] = entry["name"] in options
            if entry["installed"]:
                entry["index"] = options.index(entry["name"])
        names = {e["name"] for e in known}
        entries += [
            {
                "kind": kind,
                "name": name,
                "block": block,
                "param": param,
                "inspired_by": None,
                "installed": True,
                "index": index,
            }
            for index, name in enumerate(options)
            if name not in names
        ]


def _merge_live(
    client: HeadRushClient,
    kinds: set[str],
    entries: list[dict[str, Any]],
    block_names: list[str],
    warnings: list[str],
) -> None:
    if "block" in kinds:
        known = {e["name"] for e in entries if e["kind"] == "block"}
        for entry in entries:
            if entry["kind"] == "block":
                entry["installed"] = entry["name"] in block_names
        entries += [
            {"kind": "block", "name": name, "category": None, "inspired_by": None, "installed": True}
            for name in block_names
            if name not in known
            and name not in _SKIPPED_BLOCKS
            and not _SECOND_INSTANCE.search(name)
        ]
    for kind in MODEL_PARAMS:
        if kind in kinds:
            _merge_models(client, kind, entries, warnings)
    for kind in FILE_KINDS:
        if kind in kinds:
            try:
                entries += _file_entries(client, kind)
            except HeadRushError as exc:
                warnings.append(f"Couldn't list {kind} files: {exc}")


def find_models(
    client: HeadRushClient, query: str = "", kind: str = "", category: str = "", limit: int = 50
) -> dict[str, Any]:
    if kind and kind not in KINDS:
        raise HeadRushError(f"Unknown kind '{kind}'. Use one of: {', '.join(KINDS)}")
    # Only blocks have categories, so a category search needn't walk any folders.
    kinds = {kind} if kind else ({"block"} if category else set(_DEFAULT_KINDS))
    entries = [dict(e) for e in _CATALOG["entries"] if e["kind"] in kinds]
    notes = [NOTE]
    try:
        block_names = client.get_properties(BLOCKS)["ModuleTypes"]
    except HeadRushError as exc:
        notes.append(f"The pedal wasn't reachable, so installed is unknown: {exc}")
    else:
        _merge_live(client, kinds, entries, block_names, notes)
    wanted = _normalize(category)
    results = [
        e
        for e in entries
        if _matches(e, query) and (not wanted or wanted in _normalize(e.get("category") or ""))
    ]
    # Installed first; a stable sort keeps catalog order within each group.
    results.sort(key=lambda e: e.get("installed") is False)
    for entry in results:
        entry.setdefault("installed", None)
        if entry.get("info"):
            entry["info"] = f"{_SOURCE['url']}{entry['info']}"
    return {"total": len(results), "results": results[:limit], "notes": notes}
