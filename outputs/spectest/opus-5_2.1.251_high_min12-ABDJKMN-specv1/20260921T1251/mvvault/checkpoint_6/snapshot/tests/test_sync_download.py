"""Spec sections: Download Sources and Targets, Download Rules, and
`sync` on Legacy Vaults - Download Phase."""

from __future__ import annotations


def payload_with(helpers, episodes=(), streams=(), clips=(), **kwargs):
    def build(ids):
        return [helpers.make_source_entry(i, **kwargs) for i in ids]

    return helpers.make_payload(
        episodes=build(episodes), streams=build(streams), clips=build(clips))


# ---------------------------------------------------------------------------
# | Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename contains
#   entry `id` |
# ---------------------------------------------------------------------------

# Spec: | Media | `<source>/media/<entry_id>` | ... |
def test_media_is_fetched_from_source_media_path(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert source.hits(helpers.media_path("e1")) == 1


# Spec: | Media | ... | `<vault>/media/` | ... |
def test_media_is_stored_in_vault_media_directory(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert (helpers.media_dir(vault)).is_dir()
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]


# Spec: | Media | ... | Filename contains entry `id` |
def test_media_filename_contains_entry_id(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["ep-42"]))
    source.serve_entry("ep-42")
    assert run_cli("sync", "vault").returncode == 0
    names = helpers.listing(helpers.media_dir(vault))
    assert names and all("ep-42" in name for name in names)


# Spec: | Media | ... | (content is written through unchanged)
def test_media_body_is_written_to_disk(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", body=b"\x00\x01binary-media")
    source.set_preview("e1")
    assert run_cli("sync", "vault").returncode == 0
    stored = next(helpers.media_dir(vault).iterdir())
    assert stored.read_bytes() == b"\x00\x01binary-media"


# ---------------------------------------------------------------------------
# | Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename
#   contains entry `id` |
# ---------------------------------------------------------------------------

# Spec: | Preview | `<source>/preview/<entry_id>` | ... |
def test_preview_is_fetched_from_source_preview_path(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert source.hits(helpers.preview_path("e1")) == 1


# Spec: | Preview | ... | `<vault>/previews/` | Filename contains entry `id` |
def test_preview_is_stored_in_vault_previews_directory(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    names = helpers.listing(helpers.preview_dir(vault))
    assert names and all("e1" in name for name in names)


# Spec: | Preview | ... | (the preview is not written into `<vault>/media/`)
def test_preview_does_not_land_in_media_directory(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", body=b"media", content_type="video/mp4")
    source.set_preview("e1", body=b"preview", content_type="image/jpeg")
    assert run_cli("sync", "vault").returncode == 0
    media_bytes = [p.read_bytes() for p in helpers.media_dir(vault).iterdir()]
    assert media_bytes == [b"media"]


# ---------------------------------------------------------------------------
# | Candidate selection | Only entries without a corresponding media file in
#   `<vault>/media/` are candidates; A file matches if the name contains entry
#   `id`, apart from partial downloads |
# ---------------------------------------------------------------------------

# Spec: | Candidate selection | Only entries without a corresponding media file
#   in `<vault>/media/` are candidates |
def test_entry_with_existing_media_file_is_not_a_candidate(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    media = helpers.media_dir(vault)
    media.mkdir(parents=True, exist_ok=True)
    (media / "e1.mp4").write_bytes(b"already here")
    assert run_cli("sync", "vault").returncode == 0
    assert source.hits(helpers.media_path("e1")) == 0
    assert (media / "e1.mp4").read_bytes() == b"already here"


# Spec: | Candidate selection | ... A file matches if the name contains entry `id` |
# Context: the match is by substring, not by exact `<id>.<ext>` name.
def test_media_match_is_by_name_containing_the_id(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    media = helpers.media_dir(vault)
    media.mkdir(parents=True, exist_ok=True)
    (media / "downloaded-e1-final.mkv").write_bytes(b"already here")
    assert run_cli("sync", "vault").returncode == 0
    assert source.hits(helpers.media_path("e1")) == 0


# Spec: | Candidate selection | ... apart from partial downloads |
def test_partial_download_artifact_does_not_make_an_entry_a_non_candidate(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    media = helpers.media_dir(vault)
    media.mkdir(parents=True, exist_ok=True)
    (media / "e1.part").write_bytes(b"half a file")
    assert run_cli("sync", "vault").returncode == 0
    assert source.hits(helpers.media_path("e1")) == 1


# Spec: | Partial artifacts | Stale partial-download artifacts must not block a
#   later successful download |
def test_stale_partial_artifact_is_replaced_by_a_complete_download(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", body=b"complete", content_type="video/mp4")
    source.set_preview("e1")
    media = helpers.media_dir(vault)
    media.mkdir(parents=True, exist_ok=True)
    (media / "e1.part").write_bytes(b"stale")
    assert run_cli("sync", "vault").returncode == 0
    complete = [p for p in media.iterdir() if p.read_bytes() == b"complete"]
    assert complete, helpers.listing(media)


# Spec: | Partial artifacts | Stale partial-download artifacts must not block a
#   later successful download |
# Context: a completed download leaves no partial artifact behind.
def test_successful_download_leaves_no_partial_artifact(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    names = helpers.listing(helpers.media_dir(vault))
    assert not any(name.endswith(".part") for name in names), names


# Spec: | Candidate selection | Only entries without a corresponding media file
#   in `<vault>/media/` are candidates |
# Context: a second sync re-downloads nothing.
def test_second_sync_downloads_nothing_new(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert run_cli("sync", "vault").returncode == 0
    assert source.hits(helpers.media_path("e1")) == 1


# ---------------------------------------------------------------------------
# | Candidate order | Catalog order within category |
# | Per-category limit | Download first `N` candidates in candidate order |
# ---------------------------------------------------------------------------

# Spec: | Candidate order | Catalog order within category |
# Context: catalog order is newest `published` first, so the limit picks the
# first entry of the stored catalog, not of the source payload.
def test_candidate_order_follows_catalog_order(
    run_cli, vault, source, helpers, workdir
):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("e1", published="2024-01-01T00:00:00"),
        helpers.make_source_entry("e2", published="2024-03-01T00:00:00"),
        helpers.make_source_entry("e3", published="2024-02-01T00:00:00"),
    ]))
    for entry_id in ("e1", "e2", "e3"):
        source.serve_entry(entry_id)
    assert run_cli("sync", "vault", "--episodes=1").returncode == 0
    catalog = helpers.read_catalog(workdir)
    first_in_catalog = catalog["episodes"][0]["id"]
    assert first_in_catalog == "e2"
    assert helpers.listing(helpers.media_dir(vault)) == [f"{first_in_catalog}.mp4"]


# Spec: | Per-category limit | Download first `N` candidates in candidate order |
def test_limit_takes_the_first_n_candidates_in_order(
    run_cli, vault, source, helpers, workdir
):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("e1", published="2024-01-01T00:00:00"),
        helpers.make_source_entry("e2", published="2024-03-01T00:00:00"),
        helpers.make_source_entry("e3", published="2024-02-01T00:00:00"),
    ]))
    for entry_id in ("e1", "e2", "e3"):
        source.serve_entry(entry_id)
    assert run_cli("sync", "vault", "--episodes=2").returncode == 0
    assert sorted(helpers.listing(helpers.media_dir(vault))) == ["e2.mp4", "e3.mp4"]


# Spec: | Per-category limit | Download first `N` candidates in candidate order |
# Context: entries that already have media are not candidates, so the limit
# applies to what remains.
def test_limit_counts_candidates_not_entries(run_cli, vault, source, helpers):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("e1", published="2024-03-01T00:00:00"),
        helpers.make_source_entry("e2", published="2024-02-01T00:00:00"),
        helpers.make_source_entry("e3", published="2024-01-01T00:00:00"),
    ]))
    for entry_id in ("e1", "e2", "e3"):
        source.serve_entry(entry_id)
    media = helpers.media_dir(vault)
    media.mkdir(parents=True, exist_ok=True)
    (media / "e1.mp4").write_bytes(b"already here")
    assert run_cli("sync", "vault", "--episodes=1").returncode == 0
    assert source.hits(helpers.media_path("e2")) == 1
    assert source.hits(helpers.media_path("e3")) == 0


# Spec: | Download candidate order | Same as catalog order within category |
# Context: repeated runs pick the same candidate.
def test_candidate_selection_is_deterministic(run_cli, vault, source, helpers):
    ids = ["e1", "e2", "e3"]
    source.set(payload_with(helpers, episodes=ids))
    for entry_id in ids:
        source.serve_entry(entry_id)
    assert run_cli("init", "vault2", source.url).returncode == 0
    assert run_cli("sync", "vault", "--episodes=1").returncode == 0
    assert run_cli("sync", "vault2", "--episodes=1").returncode == 0
    first = helpers.listing(helpers.media_dir(vault))
    second = helpers.listing(helpers.media_dir(vault.parent / "vault2"))
    assert first == second


# ---------------------------------------------------------------------------
# | Media extension without override | Derive from HTTP `Content-Type` |
# ---------------------------------------------------------------------------

# Spec: | Media extension without override | Derive from HTTP `Content-Type` |
def test_extension_derived_from_content_type_mp4(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", content_type="video/mp4")
    source.set_preview("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]


# Spec: | Media extension without override | Derive from HTTP `Content-Type` |
def test_extension_derived_from_content_type_mpeg_audio(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", content_type="audio/mpeg")
    source.set_preview("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp3"]


# Spec: | Media extension without override | Derive from HTTP `Content-Type` |
# Context: `Content-Type` parameters are not part of the extension.
def test_content_type_parameters_are_ignored(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", content_type="video/webm; charset=binary")
    source.set_preview("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.webm"]


# Spec: | Preview | ... | Filename contains entry `id` |
# Context: the preview extension also follows its own `Content-Type`.
def test_preview_extension_derived_from_its_content_type(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", content_type="video/mp4")
    source.set_preview("e1", content_type="image/png")
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.preview_dir(vault)) == ["e1.png"]


# ---------------------------------------------------------------------------
# | Successful HTTP download response | Any successful response is treated as
#   downloadable content; implementations are not required to validate payload
#   semantics beyond using `Content-Type` for extension derivation |
# ---------------------------------------------------------------------------

# Spec: | Successful HTTP download response | Any successful response is treated
#   as downloadable content |
def test_any_successful_response_is_stored(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", body=b"this is not really a video",
                     content_type="video/mp4")
    source.set_preview("e1")
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]


# Spec: | Successful HTTP download response | Any successful response ... |
# Context: a `204`-style empty body is still a successful response.
def test_empty_successful_body_is_stored(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", body=b"", content_type="video/mp4")
    source.set_preview("e1")
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]


# ---------------------------------------------------------------------------
# | Permanent download failure | Warning to stderr; continue with remaining
#   entries |
# ---------------------------------------------------------------------------

# Spec: | Permanent download failure | Warning to stderr; ... |
def test_permanent_failure_warns_on_stderr(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    # `e1` has no registered asset: the server answers 404.
    result = run_cli("sync", "vault")
    assert result.returncode == 0
    assert "e1" in result.stderr


# Spec: | Permanently unavailable content during download | stderr | `0` |
#   Warning per affected entry; continue |
def test_permanent_failure_warns_per_affected_entry(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1", "e2"]))
    result = run_cli("sync", "vault")
    assert result.returncode == 0
    assert "e1" in result.stderr
    assert "e2" in result.stderr


# Spec: | Permanent download failure | ... continue with remaining entries |
def test_permanent_failure_does_not_stop_later_entries(
    run_cli, vault, source, helpers
):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("e1", published="2024-03-01T00:00:00"),
        helpers.make_source_entry("e2", published="2024-02-01T00:00:00"),
    ]))
    source.serve_entry("e2")  # e1 is permanently unavailable
    result = run_cli("sync", "vault")
    assert result.returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e2.mp4"]


# Spec: | Permanent download failure | ... continue with remaining entries |
# Context: categories after a failing one are still processed.
def test_permanent_failure_does_not_stop_later_categories(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"], clips=["c1"]))
    source.serve_entry("c1")
    result = run_cli("sync", "vault")
    assert result.returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["c1.mp4"]


# Spec: | Permanent download failure | Warning to stderr; ... |
# Context: a failed media download must not leave a partial file behind.
def test_failed_download_leaves_no_file(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == []


# Spec: | Permanent download failure | ... |
# Context: a preview failure alone does not lose the media file.
def test_preview_failure_keeps_media_download(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1")  # no preview registered
    result = run_cli("sync", "vault")
    assert result.returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]
    assert result.stderr.strip() != ""


# ---------------------------------------------------------------------------
# | Transient download failure | Retry, then warn to stderr after retries
#   exhausted; continue with remaining entries |
# ---------------------------------------------------------------------------

# Spec: | Transient download failure | Retry, ... |
def test_transient_failure_is_retried_until_it_succeeds(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    source.fail_transiently(helpers.media_path("e1"), times=1)
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]
    assert source.hits(helpers.media_path("e1")) >= 2


# Spec: | Transient download failure | ... then warn to stderr after retries
#   exhausted ... |
def test_transient_failure_warns_after_retries_exhausted(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    source.fail_transiently(helpers.media_path("e1"), times=99)
    result = run_cli("sync", "vault")
    assert result.returncode == 0
    assert "e1" in result.stderr
    assert source.hits(helpers.media_path("e1")) >= 2


# Spec: | Transient download failure after retries exhausted | stderr | `0` |
#   Warning per affected entry; continue |
def test_transient_failure_continues_with_remaining_entries(
    run_cli, vault, source, helpers
):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("e1", published="2024-03-01T00:00:00"),
        helpers.make_source_entry("e2", published="2024-02-01T00:00:00"),
    ]))
    source.serve_entry("e1")
    source.serve_entry("e2")
    source.fail_transiently(helpers.media_path("e1"), times=99)
    result = run_cli("sync", "vault")
    assert result.returncode == 0
    assert "e2.mp4" in helpers.listing(helpers.media_dir(vault))


# Spec: | Transient download failure | ... |
# Context: an exhausted transient failure leaves no partial artifact that would
# block a later successful download.
def test_exhausted_transient_failure_allows_a_later_download(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    source.fail_transiently(helpers.media_path("e1"), times=99)
    assert run_cli("sync", "vault").returncode == 0
    source.fail_transiently(helpers.media_path("e1"), times=0)
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]


# ---------------------------------------------------------------------------
# `sync` on Legacy Vaults - Download Phase
#
# "Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata
# phase, the download phase always operates against a v3 catalog. The source
# URL for downloads is the migrated `source` value."
# ---------------------------------------------------------------------------

# Spec: "the download phase always operates against a v3 catalog"
def test_v2_vault_download_phase_runs_after_migration(
    run_cli, make_vault, source, helpers, legacy, workdir
):
    vault_dir = make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert helpers.read_catalog(workdir)["version"] == 3
    assert helpers.listing(helpers.media_dir(vault_dir)) == ["e1.mp4"]


# Spec: "The source URL for downloads is the migrated `source` value."
def test_v2_download_uses_migrated_source_value(
    run_cli, make_vault, source, helpers, legacy
):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert source.hits(helpers.media_path("e1")) == 1


# Spec: "the download phase always operates against a v3 catalog"
# Context: entries migrated from v2 are candidates just like v3 entries.
def test_v2_entries_are_download_candidates(
    run_cli, make_vault, source, helpers, legacy
):
    vault_dir = make_vault(legacy.v2_catalog(
        episodes=[legacy.v2_entry("e1")], clips=[legacy.v2_entry("c1")]))
    source.set(payload_with(helpers, episodes=["e1"], clips=["c1"]))
    source.serve_entry("e1")
    source.serve_entry("c1")
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault_dir)) == ["c1.mp4", "e1.mp4"]


# Spec: "The source URL for downloads is the migrated `source` value."
# Context: for v1 the migrated source is the `media.example.com` channel URL,
# so a download-only run against a v1 vault addresses that host.
def test_v1_download_uses_migrated_channel_url(
    run_cli, make_vault, helpers, legacy
):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")],
                                 source_id="chan-1"))
    result = run_cli("sync", "vault", "--skip-metadata", "--episodes=1")
    assert result.returncode == 0, result.stderr
    assert "media.example.com/channel/chan-1" in result.stderr
