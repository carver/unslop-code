"""Spec sections: `sync` Command, `sync` Options, `sync` Post-Summary, Error Handling."""

import json

from conftest import catalog_bytes, media_names, payload, run_cli, source_entry


def synced_vault(vault, tmp_path, source, **categories):
    """A vault whose catalog already holds `categories`, with nothing downloaded."""
    source.serve(payload(**categories))
    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return vault


# `sync` Command: "Syntax | `python mvault.py sync <name> [options]`" — the
# name stays positional once options are accepted.
def test_sync_accepts_a_name_and_options(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)
    assert result.returncode == 0, result.stderr


# `sync` Command: "Metadata phase | Load vault, optionally fetch source
# metadata, update catalog history, persist metadata".
def test_metadata_phase_persists_fetched_history(vault, tmp_path, source):
    synced_vault(vault, tmp_path, source, episodes=[source_entry("e1")])
    catalog = json.loads((vault / "catalog.json").read_text())
    assert list(catalog["episodes"][0]["title"].values()) == ["title-e1"]


# `sync` Command: "Download phase | Retrieve media and preview files after
# metadata phase" — one plain run both records and downloads the new entry.
def test_download_phase_follows_the_metadata_phase(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_entry("e1")

    result = run_cli("sync", "demo", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert media_names(vault) == ["e1.mp4"]
    assert (vault / "previews" / "e1.jpg").exists()


# `sync` Command: "Metadata-only run | `--skip-download`".
def test_skip_download_writes_no_media(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_entry("e1")

    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (vault / "media").exists()
    assert source.asset_requests() == []


# `sync` Command: "Download-only run | `--skip-metadata`" — "Skip source fetch
# and metadata update; run download phase against existing vault state".
def test_skip_metadata_downloads_without_fetching(vault, tmp_path, source):
    synced_vault(vault, tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1")
    before = catalog_bytes(vault)
    source.requests.clear()

    result = run_cli("sync", "demo", "--skip-metadata", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert media_names(vault) == ["e1.mp4"]
    assert catalog_bytes(vault) == before
    assert [path for path in source.requests if "source.json" == path.strip("/")] == []


# `sync` Command: "Successful run with skipped downloads due to download
# failures | Exit code `0`".
def test_download_failures_still_exit_zero(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))

    result = run_cli("sync", "demo", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stderr != ""


# `sync` Options: "`--episodes=<n>` | non-negative integer | Maximum number of
# episode media downloads".
def test_episode_limit_caps_episode_downloads(vault, tmp_path, source):
    entries = [source_entry(f"e{n}", published=f"2024-01-0{n}T00:00:00") for n in (1, 2, 3)]
    synced_vault(vault, tmp_path, source, episodes=entries)
    for entry in entries:
        source.serve_entry(entry["id"])

    run_cli("sync", "demo", "--skip-metadata", "--episodes=2", cwd=tmp_path)
    assert len(media_names(vault)) == 2


# `sync` Options: "`--streams=<n>` | non-negative integer | Maximum number of
# stream media downloads" — a limit binds only its own category.
def test_stream_limit_binds_only_streams(vault, tmp_path, source):
    synced_vault(
        vault,
        tmp_path,
        source,
        streams=[source_entry("s1"), source_entry("s2")],
        clips=[source_entry("c1")],
    )
    for entry_id in ("s1", "s2", "c1"):
        source.serve_entry(entry_id)

    run_cli("sync", "demo", "--skip-metadata", "--streams=1", cwd=tmp_path)
    assert media_names(vault) == ["c1.mp4", "s1.mp4"]


# `sync` Options: "`--clips=<n>` | non-negative integer | Maximum number of clip
# media downloads" — zero is a valid non-negative limit.
def test_clip_limit_of_zero_downloads_nothing(vault, tmp_path, source):
    synced_vault(vault, tmp_path, source, clips=[source_entry("c1")])
    source.serve_entry("c1")

    run_cli("sync", "demo", "--skip-metadata", "--clips=0", cwd=tmp_path)
    assert source.asset_requests() == []


# `sync` Options: "`--format=<str>` | string | Override media download format
# and output extension".
def test_format_override_sets_the_media_extension(vault, tmp_path, source):
    synced_vault(vault, tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1", fmt="webm", content_type="video/mp4")

    result = run_cli("sync", "demo", "--skip-metadata", "--format=webm", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert media_names(vault) == ["e1.webm"]


# `sync` Post-Summary: "Trigger | Successful `sync` run that includes metadata
# phase"; "Output stream | stdout"; "Counts reported | Added, removed, updated".
def test_post_summary_reports_added_removed_and_updated(vault, tmp_path, source):
    entries = [source_entry("e1"), source_entry("e2"), source_entry("e3")]
    synced_vault(vault, tmp_path, source, episodes=entries)
    source.serve(
        payload(
            episodes=[
                source_entry("e1", title="changed"),
                source_entry("e3"),
                source_entry("e4"),
            ]
        )
    )

    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    summary = result.stdout.lower()
    assert "1 added" in summary
    assert "1 removed" in summary
    assert "1 updated" in summary


# `sync` Post-Summary: "Trigger | Successful `sync` run that includes metadata
# phase" — a download-only run reports nothing.
def test_skip_metadata_prints_no_summary(vault, tmp_path, source):
    synced_vault(vault, tmp_path, source, episodes=[source_entry("e1")])
    source.serve_entry("e1")

    result = run_cli("sync", "demo", "--skip-metadata", cwd=tmp_path)
    assert result.stdout == ""


# Error Handling: "Malformed numeric category limit | stderr | non-zero | Abort
# before any sync work".
def test_malformed_limit_aborts_before_any_work(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    before = catalog_bytes(vault)

    result = run_cli("sync", "demo", "--episodes=many", cwd=tmp_path)
    assert result.returncode != 0
    assert result.stderr != ""
    assert catalog_bytes(vault) == before
    assert source.requests == []


# Error Handling: "Malformed numeric category limit" — a negative count is not
# a non-negative integer.
def test_negative_limit_is_rejected(vault, tmp_path, source):
    result = run_cli("sync", "demo", "--clips=-1", cwd=tmp_path)
    assert result.returncode != 0
    assert source.requests == []


# Error Handling: "Unrecognized CLI option | stderr | non-zero | Abort before
# any sync work".
def test_unrecognized_option_aborts_before_any_work(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    before = catalog_bytes(vault)

    result = run_cli("sync", "demo", "--nonsense", cwd=tmp_path)
    assert result.returncode != 0
    assert result.stderr != ""
    assert catalog_bytes(vault) == before
    assert source.requests == []
