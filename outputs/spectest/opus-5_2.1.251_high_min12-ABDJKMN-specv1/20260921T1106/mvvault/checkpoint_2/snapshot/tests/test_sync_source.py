"""Spec sections: `sync` Command / `sync` Source Entry Schema / fetch failures."""
import json
import os

import pytest
from conftest import dead_url, entry, payload, read_bytes, read_catalog


def init(run, source, name="v"):
    result = run("init", name, source.url)
    assert result.returncode == 0, result.stderr
    return name


# Phrase: "Source request | HTTP `GET` to vault `source` URL,
#          made with `urllib.request`"
def test_sync_issues_http_get_to_source_url(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1")])
    result = run("sync", "v")
    assert result.returncode == 0, result.stderr
    assert source.requests, "sync made no HTTP request"
    assert source.requests[0][0] == "GET"
    assert source.requests[0][1] == "/feed.json"


# Phrase: "Source response shape | JSON object with `episodes`, `streams`,
#          and `clips` arrays"
def test_sync_consumes_all_three_category_arrays(run, source, tmp_path):
    init(run, source)
    source.payload = payload(
        episodes=[entry("e1")], streams=[entry("s1")], clips=[entry("c1")]
    )
    assert run("sync", "v").returncode == 0
    catalog = read_catalog(tmp_path / "v")
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Phrase: "Missing or invalid vault | Error to stderr including `<name>`;
#          exit non-zero"
# Context: the vault directory does not exist at all.
def test_sync_missing_vault_errors_with_name(run, tmp_path):
    result = run("sync", "nosuchvault")
    assert result.returncode != 0
    assert "nosuchvault" in result.stderr
    assert "nosuchvault" not in result.stdout


# Phrase: "`sync` with invalid vault | stderr | non-zero | Message includes
#          vault name"
# Context: the directory exists but has no catalog.json.
def test_sync_vault_without_catalog_is_invalid(run, tmp_path):
    (tmp_path / "broken").mkdir()
    result = run("sync", "broken")
    assert result.returncode != 0
    assert "broken" in result.stderr


# Phrase: "`sync` with invalid vault" — catalog.json is not parseable JSON.
def test_sync_unparseable_catalog_is_invalid(run, tmp_path):
    vault = tmp_path / "broken"
    vault.mkdir()
    (vault / "catalog.json").write_text("{not json", encoding="utf-8")
    result = run("sync", "broken")
    assert result.returncode != 0
    assert "broken" in result.stderr


# Phrase: "`catalog.json` Root Schema" — a catalog missing a required category
# is not a valid vault. Context: see AMBIGUITIES.md T4. A well-formed
# `version: 2` catalog is no longer in this list: the multi-version spec makes
# it loadable ("| `2` | Supported |"), so it is covered by the legacy tests.
@pytest.mark.parametrize(
    "catalog",
    [
        {"version": 3, "source": "http://x.invalid", "episodes": [], "streams": []},
        {"version": 3, "source": "http://x.invalid", "episodes": [], "streams": [], "clips": {}},
        {"version": 3, "episodes": [], "streams": [], "clips": []},
        [],
    ],
)
def test_sync_rejects_malformed_catalog(run, tmp_path, catalog):
    vault = tmp_path / "broken"
    vault.mkdir()
    (vault / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    result = run("sync", "broken")
    assert result.returncode != 0
    assert "broken" in result.stderr


# Phrase: "Source metadata fetch failure | stderr | non-zero | Message includes
#          `Source metadata fetch failure`"
# Context: nothing is listening on the source URL.
def test_sync_unreachable_source_reports_fetch_failure(run, tmp_path):
    assert run("init", "v", dead_url()).returncode == 0
    result = run("sync", "v")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Phrase: "Source metadata fetch failure" — HTTP error status.
def test_sync_http_error_status_is_fetch_failure(run, source):
    assert run("init", "v", source.url).returncode == 0
    source.status = 500
    result = run("sync", "v")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Phrase: "Source metadata fetch failure" — body is not JSON.
def test_sync_non_json_body_is_fetch_failure(run, source):
    assert run("init", "v", source.url).returncode == 0
    source.body = b"<html>nope</html>"
    result = run("sync", "v")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Phrase: "Source response shape | JSON object with ... arrays"
# Context: a response that is not an object, or whose categories are not
# arrays, cannot be consumed. See AMBIGUITIES.md T5.
@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b'{"episodes": [], "streams": []}',
        b'{"episodes": {}, "streams": [], "clips": []}',
        b'{"episodes": [], "streams": [], "clips": "none"}',
    ],
)
def test_sync_bad_response_shape_is_fetch_failure(run, source, body):
    assert run("init", "v", source.url).returncode == 0
    source.body = body
    result = run("sync", "v")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Phrase: "Each source entry must contain all nine fields above with the stated
#          types. If any source entry is missing a required field ... `sync`
#          must fail as a source metadata fetch failure"
@pytest.mark.parametrize(
    "missing",
    ["id", "published", "width", "height", "title", "description", "views",
     "likes", "preview"],
)
def test_sync_missing_required_field_is_fetch_failure(run, source, missing):
    assert run("init", "v", source.url).returncode == 0
    bad = entry("e1")
    del bad[missing]
    source.payload = payload(episodes=[bad])
    result = run("sync", "v")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Phrase: "... or has the wrong type, `sync` must fail as a source metadata
#          fetch failure"
@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 7),
        ("published", 20240101),
        ("width", "1920"),
        ("height", 1080.5),
        ("title", None),
        ("description", ["d"]),
        ("views", "10"),
        ("likes", "5"),
        ("preview", 42),
    ],
)
def test_sync_wrong_type_is_fetch_failure(run, source, field, value):
    assert run("init", "v", source.url).returncode == 0
    bad = entry("e1")
    bad[field] = value
    source.payload = payload(episodes=[bad])
    result = run("sync", "v")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Phrase: "`likes` | integer or `null`"
# Context: null is a valid likes value, not a missing field.
def test_sync_accepts_null_likes(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1", likes=None)])
    assert run("sync", "v").returncode == 0
    catalog = read_catalog(tmp_path / "v")
    history = catalog["episodes"][0]["likes"]
    assert list(history.values()) == [None]


# Phrase: "Each source entry must contain all nine fields"
# Context: a non-object entry cannot carry the required fields.
def test_sync_non_object_entry_is_fetch_failure(run, source):
    assert run("init", "v", source.url).returncode == 0
    source.body = b'{"episodes": ["e1"], "streams": [], "clips": []}'
    result = run("sync", "v")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Phrase: "malformed source entries are included in this case" +
#         "leave the vault unchanged"
def test_failed_sync_leaves_vault_byte_for_byte_unchanged(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1")])
    assert run("sync", "v").returncode == 0
    vault = tmp_path / "v"
    before = {name: read_bytes(vault / name) for name in sorted(os.listdir(str(vault)))}

    bad = entry("e2")
    del bad["views"]
    source.payload = payload(episodes=[entry("e1", title="changed"), bad])
    result = run("sync", "v")

    assert result.returncode != 0
    after = {name: read_bytes(vault / name) for name in sorted(os.listdir(str(vault)))}
    assert after == before


# Phrase: "Source metadata fetch failure | stderr"
# Context: nothing is written to stdout on the failure path.
def test_fetch_failure_message_not_on_stdout(run, tmp_path):
    assert run("init", "v", dead_url()).returncode == 0
    result = run("sync", "v")
    assert "Source metadata fetch failure" not in result.stdout


# Phrase: "Source data does not include `removed` or `annotations`"
# Context: unknown extra fields in a source entry are ignored, not stored; the
# entry `sync` creates carries the v3-shape `annotations: []` of its own
# ("Entries created by `sync` | Written in v3 shape, with `annotations` as
# `[]`"), never the source's value.
def test_extra_source_fields_are_ignored(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    extra = entry("e1")
    extra["annotations"] = ["hi"]
    extra["removed"] = True
    source.payload = payload(episodes=[extra])
    assert run("sync", "v").returncode == 0
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    assert stored["annotations"] == []
    assert list(stored["removed"].values()) == [False]
