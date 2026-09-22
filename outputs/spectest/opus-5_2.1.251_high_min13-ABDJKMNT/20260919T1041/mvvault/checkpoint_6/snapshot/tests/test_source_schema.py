"""`sync` Source Entry Schema and source metadata fetch failures."""

import json

import pytest

from conftest import read_catalog, source_entry

REQUIRED_FIELDS = [
    "id",
    "published",
    "width",
    "height",
    "title",
    "description",
    "views",
    "likes",
    "preview",
]

WRONG_TYPES = [
    ("id", 7),
    ("published", 20240101),
    ("width", "1920"),
    ("height", 1080.5),
    ("title", None),
    ("description", ["text"]),
    ("views", "many"),
    ("likes", "none"),
    ("preview", 42),
]


# Spec: Source request | HTTP `GET` to vault `source` URL
def test_sync_requests_the_source_url(run_cli, vault, source):
    source.payload = {"episodes": [source_entry("a")], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    assert source.requests == 1


# Spec: Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays
def test_sync_accepts_the_documented_response_shape(run_cli, vault, source):
    source.payload = {
        "episodes": [source_entry("e1")],
        "streams": [source_entry("s1")],
        "clips": [source_entry("c1")],
    }
    assert run_cli("sync", "v").returncode == 0
    catalog = read_catalog(vault)
    assert [len(catalog[name]) for name in ("episodes", "streams", "clips")] == [1, 1, 1]


# Spec: Each source entry must contain all nine fields above with the stated types.
@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_missing_required_field_fails_sync(run_cli, vault, source, field):
    entry = source_entry("a")
    del entry[field]
    source.payload = {"episodes": [entry], "streams": [], "clips": []}

    result = run_cli("sync", "v")

    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: If any source entry ... has the wrong type, `sync` must fail as a source
# metadata fetch failure
@pytest.mark.parametrize("field,value", WRONG_TYPES)
def test_wrong_field_type_fails_sync(run_cli, vault, source, field, value):
    source.payload = {
        "episodes": [source_entry("a", **{field: value})],
        "streams": [],
        "clips": [],
    }

    result = run_cli("sync", "v")

    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: ... and leave the vault unchanged.
def test_malformed_entry_leaves_vault_unchanged(run_cli, vault, source):
    source.payload = {"episodes": [source_entry("a")], "streams": [], "clips": []}
    run_cli("sync", "v")
    before = (vault / "catalog.json").read_bytes()

    source.payload = {"episodes": [{"id": "a"}], "streams": [], "clips": []}
    result = run_cli("sync", "v")

    assert result.returncode != 0
    assert (vault / "catalog.json").read_bytes() == before


# Spec: `likes` | integer or `null`
def test_null_likes_is_accepted(run_cli, vault, source):
    source.payload = {"episodes": [source_entry("a", likes=None)], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0


# Spec: `published` | string | ISO 8601 datetime or date-only text
@pytest.mark.parametrize("published", ["2024-05-04", "2024-05-04T12:30:00"])
def test_both_published_shapes_are_accepted(run_cli, vault, source, published):
    source.payload = {
        "episodes": [source_entry("a", published=published)],
        "streams": [],
        "clips": [],
    }
    assert run_cli("sync", "v").returncode == 0


# Spec: Source metadata fetch failure | stderr | non-zero | Error message
def test_unreachable_source_fails(run_cli, tmp_path, source):
    run_cli("init", "dead", "http://127.0.0.1:1/nope.json")
    result = run_cli("sync", "dead")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Source metadata fetch failure (HTTP error status)
def test_http_error_status_fails(run_cli, vault, source):
    source.status = 500
    result = run_cli("sync", "v")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Source metadata fetch failure (body is not JSON)
def test_non_json_body_fails(run_cli, vault, source):
    source.body = "<html>nope</html>"
    result = run_cli("sync", "v")
    assert result.returncode != 0


# Spec: Source response shape | JSON object with ... arrays (top level is not an object)
def test_non_object_payload_fails(run_cli, vault, source):
    source.body = json.dumps([source_entry("a")])
    result = run_cli("sync", "v")
    assert result.returncode != 0


# Spec: Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays
# See AMBIGUITIES T3: a payload missing a category array is a fetch failure.
def test_missing_category_array_fails(run_cli, vault, source):
    source.body = json.dumps({"episodes": [], "streams": []})
    result = run_cli("sync", "v")
    assert result.returncode != 0


# Spec: ... `episodes`, `streams`, and `clips` arrays (category value is not an array)
def test_non_array_category_fails(run_cli, vault, source):
    source.body = json.dumps({"episodes": {}, "streams": [], "clips": []})
    assert run_cli("sync", "v").returncode != 0


# Spec: If any source entry is missing a required field (entry is not an object)
def test_non_object_entry_fails(run_cli, vault, source):
    source.body = json.dumps({"episodes": ["a"], "streams": [], "clips": []})
    assert run_cli("sync", "v").returncode != 0


# See AMBIGUITIES T9: JSON booleans are not integers.
@pytest.mark.parametrize("field", ["width", "height", "views", "likes"])
def test_boolean_is_not_an_integer(run_cli, vault, source, field):
    source.payload = {
        "episodes": [source_entry("a", **{field: True})],
        "streams": [],
        "clips": [],
    }
    assert run_cli("sync", "v").returncode != 0


# See AMBIGUITIES T5: unparseable `published` text is malformed source metadata.
def test_unparseable_published_fails(run_cli, vault, source):
    source.payload = {
        "episodes": [source_entry("a", published="last tuesday")],
        "streams": [],
        "clips": [],
    }
    assert run_cli("sync", "v").returncode != 0


# Spec: Local-only fields | Source data does not include `removed` or `annotations`
def test_source_removed_field_does_not_override_local_history(run_cli, vault, source):
    entry = source_entry("a")
    entry["removed"] = True
    source.payload = {"episodes": [entry], "streams": [], "clips": []}

    assert run_cli("sync", "v").returncode == 0
    history = read_catalog(vault)["episodes"][0]["removed"]
    assert list(history.values()) == [False]
