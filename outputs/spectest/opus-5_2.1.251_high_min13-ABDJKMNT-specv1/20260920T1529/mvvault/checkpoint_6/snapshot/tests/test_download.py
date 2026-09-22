"""Spec sections: Download Sources and Targets, Download Rules, legacy download phase."""

import json

from conftest import (
    catalog_bytes,
    media_names,
    payload,
    place_media,
    preview_names,
    run_cli,
    source_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)


def stocked_vault(tmp_path, source, **categories):
    """Sync metadata only, so every catalog entry is a download candidate."""
    source.serve(payload(**categories))
    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    source.requests.clear()


def download(tmp_path, *options):
    """Run the download phase alone."""
    return run_cli("sync", "demo", "--skip-metadata", *options, cwd=tmp_path)


# Download Sources and Targets: "Media | `<source>/media/<entry_id>` |
# `<vault>/media/` | Filename contains entry `id`".
def test_media_is_fetched_from_the_source_into_the_media_directory(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1")

    assert download(tmp_path).returncode == 0
    assert "/source.json/media/e1" in source.requests
    assert media_names(vault) == ["e1.mp4"]


# Download Sources and Targets: "Media with format override |
# `<source>/media/<entry_id>.<format>` | `<vault>/media/` | Extension = format
# string".
def test_format_override_changes_the_remote_path_and_extension(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1", fmt="mkv")

    assert download(tmp_path, "--format=mkv").returncode == 0
    assert "/source.json/media/e1.mkv" in source.requests
    assert media_names(vault) == ["e1.mkv"]


# Download Sources and Targets: "Preview | `<source>/preview/<entry_id>` |
# `<vault>/previews/` | Filename contains entry `id`".
def test_preview_is_fetched_into_the_previews_directory(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1")

    assert download(tmp_path).returncode == 0
    assert "/source.json/preview/e1" in source.requests
    assert preview_names(vault) == ["e1.jpg"]


# Download Rules: "Candidate selection | Only entries without a corresponding
# media file in `<vault>/media/` are candidates".
def test_entries_with_a_media_file_are_not_candidates(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1")
    place_media(vault, "e1.mp4")

    download(tmp_path)
    assert source.asset_requests() == []


# Download Rules: "A file matches if the name contains entry `id`" — matching is
# by containment, not by exact name.
def test_a_file_whose_name_contains_the_id_matches(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1")
    place_media(vault, "archive-e1-copy.bin")

    download(tmp_path)
    assert source.asset_requests() == []


# Download Rules: "apart from partial downloads"; "Partial artifacts | Stale
# partial-download artifacts must not block a later successful download".
def test_a_stale_partial_does_not_block_the_download(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1")
    place_media(vault, "e1.part", body=b"half")

    assert download(tmp_path).returncode == 0
    assert "e1.mp4" in media_names(vault)


# Download Rules: "Candidate order | Catalog order within category" and
# "Per-category limit | Download first `N` candidates in candidate order".
def test_the_limit_takes_the_first_candidates_in_catalog_order(vault, tmp_path, source):
    entries = [source_entry(f"e{n}", published=f"2024-01-0{n}T00:00:00") for n in (1, 2, 3)]
    stocked_vault(tmp_path, source, episodes=entries)
    for entry in entries:
        source.serve_entry(entry["id"])

    catalog = json.loads((vault / "catalog.json").read_text())
    first_two = [entry["id"] for entry in catalog["episodes"]][:2]

    download(tmp_path, "--episodes=2")
    assert media_names(vault) == sorted(f"{entry_id}.mp4" for entry_id in first_two)


# Download Rules: "Per-category limit | Download first `N` candidates in
# candidate order" — already-downloaded entries are not candidates, so they do
# not consume the limit.
def test_the_limit_counts_candidates_not_entries(vault, tmp_path, source):
    entries = [source_entry(f"e{n}", published=f"2024-01-0{n}T00:00:00") for n in (1, 2, 3)]
    stocked_vault(tmp_path, source, episodes=entries)
    for entry in entries:
        source.serve_entry(entry["id"])
    place_media(vault, "e3.mp4")

    download(tmp_path, "--episodes=1")
    assert sorted(media_names(vault)) == ["e2.mp4", "e3.mp4"]


# Download Rules: "Omitted limit | No limit for that category".
def test_an_omitted_limit_downloads_every_candidate(vault, tmp_path, source):
    entries = [source_entry(f"e{n}") for n in (1, 2, 3)]
    stocked_vault(tmp_path, source, episodes=entries)
    for entry in entries:
        source.serve_entry(entry["id"])

    download(tmp_path)
    assert media_names(vault) == ["e1.mp4", "e2.mp4", "e3.mp4"]


# Download Rules: "Media extension without override | Derive from HTTP
# `Content-Type`".
def test_media_extension_comes_from_the_content_type(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_asset("media", "e1", content_type="audio/mpeg")
    source.serve_asset("preview", "e1", content_type="image/png")

    download(tmp_path)
    assert media_names(vault) == ["e1.mp3"]
    assert preview_names(vault) == ["e1.png"]


# Download Rules: "Successful HTTP download response | Any successful response
# is treated as downloadable content".
def test_any_successful_response_is_stored(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_asset("media", "e1", body=b"<html>not a video</html>", content_type="text/html")
    source.serve_asset("preview", "e1", content_type="image/jpeg")

    assert download(tmp_path).returncode == 0
    assert media_names(vault) == ["e1.html"]


# Download Rules: "Permanent download failure | Warning to stderr; continue with
# remaining entries".
def test_permanent_failure_warns_and_continues(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1"), source_entry("e2")])
    source.serve_entry("e2")

    result = download(tmp_path)
    assert result.returncode == 0
    assert "e1" in result.stderr
    assert media_names(vault) == ["e2.mp4"]
    assert source.requests.count("/source.json/media/e1") == 1


# Download Rules: "Transient download failure | Retry, then warn to stderr after
# retries exhausted" — a retried download that recovers succeeds silently.
def test_transient_failure_is_retried(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1", failures=1)

    result = download(tmp_path)
    assert result.returncode == 0
    assert media_names(vault) == ["e1.mp4"]
    assert source.requests.count("/source.json/media/e1") > 1


# Download Rules: "Transient download failure | Retry, then warn to stderr after
# retries exhausted; continue with remaining entries".
def test_exhausted_retries_warn_and_continue(vault, tmp_path, source):
    stocked_vault(tmp_path, source, episodes=[source_entry("e1"), source_entry("e2")])
    source.serve_entry("e1", failures=99)
    source.serve_entry("e2")

    result = download(tmp_path)
    assert result.returncode == 0
    assert "e1" in result.stderr
    assert source.requests.count("/source.json/media/e1") > 1
    assert media_names(vault) == ["e2.mp4"]


# Download Rules: "Persistence boundary | Metadata changes must be durably saved
# before successful sync returns, including runs with download failures", and
# `catalog.json` Persistence During `sync`: "Metadata save still occurs even
# when one or more downloads fail".
def test_metadata_is_saved_despite_download_failures(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))

    result = run_cli("sync", "demo", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stderr != ""
    catalog = json.loads((vault / "catalog.json").read_text())
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1"]


# `sync` on Legacy Vaults — Download Phase: "the download phase always operates
# against a v3 catalog. The source URL for downloads is the migrated `source`".
def test_legacy_sync_downloads_from_the_migrated_source(tmp_path, source):
    vault = write_vault(tmp_path, v2_catalog(source.url, episodes=[v2_entry("e1")]))
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_entry("e1")

    result = run_cli("sync", "demo", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(catalog_bytes(vault))["version"] == 3
    assert media_names(vault) == ["e1.mp4"]
