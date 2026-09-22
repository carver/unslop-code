"""Spec: `sync` Command (input/request/response) and `sync` Source Entry Schema."""
import json
import os

import pytest

from conftest import make_entry, read_catalog, find_entry, current


# Spec: "| Syntax | `python mvault.py sync <name>` |" +
# "| Vault input | Existing valid vault at `<name>/` |"
def test_sync_succeeds_on_valid_vault(run, source, vault):
    source.serve(episodes=[make_entry(id="a")])
    res = run("sync", "vault")
    assert res.returncode == 0, res


# Spec: "| Source request | HTTP `GET` to vault `source` URL |"
def test_sync_issues_http_get_to_source_url(run, source, vault):
    source.serve()
    run("sync", "vault")
    assert source.requests, "no request reached the source server"
    methods = {method for method, _ in source.requests}
    assert methods == {"GET"}
    assert source.requests[0][1].endswith("/source.json")


# Spec: "Source request | HTTP GET to vault `source` URL" -- the URL comes from
# the catalog's `source` field, not from the command line.
def test_sync_uses_source_url_recorded_in_catalog(run, source, tmp_path):
    run("init", "vault", source.url)
    source.serve(clips=[make_entry(id="c1")])
    run("sync", "vault")
    assert find_entry(read_catalog(tmp_path), "clips", "c1") is not None


# Spec: "| Source response shape | JSON object with `episodes`, `streams`, and
# `clips` arrays |"
def test_sync_reads_all_three_categories(run, source, tmp_path, vault):
    source.serve(
        episodes=[make_entry(id="e1")],
        streams=[make_entry(id="s1")],
        clips=[make_entry(id="c1")],
    )
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Spec: "| Missing or invalid vault | Error to stderr including `<name>`; exit
# non-zero |" -- non-existent vault (also Error Handling: "sync with
# non-existent vault").
def test_sync_missing_vault_errors_with_name(run, tmp_path):
    res = run("sync", "ghost")
    assert res.returncode != 0
    assert "ghost" in res.stderr
    assert res.stdout == ""


# Spec: "sync with invalid vault | stderr | non-zero | Message includes vault
# name" -- directory exists but has no catalog.json.
def test_sync_vault_without_catalog_is_invalid(run, tmp_path):
    (tmp_path / "shell").mkdir()
    res = run("sync", "shell")
    assert res.returncode != 0
    assert "shell" in res.stderr


# Spec: "sync with invalid vault" -- unparseable catalog.json.
def test_sync_corrupt_catalog_is_invalid(run, tmp_path):
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "catalog.json").write_text("{not json")
    res = run("sync", "broken")
    assert res.returncode != 0
    assert "broken" in res.stderr


# Spec: "sync with invalid vault" + Root Schema (missing category arrays).
@pytest.mark.parametrize("missing", ["episodes", "streams", "clips", "source", "version"])
def test_sync_catalog_missing_root_field_is_invalid(run, tmp_path, missing):
    bad = tmp_path / "part"
    bad.mkdir()
    catalog = {
        "version": 3,
        "source": "http://example.invalid/s.json",
        "episodes": [],
        "streams": [],
        "clips": [],
    }
    del catalog[missing]
    (bad / "catalog.json").write_text(json.dumps(catalog))
    res = run("sync", "part")
    assert res.returncode != 0
    assert "part" in res.stderr


# Spec: "| `version` greater than `3` | Version-related error to stderr; exit
# non-zero; ... |" -- superseded the earlier "version must be 3" reading: v1 and
# v2 are now loaded transparently (see AMBIGUITIES T3 addendum), and only an
# unsupported version makes the vault invalid.
def test_sync_catalog_with_unsupported_version_is_invalid(run, tmp_path):
    bad = tmp_path / "oldv"
    bad.mkdir()
    (bad / "catalog.json").write_text(json.dumps({
        "version": 4,
        "source": "http://example.invalid/s.json",
        "episodes": [], "streams": [], "clips": [],
    }))
    res = run("sync", "oldv")
    assert res.returncode != 0
    assert "oldv" in res.stderr


# Spec: "Syntax | `python mvault.py sync <name>`" -- the name operand is
# required.
def test_sync_requires_name(run):
    res = run("sync")
    assert res.returncode != 0
    assert res.stderr != ""


# ---------------------------------------------------------------------------
# Source Entry Schema: the nine required fields and their types.
# Spec: "Each source entry must contain all nine fields above with the stated
# types."
# ---------------------------------------------------------------------------
NINE_FIELDS = [
    "id", "published", "width", "height",
    "title", "description", "views", "likes", "preview",
]


# Spec: "If any source entry is missing a required field ... `sync` must fail as
# a source metadata fetch failure and leave the vault unchanged."
@pytest.mark.parametrize("field", NINE_FIELDS)
def test_sync_missing_source_field_fails(run, source, tmp_path, vault, field):
    broken = make_entry(id="x")
    del broken[field]
    source.serve(episodes=[broken])
    before = read_catalog(tmp_path)

    res = run("sync", "vault")

    assert res.returncode != 0
    assert res.stderr != ""
    assert read_catalog(tmp_path) == before


# Spec: Source Entry Schema types -- "| `id` | string |",
# "| `published` | string |", "| `title` | string |",
# "| `description` | string |", "| `preview` | string |".
@pytest.mark.parametrize("field", ["id", "published", "title", "description", "preview"])
@pytest.mark.parametrize("value", [1, None, [], {}, True])
def test_sync_string_field_wrong_type_fails(run, source, tmp_path, vault, field, value):
    broken = make_entry(id="x")
    broken[field] = value
    source.serve(episodes=[broken])
    before = read_catalog(tmp_path)

    res = run("sync", "vault")

    assert res.returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "| `width` | integer |", "| `height` | integer |", "| `views` | integer |".
@pytest.mark.parametrize("field", ["width", "height", "views"])
@pytest.mark.parametrize("value", ["1080", None, 1.5, [], {}])
def test_sync_integer_field_wrong_type_fails(run, source, tmp_path, vault, field, value):
    broken = make_entry(id="x")
    broken[field] = value
    source.serve(episodes=[broken])
    before = read_catalog(tmp_path)

    res = run("sync", "vault")

    assert res.returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "| `likes` | integer or `null` |" -- anything else is the wrong type.
@pytest.mark.parametrize("value", ["12", 1.5, [], {}])
def test_sync_likes_wrong_type_fails(run, source, tmp_path, vault, value):
    broken = make_entry(id="x", likes=value)
    source.serve(episodes=[broken])
    before = read_catalog(tmp_path)

    res = run("sync", "vault")

    assert res.returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "| `likes` | integer or `null` |" -- both accepted forms sync cleanly.
@pytest.mark.parametrize("value", [0, 42, None])
def test_sync_likes_accepts_integer_or_null(run, source, tmp_path, vault, value):
    source.serve(episodes=[make_entry(id="x", likes=value)])
    assert run("sync", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "x")
    assert current(entry["likes"]) == value


# Spec: integer fields are integers -- JSON booleans are a different JSON type
# (see AMBIGUITIES T5).
@pytest.mark.parametrize("field", ["width", "height", "views", "likes"])
def test_sync_boolean_for_integer_field_fails(run, source, tmp_path, vault, field):
    broken = make_entry(id="x")
    broken[field] = True
    source.serve(episodes=[broken])
    before = read_catalog(tmp_path)

    res = run("sync", "vault")

    assert res.returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "If any source entry is missing a required field ..." -- one bad entry
# poisons the whole sync, including entries in other categories.
def test_one_bad_entry_aborts_entire_sync(run, source, tmp_path, vault):
    bad = make_entry(id="bad")
    del bad["views"]
    source.serve(episodes=[make_entry(id="good")], clips=[bad])
    before = read_catalog(tmp_path)

    assert run("sync", "vault").returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "Source metadata fetch failure | stderr | non-zero | Error message;
# malformed source entries are included in this case" -- transport/status error.
def test_sync_http_error_is_fetch_failure(run, source, tmp_path, vault):
    source.fail(status=500)
    before = read_catalog(tmp_path)

    res = run("sync", "vault")

    assert res.returncode != 0
    assert res.stderr != ""
    assert read_catalog(tmp_path) == before


# Spec: "Source metadata fetch failure" -- unreachable source URL.
def test_sync_unreachable_source_is_fetch_failure(run, tmp_path):
    run("init", "vault", "http://127.0.0.1:9/never.json")
    before = read_catalog(tmp_path)

    res = run("sync", "vault")

    assert res.returncode != 0
    assert res.stderr != ""
    assert read_catalog(tmp_path) == before


# Spec: "Source response shape | JSON object ..." -- a body that is not JSON.
def test_sync_non_json_body_is_fetch_failure(run, source, tmp_path, vault):
    source.serve_raw(b"<html>nope</html>")
    before = read_catalog(tmp_path)

    res = run("sync", "vault")

    assert res.returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "Source response shape | JSON object with ... arrays" -- a JSON array
# (not object) at the top level.
def test_sync_non_object_json_is_fetch_failure(run, source, tmp_path, vault):
    source.serve_raw(b"[1, 2, 3]")
    before = read_catalog(tmp_path)

    assert run("sync", "vault").returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "Source response shape | JSON object with `episodes`, `streams`, and
# `clips` arrays" -- a missing category array (see AMBIGUITIES T4).
@pytest.mark.parametrize("missing", ["episodes", "streams", "clips"])
def test_sync_missing_category_array_is_fetch_failure(run, source, tmp_path, vault, missing):
    payload = {"episodes": [], "streams": [], "clips": []}
    del payload[missing]
    source.serve_object(payload)
    before = read_catalog(tmp_path)

    assert run("sync", "vault").returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "... with `episodes`, `streams`, and `clips` arrays" -- present but not
# an array.
def test_sync_category_not_an_array_is_fetch_failure(run, source, tmp_path, vault):
    source.serve_object({"episodes": {"id": "x"}, "streams": [], "clips": []})
    before = read_catalog(tmp_path)

    assert run("sync", "vault").returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: entries are objects carrying the nine fields.
def test_sync_non_object_entry_is_fetch_failure(run, source, tmp_path, vault):
    source.serve_object({"episodes": ["just-a-string"], "streams": [], "clips": []})
    before = read_catalog(tmp_path)

    assert run("sync", "vault").returncode != 0
    assert read_catalog(tmp_path) == before


# Spec: "leave the vault unchanged" -- a failed sync must not leave a stale
# backup either, since no write happened.
def test_failed_sync_writes_nothing(run, source, tmp_path, vault):
    source.fail(status=404)
    assert run("sync", "vault").returncode != 0
    assert not (tmp_path / "vault" / "catalog.bak").exists()
