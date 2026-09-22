"""Spec sections: Download Sources and Targets, Download Rules, `sync` on
Legacy Vaults -- Download Phase, and `catalog.json` Persistence During `sync`.
"""
import os

import pytest

from conftest import (
    entry,
    media_files,
    media_path,
    payload,
    preview_files,
    preview_path,
    read_catalog,
    v2_catalog,
    write_file,
    write_vault,
)


def completed(names):
    """Downloaded files, ignoring partial-download artifacts."""
    return [n for n in names if not n.endswith(".part")]


def paths_of(source):
    return [path for _method, path in source.requests]


# --- Phrase: "| Media | `<source>/media/<entry_id>` | `<vault>/media/` |
#     Filename contains entry `id` |"
def test_media_is_fetched_from_the_media_path(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    run("sync", "vault")
    assert media_path("e1") in paths_of(source)


def test_media_lands_in_the_vault_media_directory(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    run("sync", "vault")
    assert completed(media_files(tmp_path)) == ["e1.mp4"]


def test_media_filename_contains_the_entry_id(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("abc-123")]))
    source.set_entry_assets("abc-123")
    run("sync", "vault")
    names = completed(media_files(tmp_path))
    assert len(names) == 1, names
    assert "abc-123" in names[0]


def test_media_file_holds_the_served_bytes(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", body=b"\x00\x01payload")
    source.set_preview("e1")
    run("sync", "vault")
    with open(os.path.join(str(tmp_path), "vault", "media", "e1.mp4"), "rb") as fh:
        assert fh.read() == b"\x00\x01payload"


# --- Phrase: "| Media with format override |
#     `<source>/media/<entry_id>.<format>` | `<vault>/media/` |
#     Extension = format string |"
def test_format_override_changes_the_remote_path(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", fmt="webm")
    source.set_preview("e1")
    run("sync", "vault", "--format=webm")
    requested = paths_of(source)
    assert media_path("e1", "webm") in requested
    assert media_path("e1") not in requested


def test_format_override_sets_the_output_extension(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    # Content-Type deliberately disagrees with the override.
    source.set_media("e1", fmt="webm", content_type="video/mp4")
    source.set_preview("e1")
    run("sync", "vault", "--format=webm")
    assert completed(media_files(tmp_path)) == ["e1.webm"]


# --- Phrase: "| Media extension with override | Use override string as
#     extension |" (context: the string is used as given, see AMBIGUITIES T36)
@pytest.mark.parametrize("fmt", ["mp4", "webm", "m4a", "dat"])
def test_override_string_is_used_verbatim_as_extension(
    run, source, vault, tmp_path, fmt
):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", fmt=fmt)
    source.set_preview("e1")
    run("sync", "vault", "--format=%s" % fmt)
    assert completed(media_files(tmp_path)) == ["e1.%s" % fmt]


# --- Phrase: "Override media download format" (context: the override is a
#     media format; previews are unaffected -- see AMBIGUITIES T36)
def test_format_override_does_not_change_the_preview_path(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", fmt="webm")
    source.set_preview("e1")
    run("sync", "vault", "--format=webm")
    assert preview_path("e1") in paths_of(source)


# --- Phrase: "| Preview | `<source>/preview/<entry_id>` | `<vault>/previews/`
#     | Filename contains entry `id` |"
def test_preview_is_fetched_from_the_preview_path(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    run("sync", "vault")
    assert preview_path("e1") in paths_of(source)


def test_preview_lands_in_the_vault_previews_directory(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    run("sync", "vault")
    names = completed(preview_files(tmp_path))
    assert len(names) == 1, names
    assert "e1" in names[0]


# --- Phrase: "| Candidate selection | Only entries without a corresponding
#     media file in `<vault>/media/` are candidates |"
def test_entry_with_existing_media_file_is_not_a_candidate(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    assert run("sync", "vault").returncode == 0
    source.requests.clear()
    assert run("sync", "vault").returncode == 0
    assert media_path("e1") not in paths_of(source)


def test_pre_existing_media_file_suppresses_the_download(
    run, source, vault, tmp_path
):
    write_file(os.path.join(str(tmp_path), "vault", "media", "e1.mp4"), b"old")
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1", body=b"new")
    run("sync", "vault")
    assert media_path("e1") not in paths_of(source)
    with open(os.path.join(str(tmp_path), "vault", "media", "e1.mp4"), "rb") as fh:
        assert fh.read() == b"old"


def test_existing_media_for_one_entry_does_not_block_another(
    run, source, vault, tmp_path
):
    write_file(os.path.join(str(tmp_path), "vault", "media", "e1.mp4"))
    source.set_payload(payload(episodes=[entry("e1"), entry("e2")]))
    source.set_entry_assets("e1")
    source.set_entry_assets("e2")
    run("sync", "vault")
    assert media_path("e1") not in paths_of(source)
    assert media_path("e2") in paths_of(source)


# --- Phrase: "Only entries without a corresponding media file" (context: a
#     media file for a *different* id whose name merely starts with the same
#     text is not a corresponding file)
def test_similar_filename_does_not_count_as_the_entry_media(
    run, source, vault, tmp_path
):
    write_file(os.path.join(str(tmp_path), "vault", "media", "e10.mp4"))
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    run("sync", "vault")
    assert media_path("e1") in paths_of(source)


# --- Phrase: "| Candidate order | Catalog order within category |" +
#     "| Per-category limit | Download first `N` candidates in candidate
#     order |"
def test_limit_selects_the_first_candidates_in_catalog_order(
    run, source, vault, tmp_path
):
    # Catalog order is newest `published` first: e2, e3, e1.
    source.set_payload(
        payload(
            episodes=[
                entry("e1", published="2024-01-01T00:00:00"),
                entry("e2", published="2024-03-01T00:00:00"),
                entry("e3", published="2024-02-01T00:00:00"),
            ]
        )
    )
    for eid in ("e1", "e2", "e3"):
        source.set_entry_assets(eid)
    assert run("sync", "vault", "--episodes=2").returncode == 0
    assert completed(media_files(tmp_path)) == ["e2.mp4", "e3.mp4"]


def test_limit_of_one_downloads_only_the_first_candidate(
    run, source, vault, tmp_path
):
    source.set_payload(
        payload(
            episodes=[
                entry("old", published="2020-01-01T00:00:00"),
                entry("new", published="2025-01-01T00:00:00"),
            ]
        )
    )
    source.set_entry_assets("old")
    source.set_entry_assets("new")
    run("sync", "vault", "--episodes=1")
    assert completed(media_files(tmp_path)) == ["new.mp4"]


# --- Phrase: "non-negative integer" + "Download first `N` candidates"
#     (context: `N` of zero selects nothing -- see AMBIGUITIES T37)
def test_limit_zero_downloads_nothing_from_that_category(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")], clips=[entry("c1")]))
    source.set_entry_assets("e1")
    source.set_entry_assets("c1")
    run("sync", "vault", "--episodes=0")
    assert completed(media_files(tmp_path)) == ["c1.mp4"]


# --- Phrase: "| Omitted limit | No limit for that category |"
def test_omitted_limit_downloads_every_candidate(run, source, vault, tmp_path):
    episodes = [entry("e%d" % i, published="2024-01-%02dT00:00:00" % (i + 1))
                for i in range(5)]
    source.set_payload(payload(episodes=episodes))
    for item in episodes:
        source.set_entry_assets(item["id"])
    run("sync", "vault")
    assert len(completed(media_files(tmp_path))) == 5


def test_limit_applies_only_to_its_own_category(run, source, vault, tmp_path):
    source.set_payload(
        payload(
            episodes=[entry("e1"), entry("e2", published="2023-01-01T00:00:00")],
            streams=[entry("s1"), entry("s2", published="2023-01-01T00:00:00")],
            clips=[entry("c1"), entry("c2", published="2023-01-01T00:00:00")],
        )
    )
    for eid in ("e1", "e2", "s1", "s2", "c1", "c2"):
        source.set_entry_assets(eid)
    run("sync", "vault", "--episodes=1", "--streams=0")
    assert completed(media_files(tmp_path)) == ["c1.mp4", "c2.mp4", "e1.mp4"]


# --- Phrase: "| Media extension without override | Derive from HTTP
#     `Content-Type` |" (see AMBIGUITIES T22 for the mapping)
@pytest.mark.parametrize(
    "content_type,extension",
    [
        ("video/mp4", "mp4"),
        ("video/webm", "webm"),
        ("audio/mpeg", "mp3"),
        ("image/png", "png"),
        ("image/jpeg", "jpg"),
    ],
)
def test_media_extension_derives_from_content_type(
    run, source, vault, tmp_path, content_type, extension
):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", content_type=content_type)
    source.set_preview("e1")
    run("sync", "vault")
    assert completed(media_files(tmp_path)) == ["e1.%s" % extension]


def test_content_type_parameters_are_ignored(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", content_type="video/mp4; charset=binary")
    source.set_preview("e1")
    run("sync", "vault")
    assert completed(media_files(tmp_path)) == ["e1.mp4"]


# --- Phrase: "| Successful HTTP download response | Any successful response is
#     treated as downloadable content; implementations are not required to
#     validate payload semantics beyond using `Content-Type` for extension
#     derivation |"
def test_any_successful_response_is_stored(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", body=b"not really a video", content_type="text/html")
    source.set_preview("e1")
    result = run("sync", "vault")
    assert result.returncode == 0, result
    assert len(completed(media_files(tmp_path))) == 1


def test_empty_successful_response_is_stored(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", body=b"")
    source.set_preview("e1")
    run("sync", "vault")
    assert completed(media_files(tmp_path)) == ["e1.mp4"]


# --- Phrase: "| Partial artifacts | Stale partial-download artifacts must not
#     block a later successful download |"
def test_stale_partial_artifact_does_not_block_the_download(
    run, source, vault, tmp_path
):
    write_file(
        os.path.join(str(tmp_path), "vault", "media", "e1.mp4.part"), b"half"
    )
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1", body=b"whole")
    assert run("sync", "vault").returncode == 0
    path = os.path.join(str(tmp_path), "vault", "media", "e1.mp4")
    assert os.path.isfile(path)
    with open(path, "rb") as fh:
        assert fh.read() == b"whole"


def test_partial_artifact_is_not_a_corresponding_media_file(
    run, source, vault, tmp_path
):
    write_file(os.path.join(str(tmp_path), "vault", "media", "e1.part"))
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    run("sync", "vault")
    assert media_path("e1") in paths_of(source)


def test_failed_download_leaves_no_completed_file(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", status=404)
    run("sync", "vault")
    assert completed(media_files(tmp_path)) == []


# --- Phrase: "| Permanent download failure | Warning to stderr; continue with
#     remaining entries |" (and Error Handling: exit `0`)
def test_permanent_failure_warns_and_continues(run, source, vault, tmp_path):
    source.set_payload(
        payload(
            episodes=[
                entry("e1", published="2024-02-01T00:00:00"),
                entry("e2", published="2024-01-01T00:00:00"),
            ]
        )
    )
    source.set_media("e1", status=404)
    source.set_preview("e1", status=404)
    source.set_entry_assets("e2")
    result = run("sync", "vault")
    assert result.returncode == 0, result
    assert "e1" in result.stderr, result
    assert completed(media_files(tmp_path)) == ["e2.mp4"]


def test_permanent_failure_is_not_retried(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", status=404)
    source.set_preview("e1", status=404)
    run("sync", "vault")
    assert source.hits(media_path("e1")) == 1, source.requests


def test_warning_is_emitted_per_affected_entry(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1"), entry("e2")]))
    source.set_media("e1", status=404)
    source.set_media("e2", status=404)
    source.set_preview("e1", status=404)
    source.set_preview("e2", status=404)
    result = run("sync", "vault")
    assert "e1" in result.stderr and "e2" in result.stderr, result


# --- Phrase: "| Transient download failure | Retry, then warn to stderr after
#     retries exhausted; continue with remaining entries |"
def test_transient_failure_is_retried_until_it_succeeds(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", fail_times=2, fail_status=503)
    source.set_preview("e1")
    result = run("sync", "vault")
    assert result.returncode == 0, result
    assert completed(media_files(tmp_path)) == ["e1.mp4"]
    assert source.hits(media_path("e1")) > 1, source.requests


def test_transient_failure_warns_after_retries_are_exhausted(
    run, source, vault, tmp_path
):
    source.set_payload(
        payload(
            episodes=[
                entry("e1", published="2024-02-01T00:00:00"),
                entry("e2", published="2024-01-01T00:00:00"),
            ]
        )
    )
    source.set_media("e1", status=503)
    source.set_preview("e1", status=503)
    source.set_entry_assets("e2")
    result = run("sync", "vault")
    assert result.returncode == 0, result
    assert "e1" in result.stderr, result
    assert source.hits(media_path("e1")) > 1, source.requests
    assert completed(media_files(tmp_path)) == ["e2.mp4"]


# --- Phrase: "| Partial artifacts | ... must not block a later successful
#     download |" (context: an entry that failed once is a candidate again)
def test_entry_that_failed_is_downloaded_on_the_next_run(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_media("e1", status=503)
    source.set_preview("e1", status=503)
    run("sync", "vault")
    source.set_entry_assets("e1")
    assert run("sync", "vault").returncode == 0
    assert completed(media_files(tmp_path)) == ["e1.mp4"]


# --- Phrase: "| Persistence boundary | Metadata changes must be durably saved
#     before successful sync returns, including runs with download failures |"
#     + "| Download failure interaction | Metadata save still occurs even when
#     one or more downloads fail |"
def test_metadata_is_saved_even_when_downloads_fail(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", title="Saved")]))
    source.set_media("e1", status=404)
    source.set_preview("e1", status=404)
    result = run("sync", "vault")
    assert result.returncode == 0, result
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]


def test_history_update_is_saved_even_when_downloads_fail(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1", title="First")]))
    source.set_entry_assets("e1")
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", title="Second")]))
    source.assets.clear()  # every asset path now answers 404
    run("sync", "vault")
    stored = read_catalog(tmp_path)["episodes"][0]
    assert sorted(stored["title"].values()) == ["First", "Second"]


# --- Phrase: "| Save timing | Metadata phase persists before successful `sync`
#     returns |"
def test_catalog_is_persisted_by_a_successful_sync(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    assert run("sync", "vault").returncode == 0
    assert read_catalog(tmp_path)["episodes"]


# --- Phrase: "Because `sync` auto-migrates v1 and v2 vaults to v3 during the
#     metadata phase, the download phase always operates against a v3 catalog.
#     The source URL for downloads is the migrated `source` value."
def test_legacy_v2_vault_downloads_from_the_migrated_source(
    run, source, tmp_path
):
    write_vault(tmp_path, v2_catalog(source=source.url))
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    result = run("sync", "vault")
    assert result.returncode == 0, result
    assert media_path("e1") in paths_of(source)
    assert completed(media_files(tmp_path)) == ["e1.mp4"]


def test_legacy_v2_vault_download_phase_uses_the_v3_catalog(
    run, source, tmp_path
):
    from conftest import v2_entry

    write_vault(
        tmp_path, v2_catalog(source=source.url, episodes=[v2_entry("old")])
    )
    source.set_payload(payload(episodes=[entry("old"), entry("new")]))
    for eid in ("old", "new"):
        source.set_entry_assets(eid)
    assert run("sync", "vault").returncode == 0
    assert read_catalog(tmp_path)["version"] == 3
    assert completed(media_files(tmp_path)) == ["new.mp4", "old.mp4"]
