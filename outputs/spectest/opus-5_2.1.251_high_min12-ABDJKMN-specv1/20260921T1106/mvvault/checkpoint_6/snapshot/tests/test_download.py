"""Spec sections: Download Sources and Targets / Download Rules /
`sync` on Legacy Vaults — Download Phase / `catalog.json` Persistence."""
import json
import os

import pytest
from conftest import (MEDIA_DIR, PREVIEW_DIR, V1_SOURCE_PREFIX, entry, find,
                      make_vault, media_names, payload, place_file,
                      preview_names, read_catalog, stored_ids, v1_catalog,
                      v1_entry, v2_catalog, v2_entry)


def seed(run, source, episodes=(), streams=(), clips=(), name="v"):
    assert run("init", name, source.url).returncode == 0
    source.payload = payload(episodes, streams, clips)
    return name


# --------------------------------------------------------------------------
# Download Sources and Targets
# --------------------------------------------------------------------------

# Phrase: "Media | `<source>/media/<entry_id>` | `<vault>/media/` |
#          Filename contains entry `id`"
def test_media_url_local_dir_and_filename(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", body=b"MEDIA", content_type="video/mp4")
    source.preview("e1")

    assert run("sync", "v").returncode == 0
    assert source.requested(source.media_path("e1")), "media URL not requested"

    names = media_names(tmp_path / "v")
    assert len(names) == 1 and "e1" in names[0]
    assert (tmp_path / "v" / MEDIA_DIR / names[0]).read_bytes() == b"MEDIA"


# Phrase: "Media with format override | `<source>/media/<entry_id>.<format>` |
#          ... | Extension = format string"
def test_media_format_override_url_and_extension(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", fmt="webm", body=b"W", content_type="video/mp4")
    source.preview("e1")

    assert run("sync", "v", "--format=webm").returncode == 0

    assert source.requested(source.media_path("e1", "webm"))
    assert source.requested(source.media_path("e1")) == []
    assert media_names(tmp_path / "v") == ["e1.webm"]


# Phrase: "Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` |
#          Filename contains entry `id`"
def test_preview_url_local_dir_and_filename(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1")
    source.preview("e1", body=b"PNGDATA", content_type="image/png")

    assert run("sync", "v").returncode == 0
    assert source.requested(source.preview_path("e1"))

    names = preview_names(tmp_path / "v")
    assert len(names) == 1 and "e1" in names[0]
    assert (tmp_path / "v" / PREVIEW_DIR / names[0]).read_bytes() == b"PNGDATA"


# Phrase: "Preview | `<source>/preview/<entry_id>`"
# Context: the format override applies to media only, never to the preview URL.
def test_format_override_does_not_change_preview_url(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", fmt="mp3")
    source.preview("e1")
    assert run("sync", "v", "--format=mp3").returncode == 0
    assert source.requested(source.preview_path("e1"))


# Phrase: Local directories are `<vault>/media/` and `<vault>/previews/`.
def test_download_directories_live_inside_the_vault(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.assets("e1")
    assert run("sync", "v").returncode == 0
    assert (tmp_path / "v" / MEDIA_DIR).is_dir()
    assert (tmp_path / "v" / PREVIEW_DIR).is_dir()
    assert not (tmp_path / MEDIA_DIR).exists()


# --------------------------------------------------------------------------
# Download Rules
# --------------------------------------------------------------------------

# Phrase: "Candidate selection | Only entries without a corresponding media
#          file in `<vault>/media/` are candidates"
def test_entry_with_existing_media_is_not_a_candidate(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1"), entry("e2")])
    place_file(tmp_path / "v", MEDIA_DIR, "e1.mp4", b"kept")
    source.assets("e1", "e2")

    assert run("sync", "v").returncode == 0

    assert source.hits(source.media_path("e1")) == 0
    assert source.hits(source.media_path("e2")) == 1
    assert (tmp_path / "v" / MEDIA_DIR / "e1.mp4").read_bytes() == b"kept"


# Phrase: "A file matches if the name contains entry `id`"
# Context: containment, not equality, and the extension is irrelevant.
def test_media_match_is_substring_containment(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    place_file(tmp_path / "v", MEDIA_DIR, "0042-e1-final.weird")
    source.assets("e1")
    assert run("sync", "v").returncode == 0
    assert source.hits(source.media_path("e1")) == 0


# Phrase: "apart from partial downloads"
# Context: a leftover partial artifact does not count as a matching file.
def test_partial_artifact_does_not_satisfy_candidate_selection(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    place_file(tmp_path / "v", MEDIA_DIR, "e1.mp4.part", b"half")
    source.assets("e1")

    assert run("sync", "v").returncode == 0

    assert source.hits(source.media_path("e1")) == 1
    assert "e1.mp4" in media_names(tmp_path / "v")


# Phrase: "Partial artifacts | Stale partial-download artifacts must not block
#          a later successful download"
def test_stale_partial_is_replaced_by_the_real_download(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    place_file(tmp_path / "v", MEDIA_DIR, "e1.mp4.part", b"stale")
    source.media("e1", body=b"FULL", content_type="video/mp4")
    source.preview("e1")

    assert run("sync", "v").returncode == 0

    assert (tmp_path / "v" / MEDIA_DIR / "e1.mp4").read_bytes() == b"FULL"


# Phrase: "Candidate order | Catalog order within category"
# Context: with a limit of one, the first catalog entry is the one fetched.
def test_candidate_order_follows_catalog_order(run, source, tmp_path):
    seed(run, source, episodes=[
        entry("e1", published="2024-01-01T00:00:00"),
        entry("e2", published="2024-03-01T00:00:00"),
        entry("e3", published="2024-02-01T00:00:00"),
    ])
    source.assets("e1", "e2", "e3")
    assert run("sync", "v", "--episodes=1").returncode == 0

    catalog = read_catalog(tmp_path / "v")
    first = catalog["episodes"][0]["id"]
    assert stored_ids(media_names(tmp_path / "v")) == [first]


# Phrase: "Per-category limit | Download first `N` candidates in candidate
#          order"
# Context: already-downloaded entries are not candidates, so they do not
# consume the limit.
def test_limit_counts_candidates_not_catalog_entries(run, source, tmp_path):
    seed(run, source, episodes=[entry("e%d" % i) for i in (1, 2, 3)])
    place_file(tmp_path / "v", MEDIA_DIR, "e1.mp4")
    source.assets("e1", "e2", "e3")

    assert run("sync", "v", "--episodes=2").returncode == 0

    assert sorted(stored_ids(media_names(tmp_path / "v"))) == ["e1", "e2", "e3"]


# Phrase: "Media extension without override | Derive from HTTP `Content-Type`"
@pytest.mark.parametrize("content_type,expected", [
    ("video/mp4", ".mp4"),
    ("audio/mpeg", ".mp3"),
    ("image/png", ".png"),
    ("application/json", ".json"),
])
def test_media_extension_derives_from_content_type(run, source, tmp_path,
                                                   content_type, expected):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", body=b"X", content_type=content_type)
    source.preview("e1")
    assert run("sync", "v").returncode == 0
    names = media_names(tmp_path / "v")
    assert names == ["e1" + expected]


# Phrase: "Derive from HTTP `Content-Type`"
# Context: Content-Type parameters are not part of the extension.
def test_content_type_parameters_are_ignored(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", content_type="video/mp4; charset=binary")
    source.preview("e1")
    assert run("sync", "v").returncode == 0
    assert media_names(tmp_path / "v") == ["e1.mp4"]


# Phrase: "Media extension with override | Use override string as extension"
# Context: the override wins over the served Content-Type.
def test_override_extension_beats_content_type(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", fmt="ogg", content_type="video/mp4")
    source.preview("e1")
    assert run("sync", "v", "--format=ogg").returncode == 0
    assert media_names(tmp_path / "v") == ["e1.ogg"]


# Phrase: "Successful HTTP download response | Any successful response is
#          treated as downloadable content"
# Context: a JSON body is stored as-is rather than rejected.
def test_any_successful_response_is_stored(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", body=b'{"not":"media"}', content_type="application/json")
    source.preview("e1")

    result = run("sync", "v")

    assert result.returncode == 0
    names = media_names(tmp_path / "v")
    assert len(names) == 1
    assert (tmp_path / "v" / MEDIA_DIR / names[0]).read_bytes() == b'{"not":"media"}'


# Phrase: "Permanent download failure | Warning to stderr; continue with
#          remaining entries"
def test_permanent_failure_warns_and_continues(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1"), entry("e2")])
    source.media("e1", status=404)
    source.assets("e2")

    result = run("sync", "v")

    assert result.returncode == 0
    assert "e1" in result.stderr
    assert stored_ids(media_names(tmp_path / "v")) == ["e2"]


# Phrase: "Permanent download failure | Warning to stderr"
# Context: the warning is not printed on stdout.
def test_permanent_failure_warning_not_on_stdout(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", status=404)
    result = run("sync", "v")
    assert result.returncode == 0
    assert "e1" in result.stderr


# Phrase: "Permanently unavailable content during download | stderr | `0` |
#          Warning per affected entry; continue"
def test_one_warning_per_affected_entry(run, source, tmp_path):
    ids = ["e1", "e2", "e3"]
    seed(run, source, episodes=[entry(i) for i in ids])
    for eid in ids:
        source.media(eid, status=404)
    result = run("sync", "v")
    assert result.returncode == 0
    for eid in ids:
        assert eid in result.stderr


# Phrase: "Transient download failure | Retry, then warn to stderr after
#          retries exhausted; continue with remaining entries"
# Context: a route that fails once and then succeeds is downloaded by the retry.
def test_transient_failure_is_retried_until_it_succeeds(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", body=b"OK", content_type="video/mp4", transient=1)
    source.preview("e1")

    result = run("sync", "v")

    assert result.returncode == 0, result.stderr
    assert source.hits(source.media_path("e1")) >= 2
    assert (tmp_path / "v" / MEDIA_DIR / "e1.mp4").read_bytes() == b"OK"


# Phrase: "Transient download failure after retries exhausted | stderr | `0` |
#          Warning per affected entry; continue"
def test_transient_failure_exhausted_warns_and_continues(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1"), entry("e2")])
    source.media("e1", transient=99)           # never recovers
    source.assets("e2")

    result = run("sync", "v")

    assert result.returncode == 0
    assert source.hits(source.media_path("e1")) >= 2, "no retry happened"
    assert "e1" in result.stderr
    assert stored_ids(media_names(tmp_path / "v")) == ["e2"]


# Phrase: "Permanent download failure" vs "Transient download failure | Retry"
# Context: a permanently missing asset is not retried.
def test_permanent_failure_is_not_retried(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", status=404)
    assert run("sync", "v").returncode == 0
    assert source.hits(source.media_path("e1")) == 1


# Phrase: "Permanent download failure ... continue with remaining entries"
# Context: a failed media download leaves no file behind, partial or final.
def test_failed_download_leaves_no_artifact(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", status=404)
    assert run("sync", "v").returncode == 0
    assert media_names(tmp_path / "v") == []


# Phrase: "Persistence boundary | Metadata changes must be durably saved
#          before successful sync returns, including runs with download
#          failures"
def test_metadata_is_saved_despite_download_failures(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1", title="Kept")])
    source.media("e1", status=404)

    result = run("sync", "v")

    assert result.returncode == 0
    catalog = read_catalog(tmp_path / "v")
    item = find(catalog, "episodes", "e1")
    assert item["title"][max(item["title"])] == "Kept"


# Phrase: "`catalog.json` Persistence During `sync`" — "Save timing | Metadata
#          phase persists before successful `sync` returns"
def test_catalog_written_before_sync_returns(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.assets("e1")
    assert run("sync", "v").returncode == 0
    assert (tmp_path / "v" / "catalog.json").is_file()


# Phrase: "Download failure interaction | Metadata save still occurs even when
#          one or more downloads fail"
# Context: an update on a second sync reaches disk even though downloads fail.
def test_update_persisted_when_downloads_fail(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1", title="One")])
    assert run("sync", "v", "--skip-download").returncode == 0
    source.payload = payload(episodes=[entry("e1", title="Two")])

    result = run("sync", "v")             # media route is absent -> 404

    assert result.returncode == 0
    item = find(read_catalog(tmp_path / "v"), "episodes", "e1")
    assert item["title"][max(item["title"])] == "Two"


# --------------------------------------------------------------------------
# `sync` on Legacy Vaults — Download Phase
# --------------------------------------------------------------------------

# Phrase: "Because `sync` auto-migrates v1 and v2 vaults to v3 during the
#          metadata phase, the download phase always operates against a v3
#          catalog. The source URL for downloads is the migrated `source`
#          value."
# Context: v2 keeps its `source` field, so downloads come from it.
def test_v2_vault_downloads_from_migrated_source(run, source, tmp_path):
    make_vault(tmp_path, "v", v2_catalog(source=source.url,
                                         episodes=[v2_entry("e1")]))
    source.payload = payload(episodes=[entry("e1")])
    source.assets("e1")

    result = run("sync", "v")

    assert result.returncode == 0, result.stderr
    assert read_catalog(tmp_path / "v")["version"] == 3
    assert stored_ids(media_names(tmp_path / "v")) == ["e1"]


# Phrase: "The source URL for downloads is the migrated `source` value."
# Context: a v1 vault derives its source from `source_id`, so the asset URLs
# hang off `https://media.example.com/channel/<source_id>`.
def test_v1_vault_downloads_from_derived_source(run_inproc, tmp_path):
    make_vault(tmp_path, "v", v1_catalog("chan42", [v1_entry("e1")]))
    base = V1_SOURCE_PREFIX + "chan42"
    result = run_inproc("sync", "v", responses={
        base: payload(episodes=[entry("e1")]),
        base + "/media/e1": (b"M", "video/mp4"),
        base + "/preview/e1": (b"P", "image/png"),
    })

    assert result.returncode == 0, result.stderr
    assert base + "/media/e1" in result.calls
    assert media_names(tmp_path / "v") == ["e1.mp4"]
    assert stored_ids(preview_names(tmp_path / "v")) == ["e1"]


# Phrase: "the download phase always operates against a v3 catalog"
# Context: categories a v1 vault does not have contribute no downloads, and the
# migrated entries land in `episodes`.
def test_v1_migration_downloads_only_migrated_entries(run_inproc, tmp_path):
    make_vault(tmp_path, "v", v1_catalog("chan42",
                                         [v1_entry("a1"), v1_entry("a2")]))
    base = V1_SOURCE_PREFIX + "chan42"
    result = run_inproc("sync", "v", "--episodes=1", responses={
        base: payload(episodes=[entry("a1"), entry("a2")]),
        base + "/media/a1": (b"M", "video/mp4"),
        base + "/media/a2": (b"M", "video/mp4"),
        base + "/preview/a1": (b"P", "image/png"),
        base + "/preview/a2": (b"P", "image/png"),
    })

    assert result.returncode == 0, result.stderr
    assert len(media_names(tmp_path / "v")) == 1
