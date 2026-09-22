"""Spec section: `sync` Command / `sync` Source Entry Schema / fetch failures."""

import json

import pytest

from conftest import read_catalog, source_entry

FETCH_FAILURE = "Source metadata fetch failure"


# Phrase: "Source request | HTTP `GET` to vault `source` URL"
def test_sync_requests_the_source_url(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    assert run_cli("sync", "demo").returncode == 0
    assert source.requests == 1


# Phrase: "Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays"
def test_sync_reads_all_three_categories(run_cli, source, vault):
    source.serve(
        episodes=[source_entry("e1")],
        streams=[source_entry("s1")],
        clips=[source_entry("c1")],
    )
    assert run_cli("sync", "demo").returncode == 0
    catalog = read_catalog(vault)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1"]
    assert [entry["id"] for entry in catalog["streams"]] == ["s1"]
    assert [entry["id"] for entry in catalog["clips"]] == ["c1"]


# Phrase: "Missing or invalid vault | Error to stderr including `<name>`; exit non-zero"
def test_sync_missing_vault_errors_with_name(run_cli):
    result = run_cli("sync", "ghost")
    assert result.returncode != 0
    assert "ghost" in result.stderr


@pytest.mark.parametrize(
    "catalog_text",
    [
        "{not json",
        "[]",
        json.dumps({"version": 3, "source": "http://example.test/f.json"}),
        json.dumps({"version": 3, "episodes": [], "streams": [], "clips": []}),
        json.dumps({"version": 3, "source": 5, "episodes": [], "streams": [], "clips": []}),
        json.dumps({"version": 3, "source": "u", "episodes": {}, "streams": [], "clips": []}),
        # v1 and v2 are supported now; a version outside the supported set is not.
        json.dumps({"version": 4, "source": "u", "episodes": [], "streams": [], "clips": []}),
        json.dumps({"source": "u", "episodes": [], "streams": [], "clips": []}),
    ],
)
# Phrase: "`sync` with invalid vault | stderr | non-zero | Message includes vault name" (see AMBIGUITIES T7)
def test_sync_invalid_vault_errors_with_name(run_cli, tmp_path, catalog_text):
    vault = tmp_path / "broken"
    vault.mkdir()
    (vault / "catalog.json").write_text(catalog_text)
    result = run_cli("sync", "broken")
    assert result.returncode != 0
    assert "broken" in result.stderr


# Phrase: "Vault input | Existing valid vault at `<name>/`" - directory without a catalog
def test_sync_directory_without_catalog_is_invalid(run_cli, tmp_path):
    (tmp_path / "bare").mkdir()
    result = run_cli("sync", "bare")
    assert result.returncode != 0
    assert "bare" in result.stderr


# Phrase: "Source metadata fetch failure | ... | Message includes `Source metadata fetch failure`"
def test_unreachable_source_reports_fetch_failure(run_cli, tmp_path):
    assert run_cli("init", "demo", "http://127.0.0.1:1/feed.json").returncode == 0
    result = run_cli("sync", "demo")
    assert result.returncode != 0
    assert FETCH_FAILURE in result.stderr


# Phrase: "Source metadata fetch failure" - unparseable body
def test_non_json_body_reports_fetch_failure(run_cli, source, vault):
    source.raw_body = b"<html>nope</html>"
    result = run_cli("sync", "demo")
    assert result.returncode != 0
    assert FETCH_FAILURE in result.stderr


# Phrase: "Source response shape | JSON object" - a JSON array is not an object
def test_non_object_payload_reports_fetch_failure(run_cli, source, vault):
    source.raw_body = json.dumps([1, 2, 3]).encode()
    result = run_cli("sync", "demo")
    assert result.returncode != 0
    assert FETCH_FAILURE in result.stderr


@pytest.mark.parametrize("missing", ["episodes", "streams", "clips"])
# Phrase: "JSON object with `episodes`, `streams`, and `clips` arrays" (see AMBIGUITIES T4)
def test_missing_category_array_reports_fetch_failure(run_cli, source, vault, missing):
    payload = {"episodes": [], "streams": [], "clips": []}
    del payload[missing]
    source.raw_body = json.dumps(payload).encode()
    result = run_cli("sync", "demo")
    assert result.returncode != 0
    assert FETCH_FAILURE in result.stderr


@pytest.mark.parametrize(
    "field",
    ["id", "published", "width", "height", "title", "description", "views", "likes", "preview"],
)
# Phrase: "Each source entry must contain all nine fields above with the stated types."
def test_missing_required_field_reports_fetch_failure(run_cli, source, vault, field):
    entry = source_entry("e1")
    del entry[field]
    source.serve(episodes=[entry])
    result = run_cli("sync", "demo")
    assert result.returncode != 0
    assert FETCH_FAILURE in result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 7),
        ("published", 20240101),
        ("width", "1920"),
        ("height", None),
        ("title", ["a"]),
        ("description", 3),
        ("views", "many"),
        ("likes", "5"),
        ("preview", None),
        ("views", True),  # see AMBIGUITIES T8
        ("width", 1920.5),
    ],
)
# Phrase: "If any source entry is missing a required field or has the wrong type, `sync` must fail"
def test_wrong_field_type_reports_fetch_failure(run_cli, source, vault, field, value):
    source.serve(streams=[source_entry("s1", **{field: value})])
    result = run_cli("sync", "demo")
    assert result.returncode != 0
    assert FETCH_FAILURE in result.stderr


# Phrase: "malformed source entries are included in this case" - a non-object entry
def test_non_object_entry_reports_fetch_failure(run_cli, source, vault):
    source.serve(clips=["just a string"])
    result = run_cli("sync", "demo")
    assert result.returncode != 0
    assert FETCH_FAILURE in result.stderr


# Phrase: "`likes` | integer or `null`" - null is accepted, not a type error
def test_null_likes_is_accepted(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", likes=None)])
    assert run_cli("sync", "demo").returncode == 0


# Phrase: "leave the vault unchanged"
def test_malformed_entry_leaves_vault_unchanged(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    assert run_cli("sync", "demo").returncode == 0
    before = (vault / "catalog.json").read_bytes()

    source.serve(episodes=[source_entry("e1", title="new"), source_entry("e2", views="nope")])
    assert run_cli("sync", "demo").returncode != 0
    assert (vault / "catalog.json").read_bytes() == before


# Phrase: "`published` | string | ISO 8601 datetime or date-only text"
def test_date_only_published_is_accepted(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", published="2024-01-05")])
    assert run_cli("sync", "demo").returncode == 0
