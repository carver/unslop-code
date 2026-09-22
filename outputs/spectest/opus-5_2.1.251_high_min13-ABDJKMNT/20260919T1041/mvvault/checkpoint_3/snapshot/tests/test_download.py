"""Download Sources and Targets, Download Rules and the legacy download phase."""

import json

import pytest

from conftest import (
    V1_SOURCE_URL,
    read_catalog,
    source_entry,
    stored_names,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
)


@pytest.fixture
def sync(run_cli, vault, source):
    """Run `sync` on the vault 'v' against a payload of episodes."""

    def run(*options, episodes=(), streams=(), clips=()):
        source.payload = {
            "episodes": list(episodes),
            "streams": list(streams),
            "clips": list(clips),
        }
        return run_cli("sync", "v", *options)

    return run


# Spec: Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename contains entry `id`
def test_media_is_fetched_from_the_media_path(sync, source):
    sync(episodes=[source_entry("a")])
    assert "/feed.json/media/a" in source.asset_requests


# Spec: Media | ... | `<vault>/media/` | Filename contains entry `id`
def test_media_lands_in_the_media_directory_named_after_the_entry(sync, vault):
    sync(episodes=[source_entry("abc")])
    assert [name for name in stored_names(vault / "media") if "abc" in name] == ["abc.mp4"]


# Spec: Media with format override | `<source>/media/<entry_id>.<format>` | Extension = format string
def test_format_override_changes_remote_path_and_extension(sync, vault, source):
    sync("--format=ogg", episodes=[source_entry("a")])
    assert "/feed.json/media/a.ogg" in source.asset_requests
    assert stored_names(vault / "media") == ["a.ogg"]


# Spec: Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename contains entry `id`
def test_preview_is_fetched_from_the_preview_path(sync, source):
    sync(episodes=[source_entry("a")])
    assert "/feed.json/preview/a" in source.asset_requests


# Spec: Preview | ... | `<vault>/previews/` | Filename contains entry `id`
def test_preview_lands_in_the_previews_directory(sync, vault, source):
    source.assets = {"/feed.json/preview/a": (200, "image/png", b"png-bytes")}
    sync(episodes=[source_entry("a")])
    assert stored_names(vault / "previews") == ["a.png"]


# Spec: Media with format override | ... Extension = format string (previews keep their own type)
def test_format_override_does_not_apply_to_previews(sync, vault, source):
    source.assets = {"/feed.json/preview/a": (200, "image/png", b"png-bytes")}
    sync("--format=ogg", episodes=[source_entry("a")])
    assert stored_names(vault / "previews") == ["a.png"]


# Spec: Candidate selection | Only entries without a corresponding media file in
# `<vault>/media/` are candidates
def test_entries_with_existing_media_are_not_candidates(sync, vault, source):
    sync(episodes=[source_entry("a")])
    source.asset_requests.clear()
    sync(episodes=[source_entry("a")])
    assert source.asset_requests == []


# Spec: Candidate selection | ... (a media file of any extension counts)
def test_any_media_extension_marks_an_entry_as_downloaded(sync, vault, source):
    (vault / "media").mkdir()
    (vault / "media" / "a.webm").write_bytes(b"already here")
    sync(episodes=[source_entry("a")])
    assert "/feed.json/media/a" not in source.asset_requests


# Spec: Candidate order | Catalog order within category
def test_candidates_follow_catalog_order(sync, vault):
    sync(
        "--episodes=1",
        episodes=[source_entry("old", published="2024-01-01"), source_entry("new", published="2024-09-01")],
    )
    assert [entry["id"] for entry in read_catalog(vault)["episodes"]] == ["new", "old"]
    assert stored_names(vault / "media") == ["new.mp4"]


# Spec: Per-category limit | Download first `N` candidates in candidate order
def test_limit_takes_the_first_candidates_in_order(sync, vault):
    published = ["2024-05-01", "2024-04-01", "2024-03-01"]
    sync("--episodes=2", episodes=[source_entry(f"e{n}", published=day) for n, day in enumerate(published)])
    assert stored_names(vault / "media") == ["e0.mp4", "e1.mp4"]


# Spec: Per-category limit | ... (already downloaded entries do not consume the limit)
def test_limit_counts_only_pending_candidates(sync, vault):
    entries = [source_entry("e0", published="2024-05-01"), source_entry("e1", published="2024-04-01")]
    sync("--episodes=1", episodes=entries)
    sync("--episodes=1", episodes=entries)
    assert stored_names(vault / "media") == ["e0.mp4", "e1.mp4"]


# Spec: Media extension without override | Derive from HTTP `Content-Type`
@pytest.mark.parametrize(
    ("content_type", "extension"),
    [("video/mp4", ".mp4"), ("audio/mpeg", ".mp3"), ("image/png", ".png"), ("video/webm", ".webm")],
)
def test_media_extension_comes_from_content_type(sync, vault, source, content_type, extension):
    source.asset = (200, content_type, b"payload")
    sync(episodes=[source_entry("a")])
    assert stored_names(vault / "media") == ["a" + extension]


# Spec: Media extension without override | Derive from HTTP `Content-Type`
# (parameters on the header are not part of the type)
def test_content_type_parameters_are_ignored(sync, vault, source):
    source.asset = (200, "video/mp4; charset=binary", b"payload")
    sync(episodes=[source_entry("a")])
    assert stored_names(vault / "media") == ["a.mp4"]


# Spec: Media extension with override | Use override string as extension
def test_override_wins_over_content_type(sync, vault, source):
    source.asset = (200, "image/png", b"payload")
    sync("--format=mp4", episodes=[source_entry("a")])
    assert stored_names(vault / "media") == ["a.mp4"]


# Spec: Successful HTTP download response | Any successful response is treated as
# downloadable content
def test_any_successful_response_is_stored(sync, vault, source):
    source.asset = (200, "text/html", b"<html>not really media</html>")
    result = sync(episodes=[source_entry("a")])
    assert result.returncode == 0, result.stderr
    assert stored_names(vault / "media") == ["a.html"]


# Spec: Successful HTTP download response | ... (the body is stored verbatim)
def test_response_body_is_written_verbatim(sync, vault, source):
    source.asset = (200, "video/mp4", b"\x00\x01binary-payload")
    sync(episodes=[source_entry("a")])
    assert (vault / "media" / "a.mp4").read_bytes() == b"\x00\x01binary-payload"


# Spec: Partial artifacts | Stale partial-download artifacts must not block a later
# successful download
def test_stale_partial_artifact_does_not_block_a_download(sync, vault, source):
    (vault / "media").mkdir()
    (vault / "media" / "a.part").write_bytes(b"truncated")
    sync(episodes=[source_entry("a")])
    assert (vault / "media" / "a.mp4").read_bytes() == b"media-bytes"


# Spec: Partial artifacts | ... (a failed download leaves no file that looks finished)
def test_failed_download_leaves_no_finished_media_file(sync, vault, source):
    source.asset = (404, "text/plain", b"gone")
    sync(episodes=[source_entry("a")])
    assert stored_names(vault / "media") == []


# Spec: Permanent download failure | Warning to stderr; continue with remaining entries
def test_permanent_failure_warns_and_continues(sync, vault, source):
    source.assets = {"/feed.json/media/a": (404, "text/plain", b"gone")}
    result = sync(episodes=[source_entry("a", published="2024-05-01"), source_entry("b", published="2024-04-01")])
    assert result.returncode == 0
    assert "a" in result.stderr
    assert "b.mp4" in stored_names(vault / "media")


# Spec: Permanent download failure | ... (no retries for a permanent failure)
def test_permanent_failure_is_not_retried(sync, source):
    source.assets = {"/feed.json/media/a": (404, "text/plain", b"gone")}
    sync(episodes=[source_entry("a")])
    assert source.asset_requests.count("/feed.json/media/a") == 1


# Spec: Transient download failure | Retry, then warn to stderr after retries exhausted
def test_transient_failure_is_retried_until_it_succeeds(sync, vault, source):
    source.transient = {"/feed.json/media/a": 2}
    result = sync(episodes=[source_entry("a")])
    assert result.returncode == 0, result.stderr
    assert stored_names(vault / "media") == ["a.mp4"]
    assert source.asset_requests.count("/feed.json/media/a") == 3


# Spec: Transient download failure | Retry, then warn to stderr after retries exhausted;
# continue with remaining entries
def test_exhausted_retries_warn_and_continue(sync, vault, source):
    source.transient = {"/feed.json/media/a": 99}
    result = sync(episodes=[source_entry("a", published="2024-05-01"), source_entry("b", published="2024-04-01")])
    assert result.returncode == 0
    assert "a" in result.stderr
    assert source.asset_requests.count("/feed.json/media/a") > 1
    assert "b.mp4" in stored_names(vault / "media")


# Spec: Persistence boundary | Metadata changes must be durably saved before successful
# sync returns, including runs with download failures
def test_metadata_is_saved_despite_download_failures(sync, vault, source):
    source.asset = (404, "text/plain", b"gone")
    result = sync(episodes=[source_entry("a")])
    assert result.returncode == 0
    assert [entry["id"] for entry in read_catalog(vault)["episodes"]] == ["a"]


# Spec: Save timing | Metadata phase persists before successful `sync` returns
def test_catalog_is_written_by_a_successful_sync(sync, vault):
    sync(episodes=[source_entry("a")])
    assert json.loads((vault / "catalog.json").read_text())["episodes"][0]["id"] == "a"


# Spec: Download failure interaction | Metadata save still occurs even when one or more
# downloads fail
def test_backup_and_catalog_survive_download_failures(sync, vault, source):
    sync("--skip-download", episodes=[source_entry("a")])
    source.asset = (500, "text/plain", b"boom")
    sync(episodes=[source_entry("a", views=42)])
    entry = read_catalog(vault)["episodes"][0]
    assert entry["views"][max(entry["views"])] == 42


# Spec: Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata phase,
# the download phase always operates against a v3 catalog.
def test_download_phase_uses_the_migrated_v2_catalog(run_cli, make_vault, source):
    make_vault(v2_catalog(source.url, episodes=[v2_entry("a")]))
    source.payload = {"episodes": [source_entry("a")], "streams": [], "clips": []}
    result = run_cli("sync", "v")
    assert result.returncode == 0, result.stderr
    assert "/feed.json/media/a" in source.asset_requests


# Spec: The source URL for downloads is the migrated `source` value.
def test_v1_downloads_use_the_derived_source_url(monkeypatch, tmp_path, make_vault):
    from mvaultlib import catalog as catalog_module
    from mvaultlib import download as download_module

    make_vault(v1_catalog([v1_entry("a")]))
    monkeypatch.chdir(tmp_path)
    requested = []

    class Response:
        ok = True
        status_code = 200
        headers = {"Content-Type": "video/mp4"}
        content = b"payload"

    def get(url, timeout=None):
        requested.append(url)
        return Response()

    monkeypatch.setattr(download_module.requests, "get", get)
    catalog, _ = catalog_module.load("v")
    download_module.run("v", catalog, {"episodes": None, "streams": None, "clips": None}, None)
    assert requested[0] == f"{V1_SOURCE_URL}/media/a"
