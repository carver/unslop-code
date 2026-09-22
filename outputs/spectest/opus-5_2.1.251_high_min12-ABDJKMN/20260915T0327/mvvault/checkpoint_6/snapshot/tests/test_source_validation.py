"""Spec sections: `sync` Source Entry Schema (validation) and
`mvault` Error Handling -> "Source metadata fetch failure"."""
import json

import pytest

from conftest import entry, payload, read_catalog

REQUIRED = [
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


def _catalog_bytes(tmp_path, name="vault"):
    return (tmp_path / name / "catalog.json").read_bytes()


# --- Phrase: "If any source entry is missing a required field ... `sync` must
#     fail as a source metadata fetch failure and leave the vault unchanged."
@pytest.mark.parametrize("missing", REQUIRED)
def test_missing_required_field_fails(run, source, vault, tmp_path, missing):
    bad = entry("e1")
    del bad[missing]
    source.set_payload(payload(episodes=[bad]))
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result
    assert _catalog_bytes(tmp_path) == before


# --- Phrase: "... or has the wrong type, `sync` must fail as a source metadata
#     fetch failure and leave the vault unchanged."
@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 5),
        ("id", None),
        ("published", 20240101),
        ("published", None),
        ("width", "1920"),
        ("width", None),
        ("width", 19.2),
        ("height", "1080"),
        ("title", 12),
        ("title", None),
        ("description", []),
        ("description", None),
        ("views", "100"),
        ("views", None),
        ("views", 10.5),
        ("likes", "10"),
        ("likes", []),
        ("preview", 99),
        ("preview", None),
    ],
)
def test_wrong_field_type_fails(run, source, vault, tmp_path, field, value):
    source.set_payload(payload(episodes=[entry("e1", **{field: value})]))
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert _catalog_bytes(tmp_path) == before


# --- Phrase: "| `width` | integer |" (context: JSON booleans are not integers,
#     see AMBIGUITIES T8)
@pytest.mark.parametrize("field", ["width", "height", "views", "likes"])
def test_boolean_is_not_an_integer(run, source, vault, tmp_path, field):
    source.set_payload(payload(episodes=[entry("e1", **{field: True})]))
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert _catalog_bytes(tmp_path) == before


# --- Phrase: "If any source entry is missing a required field" (context: a bad
#     entry anywhere in any category poisons the whole sync)
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_bad_entry_in_any_category_fails_whole_sync(
    run, source, vault, tmp_path, category
):
    good = {"episodes": [entry("e1")], "streams": [entry("s1")], "clips": []}
    bad = entry("x1")
    del bad["views"]
    good[category] = good.get(category, []) + [bad]
    source.set_payload(payload(**good))
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert _catalog_bytes(tmp_path) == before


# --- Phrase: "leave the vault unchanged" (context: a failed sync after a
#     successful one must not append history or write a backup)
def test_failed_sync_after_success_leaves_catalog_untouched(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")]))
    assert run("sync", "vault").returncode == 0
    before = _catalog_bytes(tmp_path)
    bad = entry("e1")
    bad["likes"] = "many"
    source.set_payload(payload(episodes=[bad]))
    assert run("sync", "vault").returncode != 0
    assert _catalog_bytes(tmp_path) == before


# --- Phrase: "Source metadata fetch failure | stderr | non-zero | Error
#     message" (context: transport-level failures, see AMBIGUITIES T10)
def test_http_error_status_is_a_fetch_failure(run, source, vault, tmp_path):
    source.set_raw("gone", status=500)
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result
    assert _catalog_bytes(tmp_path) == before


def test_unreachable_source_is_a_fetch_failure(run, tmp_path):
    assert run("init", "vault", "http://127.0.0.1:9/none.json").returncode == 0
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result
    assert _catalog_bytes(tmp_path) == before


def test_non_json_body_is_a_fetch_failure(run, source, vault, tmp_path):
    source.set_raw("<html>nope</html>", content_type="text/html")
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert _catalog_bytes(tmp_path) == before


# --- Phrase: "Source response shape | JSON object with `episodes`, `streams`,
#     and `clips` arrays" (see AMBIGUITIES T5)
@pytest.mark.parametrize(
    "body",
    [
        [],
        "\"text\"",
        {"episodes": [], "streams": []},
        {"episodes": [], "streams": [], "clips": {}},
        {"episodes": {}, "streams": [], "clips": []},
    ],
)
def test_malformed_response_shape_is_a_fetch_failure(
    run, source, vault, tmp_path, body
):
    source.set_raw(body if isinstance(body, str) else json.dumps(body))
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert _catalog_bytes(tmp_path) == before


# --- Phrase: "Each source entry must contain all nine fields above with the
#     stated types." (context: a non-object element is not a valid entry)
@pytest.mark.parametrize("element", ["e1", 5, None, ["e1"]])
def test_non_object_source_entry_fails(run, source, vault, tmp_path, element):
    source.set_raw(json.dumps({"episodes": [element], "streams": [], "clips": []}))
    before = _catalog_bytes(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert _catalog_bytes(tmp_path) == before


# --- Phrase: "Each source entry must contain all nine fields above" (context:
#     unknown extra fields are not forbidden and are simply not stored)
def test_extra_source_fields_are_ignored(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", extra="junk", tags=[1, 2])]))
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert "extra" not in stored and "tags" not in stored
