"""Spec sections: `sync` Command (download phase), Download Sources and Targets,
Download Rules."""

from conftest import media_names, media_stems, payload, preview_names, source_entry


def sync_with(run, source, ids, *args, category="episodes"):
    """Serve `ids` in `category` with working assets and run `sync`."""
    source.serve(payload(**{category: [source_entry(i) for i in ids]}))
    source.serve_assets(*ids)
    return run("sync", "vault", *args)


# Spec: Download phase | Retrieve media and preview files after metadata phase
def test_sync_downloads_media_and_preview(run, source, vault):
    result = sync_with(run, source, ["e1"])
    assert result.returncode == 0, result.stderr
    assert media_names(vault) == ["e1.mp4"]
    assert preview_names(vault) == ["e1.png"]


# Spec: Download phase | Retrieve media and preview files after metadata phase
def test_download_phase_runs_after_metadata_phase(run, source, vault):
    sync_with(run, source, ["e1"])
    assert source.requests[0] == "/source.json"
    assert source.asset_requests()


# Spec: Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename contains entry `id`
def test_media_request_path_and_local_directory(run, source, vault):
    sync_with(run, source, ["e1"])
    assert "/source.json/media/e1" in source.requests
    assert (vault / "media" / "e1.mp4").read_bytes() == b"media-bytes"


# Spec: Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename contains `id`
def test_preview_request_path_and_local_directory(run, source, vault):
    sync_with(run, source, ["e1"])
    assert "/source.json/preview/e1" in source.requests
    assert (vault / "previews" / "e1.png").read_bytes() == b"preview-bytes"


# Spec: Media with format override | `<source>/media/<entry_id>.<format>` | Extension = format
def test_format_override_changes_request_path_and_extension(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_media("e1", suffix=".mkv", content_type="video/mp4")
    source.serve_preview("e1")
    result = run("sync", "vault", "--format=mkv")
    assert result.returncode == 0, result.stderr
    assert "/source.json/media/e1.mkv" in source.requests
    assert media_names(vault) == ["e1.mkv"]


# Spec: Media extension with override | Use override string as extension
# (the override wins over whatever `Content-Type` the response carries)
def test_format_override_beats_content_type(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_media("e1", suffix=".wav", content_type="audio/mpeg")
    run("sync", "vault", "--format=wav")
    assert media_names(vault) == ["e1.wav"]


# Spec: Media extension without override | Derive from HTTP `Content-Type`
def test_media_extension_derived_from_content_type(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1"), source_entry("e2")]))
    source.serve_media("e1", content_type="video/webm")
    source.serve_media("e2", content_type="audio/mpeg")
    source.serve_preview("e1")
    source.serve_preview("e2")
    run("sync", "vault")
    assert media_names(vault) == ["e1.webm", "e2.mp3"]


# Spec: Media extension without override | Derive from HTTP `Content-Type`
# (a `Content-Type` carrying parameters still yields a bare extension)
def test_content_type_parameters_are_ignored(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_media("e1", content_type="video/mp4; codecs=avc1")
    source.serve_preview("e1")
    run("sync", "vault")
    assert media_names(vault) == ["e1.mp4"]


# Spec: Candidate selection | Only entries without a corresponding media file are candidates
def test_entry_with_existing_media_file_is_not_a_candidate(run, source, vault):
    (vault / "media").mkdir()
    (vault / "media" / "e1.mp4").write_bytes(b"already here")
    sync_with(run, source, ["e1", "e2"])
    assert "/source.json/media/e1" not in source.requests
    assert "/source.json/media/e2" in source.requests
    assert (vault / "media" / "e1.mp4").read_bytes() == b"already here"


# Spec: Candidate selection | ... (a second sync re-downloads nothing)
def test_second_sync_downloads_nothing_new(run, source, vault):
    sync_with(run, source, ["e1"])
    before = len(source.asset_requests())
    sync_with(run, source, ["e1"])
    assert len(source.asset_requests()) == before


# Spec: Candidate order | Catalog order within category
def test_candidate_order_follows_catalog_order(run, source, vault):
    entries = [
        source_entry("e1", published="2024-01-01T00:00:00"),
        source_entry("e2", published="2024-03-01T00:00:00"),
        source_entry("e3", published="2024-02-01T00:00:00"),
    ]
    source.serve(payload(episodes=entries))
    source.serve_assets("e1", "e2", "e3")
    run("sync", "vault")
    media = [path for path in source.asset_requests() if "/media/" in path]
    # Catalog order is newest `published` first: e2, e3, e1.
    assert media == [
        "/source.json/media/e2",
        "/source.json/media/e3",
        "/source.json/media/e1",
    ]


# Spec: Per-category limit | Download first `N` candidates in candidate order
def test_episode_limit_takes_the_first_n_candidates(run, source, vault):
    entries = [
        source_entry("e1", published="2024-03-01T00:00:00"),
        source_entry("e2", published="2024-02-01T00:00:00"),
        source_entry("e3", published="2024-01-01T00:00:00"),
    ]
    source.serve(payload(episodes=entries))
    source.serve_assets("e1", "e2", "e3")
    assert run("sync", "vault", "--episodes=2").returncode == 0
    assert media_stems(vault) == ["e1", "e2"]


# Spec: `--streams=<n>` | Maximum number of stream media downloads
def test_stream_limit_applies_to_streams_only(run, source, vault):
    source.serve(
        payload(
            episodes=[source_entry("e1"), source_entry("e2")],
            streams=[source_entry("s1"), source_entry("s2")],
        )
    )
    source.serve_assets("e1", "e2", "s1", "s2")
    run("sync", "vault", "--streams=1")
    assert media_stems(vault) == ["e1", "e2", "s1"]


# Spec: `--clips=<n>` | Maximum number of clip media downloads
def test_clip_limit_applies_to_clips_only(run, source, vault):
    source.serve(
        payload(clips=[source_entry("c1"), source_entry("c2")], episodes=[source_entry("e1")])
    )
    source.serve_assets("c1", "c2", "e1")
    run("sync", "vault", "--clips=1")
    assert media_stems(vault) == ["c1", "e1"]


# Spec: `--episodes=<n>` | non-negative integer (zero downloads nothing in that category)
def test_zero_limit_downloads_nothing_for_that_category(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")], clips=[source_entry("c1")]))
    source.serve_assets("e1", "c1")
    assert run("sync", "vault", "--episodes=0").returncode == 0
    assert media_stems(vault) == ["c1"]


# Spec: Omitted limit | No limit for that category
def test_omitted_limit_downloads_every_candidate(run, source, vault):
    ids = [f"e{n}" for n in range(1, 6)]
    sync_with(run, source, ids)
    assert media_stems(vault) == sorted(ids)


# Spec: Per-category limit | ... limits are independent per category
def test_limits_are_independent_per_category(run, source, vault):
    source.serve(
        payload(
            episodes=[source_entry("e1"), source_entry("e2")],
            streams=[source_entry("s1"), source_entry("s2")],
            clips=[source_entry("c1"), source_entry("c2")],
        )
    )
    source.serve_assets("e1", "e2", "s1", "s2", "c1", "c2")
    run("sync", "vault", "--episodes=1", "--streams=0", "--clips=2")
    assert media_stems(vault) == ["c1", "c2", "e1"]


# Spec: Partial artifacts | Stale partial-download artifacts must not block a later download
def test_stale_partial_artifact_does_not_block_download(run, source, vault):
    (vault / "media").mkdir()
    (vault / "media" / "e1.part").write_bytes(b"half a file")
    sync_with(run, source, ["e1"])
    assert (vault / "media" / "e1.mp4").read_bytes() == b"media-bytes"


# Spec: Partial artifacts | ... the artifact is not left behind after a success
def test_successful_download_leaves_no_partial_artifact(run, source, vault):
    sync_with(run, source, ["e1"])
    assert media_names(vault) == ["e1.mp4"]


# Spec: Successful HTTP download response | Any successful response is downloadable content
def test_any_successful_response_body_is_stored(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_media("e1", body=b"", content_type="application/octet-stream")
    source.serve_preview("e1")
    assert run("sync", "vault").returncode == 0
    assert (vault / "media" / "e1.bin").read_bytes() == b""
