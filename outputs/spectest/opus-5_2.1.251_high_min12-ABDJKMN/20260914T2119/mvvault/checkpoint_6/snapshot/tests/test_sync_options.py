"""Spec: `sync` Command (phases) and `sync` Options tables."""
import os

from conftest import (make_entry, read_catalog, media_files, preview_files,
                      catalog_bytes)


# Spec: "| Syntax | `python mvault.py sync <name> [options]` |"
# Context: the bare form keeps working now that options exist.
def test_sync_syntax_accepts_no_options(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    assert run("sync", "vault").returncode == 0


# Spec: "| Metadata phase | Load vault, optionally fetch source metadata,
# update catalog history, persist metadata |"
def test_metadata_phase_persists_history(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="T")])
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert list(catalog["episodes"][0]["title"].values()) == ["T"]


# Spec: "| Download phase | Retrieve media and preview files after metadata
# phase |" -- the metadata request precedes every asset request.
def test_download_phase_runs_after_metadata_phase(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    assert run("sync", "vault").returncode == 0
    paths = [path for _, path in source.requests]
    assert paths[0].endswith("/source.json")
    assert any("/media/" in p for p in paths[1:])


# Spec: "| Metadata-only run | `--skip-download` |"
def test_skip_download_downloads_nothing(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    res = run("sync", "vault", "--skip-download")
    assert res.returncode == 0, res
    assert media_files(tmp_path) == []
    assert preview_files(tmp_path) == []
    assert source.hits("media", "e1") == 0


# Spec: "| Metadata-only run | `--skip-download` |" +
# "`--skip-download` | flag | Skip download phase; fetch and persist metadata
# only |" -- metadata is still fetched and persisted.
def test_skip_download_still_persists_metadata(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    assert run("sync", "vault", "--skip-download").returncode == 0
    assert [e["id"] for e in read_catalog(tmp_path)["episodes"]] == ["e1"]


# Spec: "| Download-only run | `--skip-metadata` |" +
# "`--skip-metadata` | flag | Skip source fetch and metadata update; run
# download phase against existing vault state |"
def test_skip_metadata_does_not_fetch_source(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault", "--skip-download")
    before = len(source.requests)
    source.serve_entry_assets("e1")
    res = run("sync", "vault", "--skip-metadata")
    assert res.returncode == 0, res
    metadata_requests = [p for _, p in source.requests[before:]
                         if "/media/" not in p and "/preview/" not in p]
    assert metadata_requests == []


# Spec: "`--skip-metadata` ... run download phase against existing vault state"
def test_skip_metadata_downloads_existing_entries(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault", "--skip-download")
    source.serve_entry_assets("e1")
    assert run("sync", "vault", "--skip-metadata").returncode == 0
    assert media_files(tmp_path) == ["e1.mp4"]


# Spec: "`--skip-metadata` | Skip source fetch and metadata update" -- the
# catalog is left byte-for-byte alone by a download-only run.
def test_skip_metadata_leaves_catalog_untouched(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault", "--skip-download")
    before = catalog_bytes(tmp_path)
    source.serve_entry_assets("e1")
    assert run("sync", "vault", "--skip-metadata").returncode == 0
    assert catalog_bytes(tmp_path) == before


# Spec: both flags together -- neither phase runs, and the run still succeeds.
def test_skip_metadata_and_skip_download_together(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    res = run("sync", "vault", "--skip-metadata", "--skip-download")
    assert res.returncode == 0, res
    assert media_files(tmp_path) == []
    assert read_catalog(tmp_path)["episodes"] == []


# Spec: "| `--episodes=<n>` | non-negative integer | Maximum number of episode
# media downloads |"
def test_episodes_limit_caps_episode_downloads(run, source, tmp_path, vault):
    ids = ["e1", "e2", "e3"]
    source.serve(episodes=[make_entry(id=i, published="2024-05-0%dT00:00:00" % n)
                           for n, i in enumerate(ids, start=1)])
    for i in ids:
        source.serve_entry_assets(i)
    assert run("sync", "vault", "--episodes=2").returncode == 0
    assert len(media_files(tmp_path)) == 2


# Spec: "| `--streams=<n>` | non-negative integer | Maximum number of stream
# media downloads |"
def test_streams_limit_caps_stream_downloads(run, source, tmp_path, vault):
    source.serve(streams=[make_entry(id="s%d" % n) for n in range(1, 4)])
    for n in range(1, 4):
        source.serve_entry_assets("s%d" % n)
    assert run("sync", "vault", "--streams=1").returncode == 0
    assert len(media_files(tmp_path)) == 1


# Spec: "| `--clips=<n>` | non-negative integer | Maximum number of clip media
# downloads |"
def test_clips_limit_caps_clip_downloads(run, source, tmp_path, vault):
    source.serve(clips=[make_entry(id="c%d" % n) for n in range(1, 4)])
    for n in range(1, 4):
        source.serve_entry_assets("c%d" % n)
    assert run("sync", "vault", "--clips=2").returncode == 0
    assert len(media_files(tmp_path)) == 2


# Spec: per-category limits are independent of each other.
def test_category_limits_are_independent(run, source, tmp_path, vault):
    source.serve(
        episodes=[make_entry(id="e%d" % n) for n in range(1, 3)],
        streams=[make_entry(id="s%d" % n) for n in range(1, 3)],
        clips=[make_entry(id="c%d" % n) for n in range(1, 3)],
    )
    for i in ("e1", "e2", "s1", "s2", "c1", "c2"):
        source.serve_entry_assets(i)
    assert run("sync", "vault", "--episodes=1", "--clips=0").returncode == 0
    names = media_files(tmp_path)
    assert len([n for n in names if n.startswith("e")]) == 1
    assert len([n for n in names if n.startswith("s")]) == 2
    assert len([n for n in names if n.startswith("c")]) == 0


# Spec: "non-negative integer" -- zero is a legal limit meaning "download none".
def test_zero_limit_downloads_nothing_for_that_category(run, source, tmp_path,
                                                        vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_entry_assets("e1")
    assert run("sync", "vault", "--episodes=0").returncode == 0
    assert media_files(tmp_path) == []
    assert source.hits("media", "e1") == 0


# Spec: "| Omitted limit | No limit for that category |"
def test_omitted_limit_means_no_limit(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e%d" % n) for n in range(1, 6)])
    for n in range(1, 6):
        source.serve_entry_assets("e%d" % n)
    assert run("sync", "vault").returncode == 0
    assert len(media_files(tmp_path)) == 5


# Spec: "| `--format=<str>` | string | Override media download format and output
# extension |" -- output extension.
def test_format_override_sets_output_extension(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", ext="webm", content_type="video/mp4")
    source.serve_preview("e1")
    assert run("sync", "vault", "--format=webm").returncode == 0
    assert media_files(tmp_path) == ["e1.webm"]


# Spec: "| Media with format override | `<source>/media/<entry_id>.<format>` |"
def test_format_override_changes_remote_path(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", ext="webm")
    run("sync", "vault", "--format=webm")
    assert source.hits("media", "e1", ext="webm") == 1
    assert source.hits("media", "e1") == 0


# Spec: "Override media download format" -- previews are unaffected by
# `--format`; only the media request carries the extension.
def test_format_override_does_not_change_preview_path(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1", ext="webm")
    source.serve_preview("e1")
    run("sync", "vault", "--format=webm")
    assert source.hits("preview", "e1") == 1


# Spec: options combine with each other.
def test_format_and_limit_combine(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e%d" % n) for n in range(1, 4)])
    for n in range(1, 4):
        source.serve_media("e%d" % n, ext="mp3")
        source.serve_preview("e%d" % n)
    assert run("sync", "vault", "--format=mp3", "--episodes=2").returncode == 0
    assert media_files(tmp_path) == ["e1.mp3", "e2.mp3"]


# Spec: "| Successful run with skipped downloads due to download failures |
# Exit code `0` |"
def test_download_failures_still_exit_zero(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.fail_asset("media", "e1", status=404)
    source.fail_asset("preview", "e1", status=404)
    res = run("sync", "vault")
    assert res.returncode == 0, res
    assert res.stderr != ""
