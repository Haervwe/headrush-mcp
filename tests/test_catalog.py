import json
from pathlib import Path

import httpx
import pytest

from headrush_mcp import catalog
from headrush_mcp.client import BLOCKS, FILES, HeadRushClient, HeadRushError, block_path

TREE = {
    "Neural Amp Modeler": ([], ["Tone 3000", "User"]),
    "Neural Amp Modeler/Tone 3000": (["Boxy AC30 Capture.nam"], []),
    "Neural Amp Modeler/User": ([], []),
    "Amp Clones": ([], ["User"]),
    "Amp Clones/User": (["Friend Amp.ac"], []),
    "SuperClones": ([], []),
    "Impulse Responses": ([], ["User"]),
    "Impulse Responses/User": (["My Cab.wav"], []),
}


class FakePedal:
    def __init__(self) -> None:
        self.methods: list[tuple[str, list]] = []
        self.writes = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if request.method == "PUT":
            self.writes += 1
        if path == f"/object-properties{BLOCKS}":
            modules = ["Empty Slot", "Amp", "Amp 2", "K Drive", "K Drive 2", "Future Block"]
            return httpx.Response(200, json={"ModuleTypes": modules})
        if path == f"/object-meta{block_path('Amp')}":
            options = {"Type": {"x-options": {"strings": ["59 Tweed Bass", "67 Black Duo"]}}}
            return httpx.Response(200, json={"properties": options})
        if path == f"/object-meta{block_path('ReValver Amp')}":
            options = {"Type": {"x-options": {"strings": ["99 Someones Download"]}}}
            return httpx.Response(200, json={"properties": options})
        if path == f"/object-meta{block_path('Cab')}":
            return httpx.Response(200, json={"properties": {}})
        if path == f"/object-meta{block_path('ReValver Cab')}":
            return httpx.Response(200, json={"properties": {}})
        if path == f"/object-method{FILES}/ls":
            folder, file_type = json.loads(request.content)["arguments"]
            self.methods.append((folder, file_type))
            files, folders = TREE[folder]
            return httpx.Response(200, json={"methodReturnValue": folders if file_type == 0 else files})
        return httpx.Response(404)


@pytest.fixture
def pedal() -> FakePedal:
    return FakePedal()


@pytest.fixture
def client(pedal: FakePedal) -> HeadRushClient:
    return HeadRushClient(host="fake", transport=httpx.MockTransport(pedal))


def names(result: dict) -> list[str]:
    return [entry["name"] for entry in result["results"]]


def entry_named(result: dict, name: str) -> dict:
    return next(entry for entry in result["results"] if entry["name"] == name)


def test_catalog_entries_are_well_formed():
    raw = json.loads(Path(catalog.__file__).with_name("catalog.json").read_text(encoding="utf-8"))
    assert raw["source"]["url"].startswith("https://")
    seen = set()
    for entry in raw["entries"]:
        assert entry["kind"] in {"block", "amp", "cab", "mic"}
        key = (entry["kind"], entry.get("block"), entry.get("param"), entry["name"])
        assert key not in seen, key
        seen.add(key)
        if entry["kind"] != "block":
            assert (entry["block"], entry["param"]) in catalog.MODEL_PARAMS[entry["kind"]]
            assert entry["inspired_by"]
        assert not entry["name"].endswith(" 2"), "second instances come from the pedal"
        assert "®" not in (entry.get("inspired_by") or "")


def test_finds_a_block_by_the_pedal_it_is_inspired_by(client):
    found = catalog.find_models(client, query="klon")
    entry = entry_named(found, "K Drive")
    assert entry["kind"] == "block"
    assert entry["category"] == "Overdrive"
    assert entry["installed"] is True
    assert entry["info"].startswith("https://")


def test_punctuation_in_a_query_does_not_matter(client):
    assert "B2 Drive" in names(catalog.find_models(client, query="BD-2"))
    assert "B2 Drive" in names(catalog.find_models(client, query="bd2"))


def test_every_query_word_must_match(client):
    assert "K Drive" not in names(catalog.find_models(client, query="klon reverb"))


def test_model_reports_the_index_this_pedal_uses(client):
    entry = entry_named(catalog.find_models(client, query="twin reverb", kind="amp"), "67 Black Duo")
    assert (entry["block"], entry["param"], entry["index"]) == ("Amp", "Type", 1)
    assert entry["installed"] is True


def test_catalog_model_missing_from_this_pedal_is_marked_and_listed_last(client):
    found = catalog.find_models(client, kind="amp", limit=500)
    assert found["results"][0]["installed"] is True
    entry = entry_named(found, "65 J45")
    assert entry["installed"] is False
    assert "index" not in entry


def test_downloaded_model_unknown_to_the_catalog_is_listed_without_a_guess(client):
    entry = entry_named(catalog.find_models(client, query="someones"), "99 Someones Download")
    assert entry["block"] == "ReValver Amp"
    assert entry["index"] == 0
    assert entry["installed"] is True
    assert entry["inspired_by"] is None


def test_unknown_block_from_the_pedal_is_listed_but_not_second_instances(client):
    found = names(catalog.find_models(client, kind="block", limit=500))
    assert "Future Block" in found
    assert "K Drive 2" not in found
    assert "Empty Slot" not in found


def test_nam_capture_is_found_in_a_subfolder_with_its_full_path(client):
    entry = entry_named(catalog.find_models(client, query="ac30", kind="nam"), "Boxy AC30 Capture")
    assert entry["file"] == "Neural Amp Modeler/Tone 3000/Boxy AC30 Capture.nam"
    assert entry["blocks"] == ["Neural Amp Modeler"]
    assert entry["param"] == "LoadedClone"
    assert entry["inspired_by"] is None


def test_default_search_covers_captures_but_not_ir_folders(client, pedal):
    found = catalog.find_models(client, query="ac30")
    assert "Boxy AC30 Capture" in names(found)
    assert not any(folder.startswith("Impulse") for folder, _ in pedal.methods)
    assert "My Cab" in names(catalog.find_models(client, kind="ir"))


def test_category_search_only_returns_blocks_and_skips_folders(client, pedal):
    found = catalog.find_models(client, category="overdrive", limit=500)
    assert "K Drive" in names(found)
    assert {entry["kind"] for entry in found["results"]} == {"block"}
    assert pedal.methods == []


def test_searching_never_writes_and_works_with_writes_off(client, pedal):
    assert client.allow_writes is False
    catalog.find_models(client, query="drive")
    assert pedal.writes == 0


def test_limit_caps_results_but_total_stays_accurate(client):
    found = catalog.find_models(client, kind="block", limit=3)
    assert len(found["results"]) == 3
    assert found["total"] > 3


def test_unreachable_pedal_still_answers_from_the_catalog_after_one_attempt():
    attempts = []

    def down(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        raise httpx.ConnectTimeout("down")

    client = HeadRushClient(host="fake", transport=httpx.MockTransport(down))
    found = catalog.find_models(client, query="klon")
    assert entry_named(found, "K Drive")["installed"] is None
    assert any("wasn't reachable" in note for note in found["notes"])
    assert len(attempts) == 1


def test_a_failing_model_list_warns_without_losing_other_results():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/object-properties{BLOCKS}"):
            return httpx.Response(200, json={"ModuleTypes": ["Amp"]})
        return httpx.Response(404)

    client = HeadRushClient(host="fake", transport=httpx.MockTransport(handler))
    found = catalog.find_models(client, query="twin", kind="amp")
    assert entry_named(found, "67 Black Duo")["installed"] is None
    assert any("Couldn't read Amp.Type" in note for note in found["notes"])


def test_unknown_kind_is_refused_with_the_valid_choices(client):
    with pytest.raises(HeadRushError, match="Use one of: block"):
        catalog.find_models(client, kind="pedal")
