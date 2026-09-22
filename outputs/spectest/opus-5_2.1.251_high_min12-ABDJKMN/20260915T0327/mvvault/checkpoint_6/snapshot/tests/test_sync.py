"""Spec sections: `sync` Command / `sync` Source Entry Schema /
`entry` Stored Fields (first observation)."""
import json
import re

import pytest

from conftest import current, entry, find, payload, read_catalog

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
TRACKED = ["title", "description", "views", "likes", "preview", "removed"]


# --- Phrase: "Syntax | `python mvault.py sync <name>`" +
#     "Vault input | Existing valid vault at `<name>/`"
def test_sync_exits_zero_on_valid_vault(run, source, vault):
    source.set_payload(payload())
    result = run("sync", "vault")
    assert result.returncode == 0, result


# --- Phrase: "Source request | HTTP `GET` to vault `source` URL"
def test_sync_issues_http_get_to_source_url(run, source, vault):
    source.set_payload(payload())
    run("sync", "vault")
    assert source.requests, "source was never requested"
    assert all(method == "GET" for method, _ in source.requests), source.requests
    assert source.requests[0][1] == "/source.json"


# --- Phrase: "Source response shape | JSON object with `episodes`,
#     `streams`, and `clips` arrays"
def test_sync_reads_all_three_categories(run, source, vault, tmp_path):
    source.set_payload(
        payload(episodes=[entry("e1")], streams=[entry("s1")], clips=[entry("c1")])
    )
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# --- Phrase: "Success effect | Update catalog with new, changed, removed, and
#     restored entries" (context: root schema survives a sync)
def test_sync_preserves_root_schema(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert catalog["version"] == 3
    assert catalog["source"] == source.url
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# --- Phrase: "Missing or invalid vault | Error to stderr including `<name>`;
#     exit non-zero" (missing)
def test_sync_missing_vault_exits_non_zero_with_name(run, source):
    result = run("sync", "ghost")
    assert result.returncode != 0, result
    assert "ghost" in result.stderr, result


# --- Phrase: "Missing or invalid vault ..." (invalid: no catalog.json)
def test_sync_directory_without_catalog_is_invalid(run, tmp_path):
    (tmp_path / "broken").mkdir()
    result = run("sync", "broken")
    assert result.returncode != 0, result
    assert "broken" in result.stderr, result


# --- Phrase: "Missing or invalid vault ..." (invalid: unparseable catalog)
def test_sync_unparseable_catalog_is_invalid(run, tmp_path):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "catalog.json").write_text("{not json")
    result = run("sync", "broken")
    assert result.returncode != 0, result
    assert "broken" in result.stderr, result


# --- Phrase: "Missing or invalid vault ..." (invalid: root schema violations)
@pytest.mark.parametrize(
    "catalog",
    [
        [],
        {"version": 3, "episodes": [], "streams": [], "clips": []},
        {"version": 3, "source": "u", "streams": [], "clips": []},
        {"version": 3, "source": "u", "episodes": {}, "streams": [], "clips": []},
        {"version": 3, "source": 5, "episodes": [], "streams": [], "clips": []},
    ],
)
def test_sync_rejects_catalogs_violating_root_schema(run, tmp_path, catalog):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "catalog.json").write_text(json.dumps(catalog))
    result = run("sync", "broken")
    assert result.returncode != 0, result
    assert "broken" in result.stderr, result


# --- Phrase: "| `version` | integer | `3` |" (context: required value, see
#     AMBIGUITIES T4; superseded for versions 1 and 2 by the Supported
#     Versions table, so only an unsupported version is rejected now)
def test_sync_rejects_wrong_catalog_version(run, tmp_path):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "catalog.json").write_text(
        json.dumps(
            {"version": 4, "source": "u", "episodes": [], "streams": [], "clips": []}
        )
    )
    result = run("sync", "broken")
    assert result.returncode != 0, result
    assert "broken" in result.stderr, result


# --- Phrase: "Each source entry must contain all nine fields above with the
#     stated types."
def test_first_sync_stores_static_fields_verbatim(run, source, vault, tmp_path):
    source.set_payload(
        payload(
            episodes=[
                entry("e1", published="2023-07-04T12:30:45", width=640, height=480)
            ]
        )
    )
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert stored["id"] == "e1"
    assert stored["published"] == "2023-07-04T12:30:45"
    assert stored["width"] == 640
    assert stored["height"] == 480


# --- Phrase: "| Tracked | `title` | history object | Values are strings |"
#     and the other five tracked field rows
def test_first_sync_creates_history_objects_for_tracked_fields(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    for field in TRACKED:
        assert isinstance(stored[field], dict), field
        assert len(stored[field]) == 1, field
        (key,) = list(stored[field])
        assert ISO.match(key), (field, key)


# --- Phrase: "| Static | ... | Tracked | ..." (context: stored entries carry
#     the ten documented fields plus `annotations`, which the Supported
#     Versions table lists as part of the native v3 shape -- see AMBIGUITIES
#     T9 and T12)
def test_stored_entry_field_set(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert set(stored) == {
        "id", "published", "width", "height", "annotations", *TRACKED
    }


# --- Phrase: "First observation | Add entry to matching category; create
#     initial history entry for all six tracked fields; set `removed` to
#     `false` at sync timestamp"
def test_first_observation_values(run, source, vault, tmp_path):
    source.set_payload(
        payload(
            episodes=[
                entry(
                    "e1",
                    title="T",
                    description="D",
                    views=7,
                    likes=3,
                    preview="p0",
                )
            ]
        )
    )
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert current(stored, "title") == "T"
    assert current(stored, "description") == "D"
    assert current(stored, "views") == 7
    assert current(stored, "likes") == 3
    assert current(stored, "preview") == "p0"
    assert current(stored, "removed") is False


# --- Phrase: "set `removed` to `false` at sync timestamp" (context: all six
#     initial history entries share the sync timestamp)
def test_first_observation_uses_one_sync_timestamp(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")], clips=[entry("c1")]))
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    keys = set()
    for eid, cat in (("e1", "episodes"), ("c1", "clips")):
        stored = find(catalog, eid, cat)
        for field in TRACKED:
            keys.update(stored[field])
    assert len(keys) == 1, keys


# --- Phrase: "| `likes` | integer or `null` | Current like count |"
def test_null_likes_is_accepted_on_first_observation(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", likes=None)]))
    assert run("sync", "vault").returncode == 0
    stored = find(read_catalog(tmp_path), "e1")
    assert current(stored, "likes") is None


# --- Phrase: "Success effect | Update catalog with new ... entries"
#     (context: entries added by later syncs join existing ones)
def test_later_sync_adds_new_entries(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", published="2024-01-02")]))
    run("sync", "vault")
    source.set_payload(
        payload(
            episodes=[
                entry("e1", published="2024-01-02"),
                entry("e2", published="2024-01-01"),
            ]
        )
    )
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert sorted(e["id"] for e in catalog["episodes"]) == ["e1", "e2"]
