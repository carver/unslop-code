"""Spec sections: `sync` Command (source request), `sync` Source Entry Schema."""

import json

import pytest

from conftest import payload, read_catalog, source_entry

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
    ("id", 17),
    ("published", 20240101),
    ("width", "1920"),
    ("height", None),
    ("title", ["a"]),
    ("description", 5),
    ("views", "10"),
    ("likes", "2"),
    ("preview", {"hash": "x"}),
]


# Spec: Source request | HTTP `GET` to vault `source` URL
def test_sync_issues_get_to_source_url(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    assert run("sync", "vault").returncode == 0
    assert source.request_count == 1
    assert set(source.methods) == {"GET"}


# Spec: Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays
def test_sync_reads_all_three_categories(run, source, vault):
    source.serve(
        payload(
            episodes=[source_entry("e1")],
            streams=[source_entry("s1")],
            clips=[source_entry("c1")],
        )
    )
    run("sync", "vault")
    catalog = read_catalog(vault)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Spec: Each source entry must contain all nine fields above with the stated types.
@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_missing_required_field_fails_sync(run, source, vault, field):
    entry = source_entry("e1")
    del entry[field]
    source.serve(payload(episodes=[entry]))

    result = run("sync", "vault")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: ... or has the wrong type, `sync` must fail as a source metadata fetch failure
@pytest.mark.parametrize("field,value", WRONG_TYPES)
def test_wrong_field_type_fails_sync(run, source, vault, field, value):
    source.serve(payload(episodes=[source_entry("e1", **{field: value})]))

    result = run("sync", "vault")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: `likes` | integer or `null` (null is valid, unlike for other numeric fields)
def test_null_likes_is_accepted(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", likes=None)]))
    assert run("sync", "vault").returncode == 0


# Spec: `published` | string | ISO 8601 datetime or date-only text
def test_date_only_published_is_accepted(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", published="2024-03-05")]))
    assert run("sync", "vault").returncode == 0


# Spec: `published` ... ISO 8601 (T13: unparseable text is malformed source data)
def test_unparseable_published_fails_sync(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", published="sometime soon")]))
    assert run("sync", "vault").returncode != 0


# Spec: ... must ... leave the vault unchanged.
def test_malformed_entry_leaves_vault_unchanged(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    before = (vault / "catalog.json").read_bytes()

    source.serve(payload(episodes=[source_entry("e1", views="many"), source_entry("e2")]))
    assert run("sync", "vault").returncode != 0
    assert (vault / "catalog.json").read_bytes() == before


# Spec: ... malformed source entries are included in this case (validated before any write)
def test_first_sync_with_malformed_entry_leaves_empty_catalog(run, source, vault):
    source.serve(payload(episodes=[source_entry("ok"), source_entry("bad", height=None)]))
    assert run("sync", "vault").returncode != 0
    assert read_catalog(vault)["episodes"] == []


# Spec: Source metadata fetch failure (T6: booleans are not integers)
@pytest.mark.parametrize("field", ["width", "height", "views", "likes"])
def test_boolean_is_not_an_integer(run, source, vault, field):
    source.serve(payload(episodes=[source_entry("e1", **{field: True})]))
    assert run("sync", "vault").returncode != 0


# Spec: Each source entry must contain all nine fields (an entry must be an object)
def test_non_object_source_entry_fails_sync(run, source, vault):
    source.serve(payload(episodes=["e1"]))
    assert run("sync", "vault").returncode != 0


# Spec: Source response shape ... (T3: a missing category array is a fetch failure)
@pytest.mark.parametrize("missing", ["episodes", "streams", "clips"])
def test_missing_category_array_fails_sync(run, source, vault, missing):
    body = payload()
    del body[missing]
    source.serve(body)
    assert run("sync", "vault").returncode != 0


# Spec: Source response shape | JSON object with ... arrays (wrong container type)
def test_non_array_category_fails_sync(run, source, vault):
    source.serve({"episodes": {}, "streams": [], "clips": []})
    assert run("sync", "vault").returncode != 0


# Spec: Source response shape | JSON object ...
def test_non_object_response_fails_sync(run, source, vault):
    source.serve([source_entry("e1")])
    assert run("sync", "vault").returncode != 0


# Spec: Source metadata fetch failure | stderr | non-zero | Error message
def test_invalid_json_body_fails_sync(run, source, vault):
    source.serve_raw("{not json at all")
    result = run("sync", "vault")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Source metadata fetch failure (T8: non-2xx status counts)
def test_http_error_status_fails_sync(run, source, vault):
    source.serve_raw(json.dumps(payload()), status=500)
    result = run("sync", "vault")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Source metadata fetch failure (T8: transport errors count)
def test_unreachable_source_fails_sync(run, tmp_path, dead_url):
    run("init", "vault", dead_url)
    result = run("sync", "vault")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert read_catalog(tmp_path / "vault")["episodes"] == []


# Spec: Each source entry must contain all nine fields (T7: extras are ignored)
def test_extra_source_fields_are_ignored(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", extra="junk", removed=True)]))
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    assert "extra" not in stored
    assert stored["removed"] == {max(stored["removed"]): False}
