"""Spec sections: `sync` Command / `sync` Options / Error Handling (CLI)."""
import os

import pytest
from conftest import (entry, media_names, payload, preview_names, read_catalog,
                      stored_ids)


def init(run, source, name="v"):
    result = run("init", name, source.url)
    assert result.returncode == 0, result.stderr
    return name


def seed(run, source, episodes=(), streams=(), clips=(), name="v"):
    """A vault whose catalog already holds the given source entries."""
    init(run, source, name)
    source.payload = payload(episodes, streams, clips)
    return name


# --------------------------------------------------------------------------
# `sync` Command
# --------------------------------------------------------------------------

# Phrase: "Syntax | `python mvault.py sync <name> [options]`"
# Context: options are accepted after the vault name.
def test_sync_accepts_options_after_name(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.assets("e1")
    result = run("sync", "v", "--episodes=1")
    assert result.returncode == 0, result.stderr


# Phrase: "Metadata phase | Load vault, optionally fetch source metadata,
#          update catalog history, persist metadata"
def test_metadata_phase_persists_catalog(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1", title="First")])
    assert run("sync", "v").returncode == 0
    catalog = read_catalog(tmp_path / "v")
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]


# Phrase: "Download phase | Retrieve media and preview files after metadata
#          phase"
# Context: the entry only exists after the metadata phase, so a download of it
# proves the ordering.
def test_download_phase_runs_after_metadata_phase(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.assets("e1")
    assert run("sync", "v").returncode == 0, "sync failed"
    assert stored_ids(media_names(tmp_path / "v")) == ["e1"]
    assert stored_ids(preview_names(tmp_path / "v")) == ["e1"]


# Phrase: "Download phase | Retrieve media and preview files"
# Context: the feed request precedes every asset request.
def test_feed_is_requested_before_assets(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.assets("e1")
    assert run("sync", "v").returncode == 0
    paths = [path for _, path in source.requests]
    assert paths[0] == source.feed_path
    assert source.media_path("e1") in paths


# Phrase: "Metadata-only run | `--skip-download`"
def test_skip_download_writes_metadata_but_no_files(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.assets("e1")
    result = run("sync", "v", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert [e["id"] for e in read_catalog(tmp_path / "v")["episodes"]] == ["e1"]
    assert media_names(tmp_path / "v") == []
    assert preview_names(tmp_path / "v") == []


# Phrase: "Metadata-only run | `--skip-download`"
# Context: no asset request is issued at all.
def test_skip_download_issues_no_asset_requests(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.assets("e1")
    assert run("sync", "v", "--skip-download").returncode == 0
    assert source.hits(source.media_path("e1")) == 0
    assert source.hits(source.preview_path("e1")) == 0


# Phrase: "Download-only run | `--skip-metadata`"
# Context: "Skip source fetch and metadata update; run download phase against
# existing vault state".
def test_skip_metadata_downloads_without_fetching_feed(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    assert run("sync", "v", "--skip-download").returncode == 0
    source.requests.clear()
    source.assets("e1")

    result = run("sync", "v", "--skip-metadata")

    assert result.returncode == 0, result.stderr
    assert source.requested(source.feed_path) == []
    assert stored_ids(media_names(tmp_path / "v")) == ["e1"]


# Phrase: "`--skip-metadata` | Skip source fetch and metadata update"
# Context: the catalog is left byte-for-byte alone, and no backup is made.
def test_skip_metadata_leaves_catalog_untouched(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    assert run("sync", "v", "--skip-download").returncode == 0
    vault = tmp_path / "v"
    before = (vault / "catalog.json").read_bytes()
    backup_before = (vault / "catalog.bak").exists()
    source.assets("e1")

    assert run("sync", "v", "--skip-metadata").returncode == 0

    assert (vault / "catalog.json").read_bytes() == before
    assert (vault / "catalog.bak").exists() == backup_before


# Phrase: "`--skip-metadata`" — a failing source feed is never contacted, so a
# download-only run succeeds even when the feed would abort a normal sync.
def test_skip_metadata_ignores_broken_feed(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    assert run("sync", "v", "--skip-download").returncode == 0
    source.assets("e1")
    source.status = 500

    result = run("sync", "v", "--skip-metadata")

    assert result.returncode == 0, result.stderr
    assert stored_ids(media_names(tmp_path / "v")) == ["e1"]


# Phrase: "Successful run with skipped downloads due to download failures |
#          Exit code `0`"
def test_download_failures_still_exit_zero(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    result = run("sync", "v")          # no asset routes registered -> 404
    assert result.returncode == 0, result.stderr
    assert result.stderr.strip(), "expected a warning on stderr"


# --------------------------------------------------------------------------
# `sync` Options
# --------------------------------------------------------------------------

# Phrase: "`--episodes=<n>` | non-negative integer | Maximum number of episode
#          media downloads"
def test_episodes_limit_caps_episode_downloads(run, source, tmp_path):
    seed(run, source, episodes=[entry("e%d" % i, published="2024-01-0%d" % i)
                                for i in (1, 2, 3)])
    source.assets("e1", "e2", "e3")
    assert run("sync", "v", "--episodes=2").returncode == 0
    assert len(media_names(tmp_path / "v")) == 2


# Phrase: "`--streams=<n>` | ... Maximum number of stream media downloads"
def test_streams_limit_caps_stream_downloads(run, source, tmp_path):
    seed(run, source, streams=[entry("s%d" % i, published="2024-01-0%d" % i)
                               for i in (1, 2, 3)])
    source.assets("s1", "s2", "s3")
    assert run("sync", "v", "--streams=1").returncode == 0
    assert len(media_names(tmp_path / "v")) == 1


# Phrase: "`--clips=<n>` | ... Maximum number of clip media downloads"
def test_clips_limit_caps_clip_downloads(run, source, tmp_path):
    seed(run, source, clips=[entry("c%d" % i, published="2024-01-0%d" % i)
                             for i in (1, 2, 3)])
    source.assets("c1", "c2", "c3")
    assert run("sync", "v", "--clips=0").returncode == 0
    assert media_names(tmp_path / "v") == []


# Phrase: "Per-category limit" — each limit applies only to its own category.
def test_limits_are_per_category(run, source, tmp_path):
    seed(run, source,
         episodes=[entry("e1"), entry("e2")],
         streams=[entry("s1"), entry("s2")],
         clips=[entry("c1"), entry("c2")])
    source.assets("e1", "e2", "s1", "s2", "c1", "c2")
    assert run("sync", "v", "--episodes=1", "--clips=2").returncode == 0
    names = media_names(tmp_path / "v")
    ids = set(stored_ids(names))
    assert len([i for i in ids if i.startswith("e")]) == 1
    assert len([i for i in ids if i.startswith("s")]) == 2   # omitted -> no limit
    assert len([i for i in ids if i.startswith("c")]) == 2


# Phrase: "Omitted limit | No limit for that category"
def test_omitted_limit_downloads_every_candidate(run, source, tmp_path):
    ids = ["e%d" % i for i in range(1, 6)]
    seed(run, source, episodes=[entry(i) for i in ids])
    source.assets(*ids)
    assert run("sync", "v").returncode == 0
    assert sorted(stored_ids(media_names(tmp_path / "v"))) == sorted(ids)


# Phrase: "`--episodes=<n>` | non-negative integer"
# Context: the value may also be supplied as a separate argument.
def test_limit_accepts_space_separated_value(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1"), entry("e2")])
    source.assets("e1", "e2")
    result = run("sync", "v", "--episodes", "1")
    assert result.returncode == 0, result.stderr
    assert len(media_names(tmp_path / "v")) == 1


# Phrase: "`--format=<str>` | string | Override media download format and
#          output extension"
def test_format_override_sets_extension(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.media("e1", fmt="mp3", content_type="video/mp4")
    source.preview("e1")
    assert run("sync", "v", "--format=mp3").returncode == 0
    assert media_names(tmp_path / "v") == ["e1.mp3"]


# --------------------------------------------------------------------------
# Error Handling
# --------------------------------------------------------------------------

# Phrase: "Malformed numeric category limit | stderr | non-zero | Abort before
#          any sync work"
@pytest.mark.parametrize("value", ["abc", "1.5", "", "-1", "1e3", " "])
def test_malformed_limit_aborts(run, source, tmp_path, value):
    seed(run, source, episodes=[entry("e1")])
    source.assets("e1")
    source.requests.clear()

    result = run("sync", "v", "--episodes=%s" % value)

    assert result.returncode != 0
    assert result.stderr.strip()
    assert source.requests == [], "sync work started before the limit was rejected"
    assert not os.path.isdir(str(tmp_path / "v" / "media"))


# Phrase: "Malformed numeric category limit" — every category limit validates.
@pytest.mark.parametrize("option", ["--streams", "--clips"])
def test_malformed_limit_aborts_for_every_category(run, source, tmp_path, option):
    seed(run, source, episodes=[entry("e1")])
    result = run("sync", "v", "%s=nope" % option)
    assert result.returncode != 0
    assert result.stderr.strip()


# Phrase: "Unrecognized CLI option | stderr | non-zero | Abort before any sync
#          work"
def test_unrecognized_option_aborts(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    source.requests.clear()

    result = run("sync", "v", "--bogus=1")

    assert result.returncode != 0
    assert result.stderr.strip()
    assert result.stdout == ""
    assert source.requests == []


# Phrase: "Abort before any sync work"
# Context: the catalog is not touched when the CLI is rejected.
def test_unrecognized_option_leaves_catalog_alone(run, source, tmp_path):
    seed(run, source, episodes=[entry("e1")])
    assert run("sync", "v", "--skip-download").returncode == 0
    before = (tmp_path / "v" / "catalog.json").read_bytes()
    source.payload = payload(episodes=[entry("e1", title="changed")])

    assert run("sync", "v", "--nope").returncode != 0

    assert (tmp_path / "v" / "catalog.json").read_bytes() == before
