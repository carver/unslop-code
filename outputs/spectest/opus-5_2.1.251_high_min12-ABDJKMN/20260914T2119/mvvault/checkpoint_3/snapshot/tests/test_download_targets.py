"""Spec: Download Sources and Targets."""
import os

from conftest import (make_entry, media_dir, preview_dir, media_files,
                      preview_files, read_bytes)


# Spec: "| Media | `<source>/media/<entry_id>` | ... |" -- remote path.
def test_media_remote_path(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    run("sync", "vault")
    assert source.asset_requests("media") == [source.asset_path("media", "e1")]


# Spec: "| Preview | `<source>/preview/<entry_id>` | ... |" -- note the
# singular `preview` segment in the remote path.
def test_preview_remote_path(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    run("sync", "vault")
    assert source.asset_requests("preview") == [
        source.asset_path("preview", "e1")]


# Spec: "| Media | ... | `<vault>/media/` | ... |" -- local directory.
def test_media_local_directory(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    run("sync", "vault")
    assert os.path.isdir(media_dir(tmp_path))
    assert len(media_files(tmp_path)) == 1


# Spec: "| Preview | ... | `<vault>/previews/` | ... |" -- note the plural
# `previews` directory name locally.
def test_preview_local_directory(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    run("sync", "vault")
    assert os.path.isdir(preview_dir(tmp_path))
    assert len(preview_files(tmp_path)) == 1


# Spec: "| Media | ... | Filename contains entry `id` |"
def test_media_filename_contains_entry_id(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="odd-id_42")])
    source.serve_entry_assets("odd-id_42")
    run("sync", "vault")
    names = media_files(tmp_path)
    assert len(names) == 1 and "odd-id_42" in names[0]


# Spec: "| Preview | ... | Filename contains entry `id` |"
def test_preview_filename_contains_entry_id(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="odd-id_42")])
    source.serve_entry_assets("odd-id_42")
    run("sync", "vault")
    names = preview_files(tmp_path)
    assert len(names) == 1 and "odd-id_42" in names[0]


# Spec: "| Media with format override | ... | Extension = format string |"
def test_format_override_extension_is_the_format_string(run, source, tmp_path,
                                                        vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", ext="mkv", content_type="video/mp4")
    source.serve_preview("e1")
    run("sync", "vault", "--format=mkv")
    assert media_files(tmp_path) == ["e1.mkv"]


# Spec: downloads write the bytes the server returned.
def test_downloaded_bytes_are_stored(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", body=b"\x00\x01MEDIA")
    source.serve_preview("e1", body=b"PREVIEW!")
    run("sync", "vault")
    assert read_bytes(os.path.join(media_dir(tmp_path),
                                   media_files(tmp_path)[0])) == b"\x00\x01MEDIA"
    assert read_bytes(os.path.join(preview_dir(tmp_path),
                                   preview_files(tmp_path)[0])) == b"PREVIEW!"


# Spec: assets for every category land in the same two directories.
def test_all_categories_share_the_download_directories(run, source, tmp_path,
                                                       vault):
    source.serve(episodes=[make_entry(id="e1")],
                 streams=[make_entry(id="s1")],
                 clips=[make_entry(id="c1")])
    for i in ("e1", "s1", "c1"):
        source.serve_entry_assets(i)
    run("sync", "vault")
    assert media_files(tmp_path) == ["c1.mp4", "e1.mp4", "s1.mp4"]
    assert preview_files(tmp_path) == ["c1.jpg", "e1.jpg", "s1.jpg"]
