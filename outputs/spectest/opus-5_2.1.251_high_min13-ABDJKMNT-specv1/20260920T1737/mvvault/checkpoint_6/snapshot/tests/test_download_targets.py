"""Download sources and targets: remote paths, local directories, filenames."""

from conftest import names_in, source_entry


# Spec: "| Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename
# contains entry `id` |".
def test_media_is_fetched_from_source_media_path_into_vault_media(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "demo")

    assert result.returncode == 0, result.stderr
    assert source.asset_requests["media/e1"] == 1
    assert names_in(vault / "media") == ["e1.mp4"]
    assert "e1" in names_in(vault / "media")[0]


# Spec: "| Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` |
# Filename contains entry `id` |".
def test_preview_is_fetched_from_source_preview_path_into_vault_previews(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "demo")

    assert result.returncode == 0, result.stderr
    assert source.asset_requests["preview/e1"] == 1
    assert [name for name in names_in(vault / "previews") if "e1" in name]


# Spec: "| Media extension without override | Derive from HTTP `Content-Type` |".
def test_media_extension_comes_from_content_type(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    source.media_content_type = "audio/mpeg"

    result = run_cli("sync", "demo")

    assert result.returncode == 0, result.stderr
    assert names_in(vault / "media") == ["e1.mp3"]


# Spec: "| Media with format override | `<source>/media/<entry_id>.<format>` |
# `<vault>/media/` | Extension = format string |".
def test_format_override_changes_remote_path_and_extension(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "demo", "--format=ogg")

    assert result.returncode == 0, result.stderr
    assert source.asset_requests["media/e1.ogg"] == 1
    assert names_in(vault / "media") == ["e1.ogg"]


# Spec: "| `--format=<str>` | string | Override media download format and output
# extension |" -- the preview path is not affected by the override.
def test_format_override_does_not_change_preview_path(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    run_cli("sync", "demo", "--format=ogg")

    assert source.asset_requests["preview/e1"] == 1


# Spec: "| Successful HTTP download response | Any successful response is
# treated as downloadable content ... |".
def test_downloaded_bytes_are_stored_verbatim(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    run_cli("sync", "demo")

    assert (vault / "media" / "e1.mp4").read_bytes() == b"media/e1-bytes"


# Spec: assets are downloaded for every category, each from `<source>/media/<id>`.
def test_all_three_categories_are_downloaded(run_cli, source, vault):
    source.serve(
        episodes=[source_entry("e1")],
        streams=[source_entry("s1")],
        clips=[source_entry("c1")],
    )

    result = run_cli("sync", "demo")

    assert result.returncode == 0, result.stderr
    assert names_in(vault / "media") == ["c1.mp4", "e1.mp4", "s1.mp4"]
