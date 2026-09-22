"""Spec sections: Supported Versions / Version 1 & 2 schemas / Multi-Version
Loading / Version 1 Source Resolution."""
import json
import re

from conftest import (EPOCH, EPOCH_ISO, OLD_EPOCH, OLD_EPOCH_ISO,
                      V1_SOURCE_PREFIX, entry, find, has_backup, make_vault,
                      payload, read_bytes, read_catalog, v1_catalog, v1_entry,
                      v2_catalog, v2_entry, v3_catalog, v3_entry)

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


# Phrase: "| `1` | Supported | Flat `entries` list; `source_id`; UNIX-epoch
#          history keys; no `removed`; no `annotations` |"
# Context: a catalog in exactly that shape is accepted by a reading command.
def test_version_1_catalog_is_supported(run, tmp_path):
    make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    result = run("migrate", "v1")
    assert result.returncode == 0, result.stderr


# Phrase: "| `2` | Supported | Category arrays; full `source`; ISO 8601 history
#          keys; no `removed`; no `annotations` |"
def test_version_2_catalog_is_supported(run, tmp_path):
    make_vault(tmp_path, "v2", v2_catalog(episodes=[v2_entry("e1")]))
    result = run("migrate", "v2")
    assert result.returncode == 0, result.stderr


# Phrase: "| `3` | Native format | ... `removed`; `annotations` |"
def test_version_3_catalog_is_the_native_format(run, tmp_path):
    make_vault(tmp_path, "v3", v3_catalog(episodes=[v3_entry("e1")]))
    result = run("migrate", "v3")
    assert result.returncode == 0, result.stderr
    assert read_catalog(tmp_path / "v3")["version"] == 3


# Phrase: "Version 1 Catalog Schema | `version` | integer | `1` |"
#         "| `source_id` | string | Short platform identifier |"
#         "| `entries` | array | All entries in a single flat list |"
def test_version_1_catalog_fields_are_consumed(run, tmp_path):
    vault = make_vault(tmp_path, "v1",
                       v1_catalog(source_id="abc", entries=[v1_entry("e1"),
                                                            v1_entry("e2")]))
    assert run("migrate", "v1").returncode == 0
    catalog = read_catalog(vault)
    assert catalog["source"] == V1_SOURCE_PREFIX + "abc"
    assert [e["id"] for e in catalog["episodes"]] == ["e1", "e2"]


# Phrase: Version 1 Entry Schema — `id`, `published`, `width`, `height` and the
# five history objects are all carried over by a load.
def test_version_1_entry_fields_survive_loading(run, tmp_path):
    item = v1_entry("e1", published="2023-02-03T04:05:06", width=640,
                    height=480, title="Ti", description="De", views=7,
                    likes=None, preview="pr")
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[item]))
    assert run("migrate", "v1").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    assert stored["id"] == "e1"
    assert stored["published"] == "2023-02-03T04:05:06"
    assert stored["width"] == 640 and stored["height"] == 480
    assert stored["title"] == {EPOCH_ISO: "Ti"}
    assert stored["description"] == {EPOCH_ISO: "De"}
    assert stored["views"] == {EPOCH_ISO: 7}
    assert stored["likes"] == {EPOCH_ISO: None}
    assert stored["preview"] == {EPOCH_ISO: "pr"}


# Phrase: "Version 1 entries have **no** `removed` field and **no**
#          `annotations` field."
# Context: the fixture omits them and the load still succeeds.
def test_version_1_entry_without_removed_or_annotations_loads(run, tmp_path):
    item = v1_entry("e1")
    assert "removed" not in item and "annotations" not in item
    make_vault(tmp_path, "v1", v1_catalog(entries=[item]))
    assert run("migrate", "v1").returncode == 0


# Phrase: "Version 1 history objects use string representations of UNIX epoch
#          seconds as keys (e.g., `\"1718444400\"`)."
def test_version_1_epoch_key_example_converts(run, tmp_path):
    vault = make_vault(tmp_path, "v1",
                       v1_catalog(entries=[v1_entry("e1", epoch=1718444400)]))
    assert run("migrate", "v1").returncode == 0
    assert list(read_catalog(vault)["episodes"][0]["title"]) == ["2024-06-15T09:40:00"]


# Phrase: "Chronological ordering is determined by numeric comparison of these
#          values."
# Context: "999999999" sorts after "1718444400" as text but before it
# numerically; the converted keys must preserve the numeric order.
def test_version_1_epoch_keys_order_numerically(run, tmp_path):
    item = v1_entry("e1")
    item["title"] = {str(OLD_EPOCH): "older", str(EPOCH): "newer"}
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[item]))
    assert run("migrate", "v1").returncode == 0
    title = read_catalog(vault)["episodes"][0]["title"]
    assert title == {OLD_EPOCH_ISO: "older", EPOCH_ISO: "newer"}
    assert max(title) == EPOCH_ISO
    assert title[max(title)] == "newer"


# Phrase: "The full source URL for a version 1 vault is derived
#          deterministically from `source_id`:
#          https://media.example.com/channel/<source_id>"
def test_version_1_source_url_derivation(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(source_id="chan42"))
    assert run("migrate", "v1").returncode == 0
    assert read_catalog(vault)["source"] == "https://media.example.com/channel/chan42"


# Phrase: "All commands that need a source URL for a version 1 vault must use
#          this derivation."
# Context: `sync` fetches the derived URL rather than anything stored.
def test_sync_fetches_the_derived_source_url(run_inproc, tmp_path):
    make_vault(tmp_path, "v1", v1_catalog(source_id="chan42"))
    url = V1_SOURCE_PREFIX + "chan42"
    result = run_inproc("sync", "v1", responses={url: payload()})
    assert result.returncode == 0, result.stderr
    assert result.calls == [url]


# Phrase: Version 2 Catalog Schema — `version`, `source`, `episodes`,
# `streams`, `clips`.
def test_version_2_catalog_fields_are_consumed(run, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(
        source="http://host.invalid/f.json",
        episodes=[v2_entry("e1")], streams=[v2_entry("s1")],
        clips=[v2_entry("c1")]))
    assert run("migrate", "v2").returncode == 0
    catalog = read_catalog(vault)
    assert catalog["source"] == "http://host.invalid/f.json"
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Phrase: Version 2 Entry Schema — ISO 8601 history keys are kept verbatim.
def test_version_2_entry_fields_survive_loading(run, tmp_path):
    item = v2_entry("e1", stamp="2022-05-05T05:05:05", published="2021-01-02",
                    width=800, height=600, title="Ti", description="De",
                    views=9, likes=None, preview="pr")
    vault = make_vault(tmp_path, "v2", v2_catalog(episodes=[item]))
    assert run("migrate", "v2").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    assert stored["published"] == "2021-01-02"
    assert stored["width"] == 800 and stored["height"] == 600
    assert stored["title"] == {"2022-05-05T05:05:05": "Ti"}
    assert stored["likes"] == {"2022-05-05T05:05:05": None}


# Phrase: "Version 2 entries have **no** `removed` field and **no**
#          `annotations` field."
def test_version_2_entry_without_removed_or_annotations_loads(run, tmp_path):
    item = v2_entry("e1")
    assert "removed" not in item and "annotations" not in item
    make_vault(tmp_path, "v2", v2_catalog(episodes=[item]))
    assert run("migrate", "v2").returncode == 0


# Phrase: "Load trigger | Any command that reads a vault (`sync`, `serve`,
#          `digest`, and future commands)"
# Context: `sync` is the implemented reading command; it loads a v2 vault.
def test_sync_loads_a_legacy_vault(run, source, tmp_path):
    make_vault(tmp_path, "v2", v2_catalog(source=source.url,
                                          episodes=[v2_entry("e1")]))
    source.payload = payload(episodes=[entry("e1")])
    result = run("sync", "v2")
    assert result.returncode == 0, result.stderr


# Phrase: "Version detection | Read `version` field from `catalog.json`"
# Context: the same entry shape is read as v1 or v2 purely by the version
# field; as v2 the ISO keys stay, as v1 the epoch keys convert.
def test_version_field_selects_the_schema(run, tmp_path):
    epoch_item = v1_entry("e1", epoch=EPOCH)
    as_v1 = make_vault(tmp_path, "a", v1_catalog(entries=[epoch_item]))
    iso_item = v2_entry("e1", stamp=EPOCH_ISO)
    as_v2 = make_vault(tmp_path, "b", v2_catalog(episodes=[iso_item]))
    assert run("migrate", "a").returncode == 0
    assert run("migrate", "b").returncode == 0
    assert list(read_catalog(as_v1)["episodes"][0]["title"]) == [EPOCH_ISO]
    assert list(read_catalog(as_v2)["episodes"][0]["title"]) == [EPOCH_ISO]


# Phrase: "In-memory representation | All versions are usable by every command"
# Context: sync works against a v1, a v2 and a v3 vault alike.
def test_every_version_is_usable_by_sync(run, source, run_inproc, tmp_path):
    make_vault(tmp_path, "b", v2_catalog(source=source.url,
                                         episodes=[v2_entry("e1")]))
    make_vault(tmp_path, "c", v3_catalog(source=source.url,
                                         episodes=[v3_entry("e1")]))
    source.payload = payload(episodes=[entry("e1", title="fresh")])
    for name in ("b", "c"):
        result = run("sync", name)
        assert result.returncode == 0, (name, result.stderr)
        stored = find(read_catalog(tmp_path / name), "episodes", "e1")
        assert stored["title"][max(stored["title"])] == "fresh"
        assert read_catalog(tmp_path / name)["version"] == 3

    make_vault(tmp_path, "a", v1_catalog(source_id="k", entries=[v1_entry("e1")]))
    url = V1_SOURCE_PREFIX + "k"
    result = run_inproc("sync", "a",
                        responses={url: payload(episodes=[entry("e1", title="fresh")])})
    assert result.returncode == 0, result.stderr
    stored = read_catalog(tmp_path / "a")["episodes"][0]
    assert stored["title"][max(stored["title"])] == "fresh"


# Phrase: "Read-only access | Loading a v1 or v2 catalog for a read-only
#          operation does **not** rewrite `catalog.json`"
# Context: the only read-only path available is a sync that aborts before its
# write (source fetch failure); the legacy catalog must survive untouched.
# See AMBIGUITIES.md T14.
def test_read_only_load_does_not_rewrite_v1_catalog(run_inproc, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    before = read_bytes(vault / "catalog.json")
    result = run_inproc("sync", "v1", responses={})
    assert result.returncode != 0
    assert read_bytes(vault / "catalog.json") == before
    assert not has_backup(vault)


# Phrase: "Read-only access | ... does **not** rewrite `catalog.json`" (v2)
def test_read_only_load_does_not_rewrite_v2_catalog(run, source, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(source=source.url,
                                                  episodes=[v2_entry("e1")]))
    before = read_bytes(vault / "catalog.json")
    source.body = b"{ not json"
    result = run("sync", "v2")
    assert result.returncode != 0
    assert read_bytes(vault / "catalog.json") == before
    assert not has_backup(vault)
