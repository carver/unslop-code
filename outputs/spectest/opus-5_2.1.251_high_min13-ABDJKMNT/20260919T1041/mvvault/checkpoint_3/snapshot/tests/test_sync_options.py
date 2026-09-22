"""`sync` Command phases and `sync` Options tables."""

import pytest

from conftest import read_catalog, source_entry, stored_names


@pytest.fixture
def sync(run_cli, vault, source):
    """Run `sync` on the vault 'v' against a payload of episodes."""

    def run(*options, episodes=(), streams=(), clips=()):
        source.payload = {
            "episodes": list(episodes),
            "streams": list(streams),
            "clips": list(clips),
        }
        return run_cli("sync", "v", *options)

    return run


# Spec: Syntax | `python mvault.py sync <name> [options]`
def test_sync_accepts_options_after_the_vault_name(sync):
    result = sync("--skip-download", episodes=[source_entry("a")])
    assert result.returncode == 0, result.stderr


# Spec: Metadata phase | Load vault, optionally fetch source metadata, update
# catalog history, persist metadata
def test_metadata_phase_persists_the_observation(sync, vault):
    sync("--skip-download", episodes=[source_entry("a")])
    assert [entry["id"] for entry in read_catalog(vault)["episodes"]] == ["a"]


# Spec: Download phase | Retrieve media and preview files after metadata phase
def test_download_phase_runs_after_the_metadata_phase(sync, vault):
    sync(episodes=[source_entry("a")])
    assert stored_names(vault / "media") == ["a.mp4"]
    assert stored_names(vault / "previews") == ["a.mp4"]


# Spec: Metadata-only run | `--skip-download`
def test_skip_download_writes_no_media(sync, vault):
    result = sync("--skip-download", episodes=[source_entry("a")])
    assert result.returncode == 0, result.stderr
    assert stored_names(vault / "media") == []
    assert stored_names(vault / "previews") == []


# Spec: `--skip-download` | flag | Skip download phase; fetch and persist metadata only
def test_skip_download_still_fetches_and_persists(sync, vault, source):
    sync("--skip-download", episodes=[source_entry("a", views=77)])
    assert source.requests == 1
    entry = read_catalog(vault)["episodes"][0]
    assert entry["views"][max(entry["views"])] == 77


# Spec: Download-only run | `--skip-metadata`
def test_skip_metadata_downloads_from_existing_state(sync, vault, source):
    sync("--skip-download", episodes=[source_entry("a")])
    requests_after_metadata = source.requests
    result = sync("--skip-metadata", episodes=[])
    assert result.returncode == 0, result.stderr
    assert source.requests == requests_after_metadata
    assert stored_names(vault / "media") == ["a.mp4"]


# Spec: `--skip-metadata` | flag | Skip source fetch and metadata update
def test_skip_metadata_leaves_the_catalog_untouched(sync, vault):
    sync("--skip-download", episodes=[source_entry("a")])
    before = (vault / "catalog.json").read_text()
    sync("--skip-metadata", episodes=[source_entry("a", views=999)])
    assert (vault / "catalog.json").read_text() == before


# Spec: `--episodes=<n>` | non-negative integer | Maximum number of episode media downloads
def test_episodes_limit_caps_episode_downloads(sync, vault):
    sync("--episodes=2", episodes=[source_entry(name) for name in "abcd"])
    assert len(stored_names(vault / "media")) == 2


# Spec: `--streams=<n>` | non-negative integer | Maximum number of stream media downloads
def test_streams_limit_caps_stream_downloads(sync, vault):
    sync("--streams=1", "--episodes=0", "--clips=0", streams=[source_entry(name) for name in "xy"])
    assert len(stored_names(vault / "media")) == 1


# Spec: `--clips=<n>` | non-negative integer | Maximum number of clip media downloads
def test_clips_limit_caps_clip_downloads(sync, vault):
    sync("--clips=1", "--episodes=0", "--streams=0", clips=[source_entry(name) for name in "xy"])
    assert len(stored_names(vault / "media")) == 1


# Spec: `--episodes=<n>` ... non-negative integer (zero downloads nothing)
def test_zero_limit_downloads_nothing_for_that_category(sync, vault):
    sync("--episodes=0", episodes=[source_entry("a")])
    assert stored_names(vault / "media") == []


# Spec: Per-category limit | Download first `N` candidates ... (limits are per category)
def test_limits_apply_per_category(sync, vault):
    sync(
        "--episodes=1",
        "--clips=0",
        episodes=[source_entry("e1"), source_entry("e2")],
        streams=[source_entry("s1")],
        clips=[source_entry("c1")],
    )
    assert stored_names(vault / "media") == ["e1.mp4", "s1.mp4"]


# Spec: Omitted limit | No limit for that category
def test_omitted_limit_downloads_every_candidate(sync, vault):
    sync(episodes=[source_entry(name) for name in "abcde"])
    assert len(stored_names(vault / "media")) == 5


# Spec: `--format=<str>` | string | Override media download format and output extension
def test_format_overrides_the_media_extension(sync, vault):
    sync("--format=mkv", episodes=[source_entry("a")])
    assert stored_names(vault / "media") == ["a.mkv"]


# Spec: `--format=<str>` | ... Override media download format (the remote path gains it)
def test_format_is_appended_to_the_remote_media_path(sync, source):
    sync("--format=mkv", episodes=[source_entry("a")])
    assert "/feed.json/media/a.mkv" in source.asset_requests


# Spec: Malformed numeric category limit | stderr | non-zero | Abort before any sync work
@pytest.mark.parametrize("option", ["--episodes=abc", "--streams=1.5", "--clips=-1", "--episodes="])
def test_malformed_limit_is_rejected(sync, option):
    result = sync(option, episodes=[source_entry("a")])
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Malformed numeric category limit | ... Abort before any sync work
def test_malformed_limit_performs_no_sync_work(sync, vault, source):
    sync("--episodes=abc", episodes=[source_entry("a")])
    assert source.requests == 0
    assert read_catalog(vault)["episodes"] == []


# Spec: Unrecognized CLI option | stderr | non-zero | Abort before any sync work
def test_unrecognized_option_is_rejected(sync):
    result = sync("--nonsense", episodes=[source_entry("a")])
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Unrecognized CLI option | ... Abort before any sync work
def test_unrecognized_option_performs_no_sync_work(sync, vault, source):
    sync("--nonsense", episodes=[source_entry("a")])
    assert source.requests == 0
    assert read_catalog(vault)["episodes"] == []


# Spec: Successful run with skipped downloads due to download failures | Exit code `0`
def test_download_failures_still_exit_zero(sync, source):
    source.asset = (404, "text/plain", b"gone")
    result = sync(episodes=[source_entry("a")])
    assert result.returncode == 0
    assert result.stderr.strip()


# Spec: `--format=<str>` | string | Override media download format and output extension
# (AMBIGUITIES T27: the template writes the dot, so a leading dot in the value is not
# part of the format name)
def test_format_value_tolerates_a_leading_dot(sync, vault, source):
    sync("--format=.mkv", episodes=[source_entry("a")])
    assert stored_names(vault / "media") == ["a.mkv"]
    assert "/feed.json/media/a.mkv" in source.asset_requests
