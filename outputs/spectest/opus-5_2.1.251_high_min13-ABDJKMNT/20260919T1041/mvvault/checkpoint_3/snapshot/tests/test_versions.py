"""Supported Versions, legacy schemas and Multi-Version Loading."""

import json

import pytest

from conftest import (
    ISO_KEY,
    EPOCH_KEY,
    EPOCH_KEY_ISO,
    V1_SOURCE_ID,
    V1_SOURCE_URL,
    read_catalog,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
)
from mvaultlib import catalog as catalog_module


@pytest.fixture
def loaded(monkeypatch, tmp_path):
    """Load a vault by name with the temporary directory as working directory."""
    monkeypatch.chdir(tmp_path)

    def run(vault):
        return catalog_module.load(vault.name)[0]

    return run


# Spec: Version detection | Read `version` field from `catalog.json`
# Spec: `1` | Supported
def test_version_one_catalog_loads(loaded, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    assert loaded(vault)["version"] == 3


# Spec: `2` | Supported
def test_version_two_catalog_loads(loaded, make_vault):
    vault = make_vault(v2_catalog("http://src.invalid/f.json", episodes=[v2_entry("a")]))
    assert loaded(vault)["version"] == 3


# Spec: `3` | Native format
def test_version_three_catalog_loads_unchanged(loaded, run_cli, tmp_path):
    run_cli("init", "native", "http://src.invalid/f.json")
    assert loaded(tmp_path / "native") == read_catalog(tmp_path / "native")


# Spec: In-memory representation | All versions are usable by every command
# Spec: `1` | Flat `entries` list; `source_id`
def test_version_one_entries_become_episodes_in_memory(loaded, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a"), v1_entry("b")]))
    catalog = loaded(vault)
    assert [entry["id"] for entry in catalog["episodes"]] == ["a", "b"]
    assert (catalog["streams"], catalog["clips"]) == ([], [])


# Spec: Version 1 Source Resolution | `https://media.example.com/channel/<source_id>`
def test_version_one_source_is_derived_from_source_id(loaded, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")], source_id=V1_SOURCE_ID))
    assert loaded(vault)["source"] == V1_SOURCE_URL


# Spec: Version 1 Source Resolution (the derivation follows the given `source_id`)
def test_version_one_source_derivation_uses_the_catalog_value(loaded, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")], source_id="other-id"))
    assert loaded(vault)["source"] == "https://media.example.com/channel/other-id"


# Spec: Version 1 Entry Schema | `id` / `published` / `width` / `height`
def test_version_one_static_fields_are_preserved(loaded, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a", published="2021-05-06T07:08:09", width=640, height=480)]))
    entry = loaded(vault)["episodes"][0]
    assert (entry["id"], entry["published"], entry["width"], entry["height"]) == (
        "a",
        "2021-05-06T07:08:09",
        640,
        480,
    )


# Spec: Version 1 UNIX-Epoch History Keys | string representations of UNIX epoch seconds
def test_version_one_history_keys_become_iso_datetimes(loaded, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a", stamp=EPOCH_KEY)]))
    assert list(loaded(vault)["episodes"][0]["title"]) == [EPOCH_KEY_ISO]


# Spec: Chronological ordering is determined by numeric comparison of these values
def test_version_one_key_order_is_numeric_not_lexicographic(loaded, make_vault):
    history = {"999999999": "older", "1000000000": "newer"}
    vault = make_vault(v1_catalog([v1_entry("a", title=history)]))
    title = loaded(vault)["episodes"][0]["title"]
    assert title == {"2001-09-09T01:46:39": "older", "2001-09-09T01:46:40": "newer"}
    assert title[max(title)] == "newer"


# Spec: Version 1 Entry Schema | `views` | integer values; `likes` | integer or `null`
def test_version_one_history_values_are_preserved(loaded, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a", views={EPOCH_KEY: 77}, likes={EPOCH_KEY: None})]))
    entry = loaded(vault)["episodes"][0]
    assert entry["views"] == {EPOCH_KEY_ISO: 77}
    assert entry["likes"] == {EPOCH_KEY_ISO: None}


# Spec: Version 1 entries have no `removed` field and no `annotations` field
def test_version_one_entries_gain_removed_and_annotations(loaded, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    entry = loaded(vault)["episodes"][0]
    assert list(entry["removed"].values()) == [False]
    assert entry["annotations"] == []


# Spec: Version 2 Catalog Schema | `source` | Full source URL
def test_version_two_source_is_preserved(loaded, make_vault):
    vault = make_vault(v2_catalog("https://elsewhere.invalid/feed.json"))
    assert loaded(vault)["source"] == "https://elsewhere.invalid/feed.json"


# Spec: Version 2 Catalog Schema | `episodes` / `streams` / `clips` arrays
def test_version_two_categories_keep_their_entries(loaded, make_vault):
    vault = make_vault(
        v2_catalog("http://src.invalid/f.json", episodes=[v2_entry("e")], streams=[v2_entry("s")], clips=[v2_entry("c")])
    )
    catalog = loaded(vault)
    assert [catalog[name][0]["id"] for name in ("episodes", "streams", "clips")] == ["e", "s", "c"]


# Spec: Version 2 Entry Schema | `title` | ISO 8601 string keys
def test_version_two_history_keys_are_kept(loaded, make_vault):
    vault = make_vault(v2_catalog("http://src.invalid/f.json", episodes=[v2_entry("a", stamp="2023-02-03T04:05:06")]))
    assert list(loaded(vault)["episodes"][0]["title"]) == ["2023-02-03T04:05:06"]


# Spec: Version 2 entries have no `removed` field and no `annotations` field
def test_version_two_entries_gain_removed_and_annotations(loaded, make_vault):
    vault = make_vault(v2_catalog("http://src.invalid/f.json", streams=[v2_entry("s")]))
    entry = loaded(vault)["streams"][0]
    assert list(entry["removed"].values()) == [False]
    assert entry["annotations"] == []


# Spec: Read-only access | Loading a v1 or v2 catalog for a read-only operation
# does not rewrite `catalog.json`
@pytest.mark.parametrize("build", [lambda: v1_catalog([v1_entry("a")]), lambda: v2_catalog("http://s.invalid/f.json")])
def test_loading_a_legacy_catalog_does_not_touch_the_file(loaded, make_vault, build):
    vault = make_vault(build())
    before = (vault / "catalog.json").read_bytes()
    loaded(vault)
    assert (vault / "catalog.json").read_bytes() == before
    assert not (vault / "catalog.bak").exists()


# Spec: Load trigger | Any command that reads a vault (`sync`, `serve`, `digest`, ...)
def test_sync_reads_a_v2_vault_without_prior_migration(run_cli, make_vault, source):
    make_vault(v2_catalog(source.url, episodes=[v2_entry("a")]))
    result = run_cli("sync", "v")
    assert result.returncode == 0, result.stderr


# Spec: Missing `version` field | Error to stderr; exit non-zero; no migration
def test_missing_version_field_is_an_error(run_cli, make_vault):
    vault = make_vault({"source": "http://s.invalid/f.json", "episodes": [], "streams": [], "clips": []})
    before = (vault / "catalog.json").read_bytes()
    result = run_cli("migrate", "v")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert (vault / "catalog.json").read_bytes() == before


# Spec: Non-integer `version` field | Version-related error to stderr; exit non-zero
@pytest.mark.parametrize("version", ["3", 3.5, True, None, [3]])
def test_non_integer_version_is_a_version_error(run_cli, make_vault, version):
    vault = make_vault({"version": version, "source": "http://s.invalid/f.json", "episodes": [], "streams": [], "clips": []})
    result = run_cli("migrate", "v")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert not (vault / "catalog.bak").exists()


# Spec: `version` greater than `3` | Version-related error to stderr; exit non-zero
def test_version_above_three_is_a_version_error(run_cli, make_vault):
    make_vault({"version": 4, "source": "http://s.invalid/f.json", "episodes": [], "streams": [], "clips": []})
    result = run_cli("migrate", "v")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()


# Spec: `version` greater than `3` | ... no migration; no modification
def test_future_version_catalog_is_left_untouched(run_cli, make_vault):
    vault = make_vault({"version": 9, "source": "http://s.invalid/f.json", "episodes": [], "streams": [], "clips": []})
    before = (vault / "catalog.json").read_bytes()
    run_cli("migrate", "v")
    run_cli("sync", "v")
    assert (vault / "catalog.json").read_bytes() == before
    assert not (vault / "catalog.bak").exists()


# Spec: Version handling errors apply to every command that reads a vault
def test_sync_reports_an_unsupported_version(run_cli, make_vault, source):
    make_vault({"version": 4, "source": source.url, "episodes": [], "streams": [], "clips": []})
    result = run_cli("sync", "v")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()


# Spec: Invalid JSON in `catalog.json` | Error to stderr; exit non-zero; no migration
def test_invalid_json_is_an_error_without_migration(run_cli, make_vault):
    vault = make_vault("{ broken")
    result = run_cli("migrate", "v")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert (vault / "catalog.json").read_text() == "{ broken"
    assert not (vault / "catalog.bak").exists()


# Spec: Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave
# `catalog.json` unchanged
@pytest.mark.parametrize(
    "entry",
    [
        {"published": "2024-01-01T00:00:00", "width": 1, "height": 1},
        v1_entry("a", width="wide"),
        v1_entry("a", title="not a history object"),
        v1_entry("a", views={EPOCH_KEY: "many"}),
        v1_entry("a", title={"yesterday": "t"}),
        "not an object",
    ],
)
def test_malformed_v1_entry_leaves_the_catalog_unchanged(run_cli, make_vault, entry):
    vault = make_vault(v1_catalog([entry]))
    before = (vault / "catalog.json").read_bytes()
    result = run_cli("migrate", "v")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert (vault / "catalog.json").read_bytes() == before
    assert not (vault / "catalog.bak").exists()


# Spec: Malformed v1 or v2 entry data (v2 keys must be ISO 8601 datetimes)
@pytest.mark.parametrize("entry", [v2_entry("a", likes={"whenever": 1}), v2_entry("a", preview={ISO_KEY: 5})])
def test_malformed_v2_entry_leaves_the_catalog_unchanged(run_cli, make_vault, entry):
    vault = make_vault(v2_catalog("http://s.invalid/f.json", clips=[entry]))
    before = (vault / "catalog.json").read_bytes()
    result = run_cli("migrate", "v")
    assert result.returncode != 0
    assert (vault / "catalog.json").read_bytes() == before


# Spec: Version 1 Catalog Schema | `entries` | array (a missing list is malformed)
@pytest.mark.parametrize(
    "catalog",
    [
        {"version": 1, "source_id": V1_SOURCE_ID},
        {"version": 1, "entries": []},
        {"version": 1, "source_id": 7, "entries": []},
        {"version": 2, "episodes": [], "streams": [], "clips": []},
        {"version": 2, "source": "http://s.invalid/f.json", "episodes": [], "streams": []},
    ],
)
def test_malformed_legacy_catalog_shapes_error(run_cli, make_vault, catalog):
    vault = make_vault(catalog)
    result = run_cli("migrate", "v")
    assert result.returncode != 0
    assert (vault / "catalog.json").read_text() == json.dumps(catalog, indent=2) + "\n"
