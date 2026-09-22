"""Spec sections: `sync` Command / `sync` Source Entry Schema / fetch failures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# Spec: | Source request | HTTP `GET` to vault `source` URL, made with `urllib.request` |
def test_sync_issues_http_get_to_source_url(run_cli, vault, source, helpers):
    source.set(helpers.make_payload())
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert source.requests, "no HTTP request reached the source server"
    assert source.requests[0][0] == "GET"
    assert source.requests[0][1] == "/source.json"


# Spec: | Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays |
def test_sync_consumes_all_three_categories(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("e1")],
        streams=[helpers.make_source_entry("s1")],
        clips=[helpers.make_source_entry("c1")],
    ))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Spec: | Success effect | Update catalog with new, changed, removed, and restored entries |
# Context: the later spec adds a download phase whose failures warn on stderr,
# so a clean metadata phase is checked with `--skip-download`.
def test_sync_succeeds_and_reports_nothing_on_stderr(run_cli, vault, source, helpers):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    result = run_cli("sync", "vault", "--skip-download")
    assert result.returncode == 0
    assert result.stderr == ""


# Spec: | Syntax | `python mvault.py sync <name>` |
def test_sync_requires_vault_name(run_cli):
    assert run_cli("sync").returncode != 0


# Spec: | Missing or invalid vault | Error to stderr including `<name>`; exit non-zero |
def test_sync_missing_vault_errors_with_name(run_cli):
    result = run_cli("sync", "ghostvault")
    assert result.returncode != 0
    assert "ghostvault" in result.stderr


# Spec: | Missing or invalid vault | ... (directory exists, no catalog.json)
def test_sync_vault_without_catalog_is_invalid(run_cli, workdir):
    (Path(workdir) / "brokenvault").mkdir()
    result = run_cli("sync", "brokenvault")
    assert result.returncode != 0
    assert "brokenvault" in result.stderr


# Spec: | Missing or invalid vault | ... (catalog.json is not parseable JSON)
def test_sync_unparseable_catalog_is_invalid(run_cli, workdir):
    vault_dir = Path(workdir) / "brokenvault"
    vault_dir.mkdir()
    (vault_dir / "catalog.json").write_text("{not json", encoding="utf-8")
    result = run_cli("sync", "brokenvault")
    assert result.returncode != 0
    assert "brokenvault" in result.stderr


# Spec: | Missing or invalid vault | ... (catalog.json missing required root fields)
@pytest.mark.parametrize("missing", ["version", "source", "episodes", "streams", "clips"])
def test_sync_catalog_missing_root_field_is_invalid(run_cli, workdir, missing):
    vault_dir = Path(workdir) / "brokenvault"
    vault_dir.mkdir()
    data = {"version": 3, "source": "http://x.invalid/f.json",
            "episodes": [], "streams": [], "clips": []}
    del data[missing]
    (vault_dir / "catalog.json").write_text(json.dumps(data), encoding="utf-8")
    result = run_cli("sync", "brokenvault")
    assert result.returncode != 0
    assert "brokenvault" in result.stderr


# Spec: Root schema | `version` | integer | `3` | -> a catalog whose version names
# no supported schema is an invalid vault. Versions 1 and 2 are now supported and
# load transparently, so the unsupported case is a version above `3`.
# See AMBIGUITIES.md T6 (and its legacy-catalog resolution).
def test_sync_catalog_with_wrong_version_is_invalid(run_cli, workdir):
    vault_dir = Path(workdir) / "brokenvault"
    vault_dir.mkdir()
    data = {"version": 4, "source": "http://x.invalid/f.json",
            "episodes": [], "streams": [], "clips": []}
    (vault_dir / "catalog.json").write_text(json.dumps(data), encoding="utf-8")
    result = run_cli("sync", "brokenvault")
    assert result.returncode != 0
    assert "brokenvault" in result.stderr


# Spec: | Source metadata fetch failure | stderr | non-zero |
#        Message includes `Source metadata fetch failure` | (transport error)
def test_unreachable_source_is_fetch_failure(run_cli, workdir):
    assert run_cli("init", "vault", "http://127.0.0.1:1/none.json").returncode == 0
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: | Source metadata fetch failure | ... (HTTP error status)
def test_http_error_status_is_fetch_failure(run_cli, vault, source):
    source.set_raw("nope", status=500)
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: | Source response shape | JSON object ... | (body is not JSON)
def test_non_json_body_is_fetch_failure(run_cli, vault, source):
    source.set_raw("<html>oops</html>")
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: | Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays |
def test_json_not_an_object_is_fetch_failure(run_cli, vault, source):
    source.set_raw(json.dumps([1, 2, 3]))
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: | Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays |
@pytest.mark.parametrize("missing", ["episodes", "streams", "clips"])
def test_missing_top_level_category_is_fetch_failure(run_cli, vault, source, helpers, missing):
    payload = helpers.make_payload()
    del payload[missing]
    source.set(payload)
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: | Source response shape | ... arrays | (category present but not an array)
def test_category_not_an_array_is_fetch_failure(run_cli, vault, source, helpers):
    payload = helpers.make_payload()
    payload["streams"] = {"id": "x"}
    source.set(payload)
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: "Each source entry must contain all nine fields above with the stated types.
#        If any source entry is missing a required field ... `sync` must fail as a
#        source metadata fetch failure"
@pytest.mark.parametrize(
    "field",
    ["id", "published", "width", "height", "title", "description", "views", "likes", "preview"],
)
def test_missing_source_entry_field_is_fetch_failure(run_cli, vault, source, helpers, field):
    entry = helpers.make_source_entry("e1")
    del entry[field]
    source.set(helpers.make_payload(episodes=[entry]))
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: "... or has the wrong type, `sync` must fail as a source metadata fetch failure"
# Context: the schema types are id/title/description/preview = string,
#          published = string, width/height/views = integer, likes = integer or null.
@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("id", 7),
        ("id", None),
        ("published", 20240501),
        ("published", None),
        ("width", "1920"),
        ("width", 19.5),
        ("width", None),
        ("height", "1080"),
        ("height", None),
        ("title", 5),
        ("title", None),
        ("description", ["a"]),
        ("description", None),
        ("views", "100"),
        ("views", 1.5),
        ("views", None),
        ("likes", "10"),
        ("likes", 1.5),
        ("preview", 99),
        ("preview", None),
    ],
)
def test_wrong_typed_source_entry_field_is_fetch_failure(
    run_cli, vault, source, helpers, field, bad_value
):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", **{field: bad_value})]))
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: "| `likes` | integer or `null` |" -> null is a valid type for likes only.
def test_null_likes_is_accepted(run_cli, vault, source, helpers):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=None)]))
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr


# Spec: "... with the stated types" -> JSON booleans are not integers. See AMBIGUITIES.md T10.
@pytest.mark.parametrize("field", ["width", "height", "views", "likes"])
def test_boolean_where_integer_required_is_fetch_failure(run_cli, vault, source, helpers, field):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", **{field: True})]))
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: "... (source entry is not an object at all)"
def test_source_entry_not_an_object_is_fetch_failure(run_cli, vault, source, helpers):
    payload = helpers.make_payload(episodes=["just a string"])
    source.set(payload)
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: "... `sync` must fail ... and leave the vault unchanged."
def test_malformed_entry_leaves_vault_unchanged(run_cli, vault, source, helpers, snapshot):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    before = snapshot(vault)

    bad = helpers.make_source_entry("e2")
    del bad["views"]
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="new"), bad]))
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert snapshot(vault) == before


# Spec: "... and leave the vault unchanged." (failure on the very first sync)
def test_fetch_failure_leaves_fresh_vault_unchanged(run_cli, vault, source, snapshot):
    before = snapshot(vault)
    source.set_raw("not json")
    assert run_cli("sync", "vault").returncode != 0
    assert snapshot(vault) == before


# Spec: | Source metadata fetch failure | stderr | ... |
def test_fetch_failure_message_goes_to_stderr_only(run_cli, vault, source):
    source.set_raw("not json")
    result = run_cli("sync", "vault")
    assert "Source metadata fetch failure" in result.stderr
    assert "Source metadata fetch failure" not in result.stdout


# Spec: "malformed source entries are included in this case" (of fetch failure)
def test_malformed_entry_reported_as_fetch_failure_text(run_cli, vault, source, helpers):
    source.set(helpers.make_payload(clips=[helpers.make_source_entry("c1", preview=None)]))
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr
