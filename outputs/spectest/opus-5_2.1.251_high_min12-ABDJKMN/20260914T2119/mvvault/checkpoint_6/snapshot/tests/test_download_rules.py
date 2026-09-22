"""Spec: Download Rules (candidate selection, ordering, extensions)."""
import os

import pytest

from conftest import (make_entry, media_dir, preview_dir, media_files,
                      preview_files, read_bytes, read_catalog)


# Spec: "| Candidate selection | Only entries without a corresponding media
# file in `<vault>/media/` are candidates |"
def test_entry_with_existing_media_file_is_not_a_candidate(run, source,
                                                           tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    run("sync", "vault")
    hits_before = source.hits("media", "e1")
    run("sync", "vault")
    assert source.hits("media", "e1") == hits_before


# Spec: "Only entries without a corresponding media file ... are candidates"
# -- an already-present file blocks the download even if this run put it there
# by hand, whatever its extension.
def test_preexisting_media_file_any_extension_blocks_download(run, source,
                                                              tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    os.makedirs(media_dir(tmp_path), exist_ok=True)
    with open(os.path.join(media_dir(tmp_path), "e1.avi"), "wb") as fh:
        fh.write(b"already here")
    run("sync", "vault")
    assert source.hits("media", "e1") == 0
    assert media_files(tmp_path) == ["e1.avi"]


# Spec: candidate selection keys on the entry id, so another entry's file does
# not suppress this entry's download.
def test_other_entrys_media_file_does_not_block(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1"), make_entry(id="e2")])
    source.serve_entry_assets("e2")
    os.makedirs(media_dir(tmp_path), exist_ok=True)
    with open(os.path.join(media_dir(tmp_path), "e1.mp4"), "wb") as fh:
        fh.write(b"x")
    run("sync", "vault")
    assert source.hits("media", "e2") == 1
    assert media_files(tmp_path) == ["e1.mp4", "e2.mp4"]


# Spec: "| Candidate order | Catalog order within category |" +
# "| Per-category limit | Download first `N` candidates in candidate order |"
def test_candidate_order_is_catalog_order(run, source, tmp_path, vault):
    # Catalog order is newest `published` first, so e3 sorts ahead of e1.
    source.serve(episodes=[
        make_entry(id="e1", published="2024-01-01T00:00:00"),
        make_entry(id="e3", published="2024-03-01T00:00:00"),
        make_entry(id="e2", published="2024-02-01T00:00:00"),
    ])
    for i in ("e1", "e2", "e3"):
        source.serve_entry_assets(i)
    run("sync", "vault", "--episodes=2")
    catalog_order = [e["id"] for e in read_catalog(tmp_path)["episodes"]]
    assert catalog_order == ["e3", "e2", "e1"]
    assert media_files(tmp_path) == ["e2.mp4", "e3.mp4"]
    assert source.hits("media", "e1") == 0


# Spec: "| Per-category limit | Download first `N` candidates in candidate
# order |" -- already-downloaded entries are not candidates, so a second run
# with the same limit picks up the *next* N.
def test_limit_applies_to_candidates_not_to_all_entries(run, source, tmp_path,
                                                        vault):
    source.serve(episodes=[
        make_entry(id="e1", published="2024-03-01T00:00:00"),
        make_entry(id="e2", published="2024-02-01T00:00:00"),
        make_entry(id="e3", published="2024-01-01T00:00:00"),
    ])
    for i in ("e1", "e2", "e3"):
        source.serve_entry_assets(i)
    run("sync", "vault", "--episodes=1")
    assert media_files(tmp_path) == ["e1.mp4"]
    run("sync", "vault", "--episodes=1")
    assert media_files(tmp_path) == ["e1.mp4", "e2.mp4"]


# Spec: "| Media extension without override | Derive from HTTP
# `Content-Type` |"
@pytest.mark.parametrize("content_type,ext", [
    ("video/mp4", "mp4"),
    ("video/webm", "webm"),
    ("audio/mpeg", "mp3"),
    ("image/png", "png"),
    ("image/jpeg", "jpg"),
])
def test_media_extension_derived_from_content_type(run, source, tmp_path,
                                                   vault, content_type, ext):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", content_type=content_type)
    source.serve_preview("e1")
    run("sync", "vault")
    assert media_files(tmp_path) == ["e1.%s" % ext]


# Spec: "Derive from HTTP `Content-Type`" -- parameters on the header are not
# part of the type.
def test_content_type_parameters_are_ignored(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", content_type="video/mp4; charset=binary")
    source.serve_preview("e1")
    run("sync", "vault")
    assert media_files(tmp_path) == ["e1.mp4"]


# Spec: "Derive from HTTP `Content-Type`" -- previews use the same derivation.
def test_preview_extension_derived_from_content_type(run, source, tmp_path,
                                                     vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1")
    source.serve_preview("e1", content_type="image/png")
    run("sync", "vault")
    assert preview_files(tmp_path) == ["e1.png"]


# Spec: "| Media extension with override | Use override string as extension |"
# -- the override wins over the served `Content-Type`.
def test_override_extension_beats_content_type(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", ext="dat", content_type="video/mp4")
    source.serve_preview("e1")
    run("sync", "vault", "--format=dat")
    assert media_files(tmp_path) == ["e1.dat"]


# Spec: "| Successful HTTP download response | Any successful response is
# treated as downloadable content; implementations are not required to validate
# payload semantics beyond using `Content-Type` for extension derivation |"
def test_any_successful_response_is_downloadable_content(run, source, tmp_path,
                                                         vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", body=b"not really a video",
                       content_type="text/plain")
    source.serve_preview("e1", body=b"{}", content_type="application/json")
    res = run("sync", "vault")
    assert res.returncode == 0, res
    assert len(media_files(tmp_path)) == 1
    assert read_bytes(os.path.join(media_dir(tmp_path),
                                   media_files(tmp_path)[0])) == b"not really a video"


# Spec: "Any successful response is treated as downloadable content" -- an
# empty body still counts as a download.
def test_empty_body_counts_as_a_download(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", body=b"")
    source.serve_preview("e1", body=b"")
    assert run("sync", "vault").returncode == 0
    assert len(media_files(tmp_path)) == 1


# Spec: "| Partial artifacts | Stale partial-download artifacts must not block
# a later successful download |"
def test_stale_partial_artifact_does_not_block_download(run, source, tmp_path,
                                                        vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    os.makedirs(media_dir(tmp_path), exist_ok=True)
    with open(os.path.join(media_dir(tmp_path), "e1.mp4.part"), "wb") as fh:
        fh.write(b"half a file")
    assert run("sync", "vault").returncode == 0
    assert source.hits("media", "e1") == 1
    assert "e1.mp4" in media_files(tmp_path)
    assert read_bytes(os.path.join(media_dir(tmp_path),
                                   "e1.mp4")) == b"MEDIABYTES"


# Spec: "Stale partial-download artifacts must not block a later successful
# download" -- a failed download leaves no artifact that would look like a
# finished media file to the next run.
def test_failed_download_leaves_no_blocking_artifact(run, source, tmp_path,
                                                     vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.fail_asset("media", "e1", status=404)
    source.fail_asset("preview", "e1", status=404)
    assert run("sync", "vault").returncode == 0
    source.serve_entry_assets("e1")
    assert run("sync", "vault").returncode == 0
    assert media_files(tmp_path) == ["e1.mp4"]


# Spec: "| Persistence boundary | Metadata changes must be durably saved before
# successful sync returns, including runs with download failures |"
def test_metadata_saved_even_when_downloads_fail(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="Saved")])
    source.fail_asset("media", "e1", status=404)
    source.fail_asset("preview", "e1", status=404)
    res = run("sync", "vault")
    assert res.returncode == 0, res
    catalog = read_catalog(tmp_path)
    assert list(catalog["episodes"][0]["title"].values()) == ["Saved"]


# Spec: "Only entries without a corresponding media file ... are candidates"
# -- previews follow the media candidate selection, so an entry that already
# has media is not re-fetched at all.
def test_preview_follows_media_candidate_selection(run, source, tmp_path,
                                                   vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    run("sync", "vault")
    before = source.hits("preview", "e1")
    run("sync", "vault")
    assert source.hits("preview", "e1") == before


# Spec: "Per-category limit | Download first `N` candidates" -- the limit
# bounds previews too, since previews ride along with selected candidates.
def test_limit_bounds_preview_downloads(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e%d" % n) for n in range(1, 4)])
    for n in range(1, 4):
        source.serve_entry_assets("e%d" % n)
    run("sync", "vault", "--episodes=1")
    assert len(preview_files(tmp_path)) == 1


# Spec: "`sync` on Legacy Vaults -- Download Phase": "Because `sync`
# auto-migrates v1 and v2 vaults to v3 during the metadata phase, the download
# phase always operates against a v3 catalog."
def test_legacy_vault_download_phase_operates_on_v3_catalog(
        run, source, tmp_path, make_vault):
    from conftest import make_v2_catalog, make_v2_entry
    make_vault(make_v2_catalog(source=source.url,
                               episodes=[make_v2_entry(id="e1")],
                               clips=[make_v2_entry(id="c1")]))
    source.serve(episodes=[make_entry(id="e1")], clips=[make_entry(id="c1")])
    for i in ("e1", "c1"):
        source.serve_entry_assets(i)
    assert run("sync", "vault").returncode == 0
    assert read_catalog(tmp_path)["version"] == 3
    assert media_files(tmp_path) == ["c1.mp4", "e1.mp4"]


# Spec: "The source URL for downloads is the migrated `source` value."
# Context: a v1 vault's source URL is derived from `source_id`.
def test_v1_download_source_url_is_the_migrated_source(run, tmp_path,
                                                       make_vault, source):
    from conftest import make_v1_catalog, make_v1_entry
    # Point the v1 `source_id` at the local server by exploiting nothing: the
    # derived URL is unreachable, so the metadata fetch aborts the run and the
    # download phase never runs against the stale v1 shape.
    make_vault(make_v1_catalog(source_id="chan42",
                               entries=[make_v1_entry(id="e1")]))
    res = run("sync", "vault")
    assert res.returncode != 0
    assert "https://media.example.com/channel/chan42" in res.stderr


# Spec: "The source URL for downloads is the migrated `source` value." --
# with `--skip-metadata` on a v2 vault the download phase still uses the
# v3 `source` value read from the catalog.
def test_skip_metadata_on_legacy_vault_uses_migrated_source(
        run, source, tmp_path, make_vault):
    from conftest import make_v2_catalog, make_v2_entry
    make_vault(make_v2_catalog(source=source.url,
                               episodes=[make_v2_entry(id="e1")]))
    source.serve_entry_assets("e1")
    res = run("sync", "vault", "--skip-metadata")
    assert res.returncode == 0, res
    assert media_files(tmp_path) == ["e1.mp4"]
