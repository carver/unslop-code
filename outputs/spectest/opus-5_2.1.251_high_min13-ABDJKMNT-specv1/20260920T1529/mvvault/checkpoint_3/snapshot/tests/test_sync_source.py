"""Spec sections: `sync` Command / `sync` Source Entry Schema / fetch failures."""

import json

import pytest

from conftest import payload, read_catalog, run_cli, source_entry


# `sync` Command: "Source request | HTTP `GET` to vault `source` URL, made with
# `urllib.request`".
def test_sync_issues_a_get_to_the_vault_source_url(vault, source):
    source.serve(payload())
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode == 0, result.stderr
    assert source.requests == ["/source.json"]


# `sync` Command: "Success effect | Update catalog with new, changed, removed,
# and restored entries" — a successful sync exits zero.
def test_sync_exits_zero_on_success(vault, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    assert run_cli("sync", "demo", cwd=vault.parent).returncode == 0


# `sync` Command: "Source response shape | JSON object with `episodes`,
# `streams`, and `clips` arrays".
def test_sync_reads_all_three_categories(vault, source):
    source.serve(
        payload(
            episodes=[source_entry("e1")],
            streams=[source_entry("s1")],
            clips=[source_entry("c1")],
        )
    )
    run_cli("sync", "demo", cwd=vault.parent)

    catalog = read_catalog(vault)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# `sync` Command: "Missing or invalid vault | Error to stderr including
# `<name>`; exit non-zero" — vault directory does not exist.
def test_sync_on_missing_vault_errors_with_the_name(tmp_path):
    result = run_cli("sync", "ghost", cwd=tmp_path)
    assert result.returncode != 0
    assert "ghost" in result.stderr


# "Missing or invalid vault" — directory exists but holds no catalog.json.
def test_sync_on_directory_without_catalog_errors_with_the_name(tmp_path):
    (tmp_path / "demo").mkdir()
    result = run_cli("sync", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert "demo" in result.stderr


# "Missing or invalid vault" — catalog.json is not parseable JSON.
def test_sync_on_corrupt_catalog_errors_with_the_name(tmp_path):
    vault = tmp_path / "demo"
    vault.mkdir()
    (vault / "catalog.json").write_text("{not json")
    result = run_cli("sync", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert "demo" in result.stderr


# "Missing or invalid vault" — catalog.json does not satisfy the root schema.
@pytest.mark.parametrize(
    "catalog",
    [
        {"version": 3, "source": "http://example.invalid/f.json", "episodes": [], "streams": []},
        {"version": 3, "source": 42, "episodes": [], "streams": [], "clips": []},
        {"version": 3, "source": "u", "episodes": {}, "streams": [], "clips": []},
        {"source": "u", "episodes": [], "streams": [], "clips": []},
        ["not", "an", "object"],
    ],
    ids=["missing-clips", "source-not-string", "episodes-not-array", "no-version", "not-object"],
)
def test_sync_on_catalog_violating_root_schema_errors_with_the_name(tmp_path, catalog):
    vault = tmp_path / "demo"
    vault.mkdir()
    (vault / "catalog.json").write_text(json.dumps(catalog))
    result = run_cli("sync", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert "demo" in result.stderr


# Error Handling: "Source metadata fetch failure | stderr | non-zero | Message
# includes `Source metadata fetch failure`" — unreachable source URL.
def test_unreachable_source_reports_fetch_failure(tmp_path):
    run_cli("init", "demo", "http://127.0.0.1:1/nothing.json", cwd=tmp_path)
    result = run_cli("sync", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# "Source metadata fetch failure" — non-success HTTP status.
def test_http_error_status_reports_fetch_failure(vault, source):
    source.serve_raw("nope", status=500)
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# "Source metadata fetch failure" — body is not JSON.
def test_non_json_body_reports_fetch_failure(vault, source):
    source.serve_raw("<html>oops</html>")
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Source response shape: "JSON object with `episodes`, `streams`, and `clips`
# arrays" — a violated envelope is a fetch failure.
@pytest.mark.parametrize(
    "body",
    [
        [],
        {"episodes": [], "streams": []},
        {"episodes": [], "streams": [], "clips": {}},
        {"episodes": None, "streams": [], "clips": []},
    ],
    ids=["array-body", "missing-clips", "clips-not-array", "episodes-null"],
)
def test_malformed_envelope_reports_fetch_failure(vault, source, body):
    source.serve(body)
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Source Entry Schema: "Each source entry must contain all nine fields above" —
# a missing field fails the sync.
@pytest.mark.parametrize(
    "field",
    ["id", "published", "width", "height", "title", "description", "views", "likes", "preview"],
)
def test_entry_missing_a_required_field_reports_fetch_failure(vault, source, field):
    entry = source_entry("e1")
    del entry[field]
    source.serve(payload(episodes=[entry]))

    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Source Entry Schema: "... with the stated types" — a wrongly typed field
# fails the sync.
@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 7),
        ("published", 20240101),
        ("width", "1920"),
        ("height", 1080.5),
        ("title", None),
        ("description", ["text"]),
        ("views", "10"),
        ("likes", "5"),
        ("preview", 99),
    ],
)
def test_entry_with_wrong_field_type_reports_fetch_failure(vault, source, field, value):
    source.serve(payload(clips=[source_entry("c1", **{field: value})]))

    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Source Entry Schema: "`likes` | integer or `null`" — null is a valid type.
def test_null_likes_is_accepted(vault, source):
    source.serve(payload(episodes=[source_entry("e1", likes=None)]))
    assert run_cli("sync", "demo", cwd=vault.parent).returncode == 0


# Source Entry Schema: entries are objects; a non-object entry is malformed.
def test_non_object_entry_reports_fetch_failure(vault, source):
    source.serve(payload(streams=["e1"]))
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# "If any source entry is missing a required field or has the wrong type,
# `sync` must fail ... and leave the vault unchanged."
def test_malformed_entry_leaves_vault_unchanged(vault, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    run_cli("sync", "demo", cwd=vault.parent)
    before = (vault / "catalog.json").read_bytes()

    bad = source_entry("e2")
    del bad["views"]
    source.serve(payload(episodes=[source_entry("e1"), bad]))
    run_cli("sync", "demo", cwd=vault.parent)

    assert (vault / "catalog.json").read_bytes() == before


# "Source metadata fetch failure ... malformed source entries are included in
# this case" — the documented message is used for entry-level problems too.
def test_malformed_entry_uses_the_fetch_failure_message(vault, source):
    source.serve(payload(clips=[source_entry("c1", width=None)]))
    assert "Source metadata fetch failure" in run_cli("sync", "demo", cwd=vault.parent).stderr


# Error Handling: fetch failures leave an untouched vault untouched — an
# unreachable source must not create a partially written catalog.
def test_fetch_failure_leaves_fresh_vault_unchanged(tmp_path):
    run_cli("init", "demo", "http://127.0.0.1:1/nothing.json", cwd=tmp_path)
    before = (tmp_path / "demo" / "catalog.json").read_bytes()
    run_cli("sync", "demo", cwd=tmp_path)
    assert (tmp_path / "demo" / "catalog.json").read_bytes() == before
