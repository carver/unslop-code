"""Spec sections: `sync` Command, `sync` Options, `catalog.json` Persistence
During `sync`, `sync` Post-Summary, and the option rows of Error Handling."""

from __future__ import annotations



def payload_with(helpers, episodes=(), streams=(), clips=()):
    return helpers.make_payload(
        episodes=[helpers.make_source_entry(i) for i in episodes],
        streams=[helpers.make_source_entry(i) for i in streams],
        clips=[helpers.make_source_entry(i) for i in clips],
    )


# ---------------------------------------------------------------------------
# | Syntax | `python mvault.py sync <name> [options]` |
# ---------------------------------------------------------------------------

# Spec: | Syntax | `python mvault.py sync <name> [options]` |
# Context: options follow the vault name and are accepted by the `sync` command.
def test_sync_accepts_options_after_name(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    result = run_cli("sync", "vault", "--episodes=1", "--format=mp4")
    assert result.returncode == 0, result.stderr


# Spec: | Syntax | `python mvault.py sync <name> [options]` |
# Context: all six documented options are recognized together.
def test_sync_accepts_every_documented_option(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli(
        "sync", "vault",
        "--episodes=0", "--streams=0", "--clips=0",
        "--skip-download", "--format=mp4",
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# | Metadata phase | Load vault, optionally fetch source metadata, update
#   catalog history, persist metadata |
# | Download phase | Retrieve media and preview files after metadata phase |
# ---------------------------------------------------------------------------

# Spec: | Metadata phase | Load vault, ... update catalog history, persist metadata |
def test_metadata_phase_updates_and_persists_history(
    run_cli, vault, source, helpers, workdir
):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry is not None
    assert len(entry["title"]) == 1


# Spec: | Download phase | Retrieve media and preview files after metadata phase |
# Context: an entry first seen in this run is already a download candidate,
# which is only possible when downloads run after the metadata update.
def test_download_phase_runs_after_metadata_phase(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]


# Spec: | Download phase | Retrieve media and preview files after metadata phase |
# Context: both asset kinds are retrieved.
def test_download_phase_retrieves_media_and_preview(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault))
    assert helpers.listing(helpers.preview_dir(vault))


# ---------------------------------------------------------------------------
# | Metadata-only run | `--skip-download` |
# | `--skip-download` | flag | Skip download phase; fetch and persist metadata only |
# ---------------------------------------------------------------------------

# Spec: | Metadata-only run | `--skip-download` |
def test_skip_download_performs_no_downloads(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == []
    assert helpers.listing(helpers.preview_dir(vault)) == []


# Spec: | `--skip-download` | ... | fetch and persist metadata only |
def test_skip_download_still_fetches_and_persists_metadata(
    run_cli, vault, source, helpers, workdir
):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    assert source.hits("/source.json") == 1
    assert helpers.find_entry(helpers.read_catalog(workdir), "e1") is not None


# Spec: | `--skip-download` | ... | Skip download phase ... |
# Context: no media asset is requested at all.
def test_skip_download_makes_no_asset_requests(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    assert source.hits(helpers.media_path("e1")) == 0
    assert source.hits(helpers.preview_path("e1")) == 0


# ---------------------------------------------------------------------------
# | Download-only run | `--skip-metadata` |
# | `--skip-metadata` | flag | Skip source fetch and metadata update; run
#   download phase against existing vault state |
# ---------------------------------------------------------------------------

# Spec: | `--skip-metadata` | ... | Skip source fetch ... |
def test_skip_metadata_makes_no_source_fetch(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    before = source.hits("/source.json")
    source.serve_entry("e1")
    assert run_cli("sync", "vault", "--skip-metadata").returncode == 0
    assert source.hits("/source.json") == before


# Spec: | `--skip-metadata` | ... | run download phase against existing vault state |
def test_skip_metadata_downloads_from_existing_vault_state(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    source.serve_entry("e1")
    assert run_cli("sync", "vault", "--skip-metadata").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]


# Spec: | `--skip-metadata` | ... | Skip ... metadata update ... |
# Context: the catalog history gains nothing from a download-only run.
def test_skip_metadata_leaves_history_untouched(
    run_cli, vault, source, helpers, workdir
):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    before = helpers.read_catalog(workdir)
    source.set(payload_with(helpers, episodes=[]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault", "--skip-metadata").returncode == 0
    assert helpers.read_catalog(workdir) == before


# Spec: | Trigger | Successful `sync` run that includes metadata phase |
# Context: a download-only run has no metadata phase, so no change summary.
def test_skip_metadata_reports_no_change_counts(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    source.serve_entry("e1")
    result = run_cli("sync", "vault", "--skip-metadata")
    assert result.returncode == 0, result.stderr
    assert "added" not in result.stdout.lower()


# ---------------------------------------------------------------------------
# | `--episodes=<n>` | non-negative integer | Maximum number of episode media
#   downloads | (and `--streams`, `--clips`)
# ---------------------------------------------------------------------------

# Spec: | `--episodes=<n>` | ... | Maximum number of episode media downloads |
def test_episodes_limit_caps_episode_media_downloads(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1", "e2", "e3"]))
    for entry_id in ("e1", "e2", "e3"):
        source.serve_entry(entry_id)
    assert run_cli("sync", "vault", "--episodes=2").returncode == 0
    assert len(helpers.listing(helpers.media_dir(vault))) == 2


# Spec: | `--streams=<n>` | ... | Maximum number of stream media downloads |
def test_streams_limit_caps_stream_media_downloads(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, streams=["s1", "s2", "s3"]))
    for entry_id in ("s1", "s2", "s3"):
        source.serve_entry(entry_id)
    assert run_cli("sync", "vault", "--streams=1").returncode == 0
    assert len(helpers.listing(helpers.media_dir(vault))) == 1


# Spec: | `--clips=<n>` | ... | Maximum number of clip media downloads |
def test_clips_limit_caps_clip_media_downloads(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, clips=["c1", "c2", "c3"]))
    for entry_id in ("c1", "c2", "c3"):
        source.serve_entry(entry_id)
    assert run_cli("sync", "vault", "--clips=2").returncode == 0
    assert len(helpers.listing(helpers.media_dir(vault))) == 2


# Spec: | `--episodes=<n>` | ... | (limits are per category)
# Context: a limit on one category does not restrict the others.
def test_limits_are_independent_per_category(run_cli, vault, source, helpers):
    source.set(payload_with(
        helpers, episodes=["e1", "e2"], streams=["s1", "s2"], clips=["c1", "c2"]))
    for entry_id in ("e1", "e2", "s1", "s2", "c1", "c2"):
        source.serve_entry(entry_id)
    assert run_cli("sync", "vault", "--episodes=1").returncode == 0
    names = helpers.listing(helpers.media_dir(vault))
    assert len([n for n in names if n.startswith("e")]) == 1
    assert len([n for n in names if n.startswith("s")]) == 2
    assert len([n for n in names if n.startswith("c")]) == 2


# Spec: | Omitted limit | No limit for that category |
def test_omitted_limit_downloads_every_candidate(run_cli, vault, source, helpers):
    ids = [f"e{n}" for n in range(1, 6)]
    source.set(payload_with(helpers, episodes=ids))
    for entry_id in ids:
        source.serve_entry(entry_id)
    assert run_cli("sync", "vault").returncode == 0
    assert len(helpers.listing(helpers.media_dir(vault))) == len(ids)


# Spec: | `--episodes=<n>` | non-negative integer | ... |
# Context: zero is a valid non-negative integer and caps downloads at none.
def test_zero_limit_downloads_nothing_for_that_category(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1", "e2"]))
    source.serve_entry("e1")
    source.serve_entry("e2")
    result = run_cli("sync", "vault", "--episodes=0")
    assert result.returncode == 0, result.stderr
    assert helpers.listing(helpers.media_dir(vault)) == []


# Spec: | `--episodes=<n>` | ... |
# Context: the space-separated spelling is the same option.
def test_limit_accepts_space_separated_value(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1", "e2"]))
    source.serve_entry("e1")
    source.serve_entry("e2")
    result = run_cli("sync", "vault", "--episodes", "1")
    assert result.returncode == 0, result.stderr
    assert len(helpers.listing(helpers.media_dir(vault))) == 1


# ---------------------------------------------------------------------------
# | `--format=<str>` | string | Override media download format and output
#   extension |
# ---------------------------------------------------------------------------

# Spec: | `--format=<str>` | ... | Override media download ... extension |
def test_format_override_sets_output_extension(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", fmt="ogg", content_type="video/mp4")
    source.set_preview("e1")
    assert run_cli("sync", "vault", "--format=ogg").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.ogg"]


# Spec: | Media with format override | `<source>/media/<entry_id>.<format>` |
def test_format_override_requests_suffixed_remote_path(
    run_cli, vault, source, helpers
):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", fmt="ogg")
    source.set_preview("e1")
    assert run_cli("sync", "vault", "--format=ogg").returncode == 0
    assert source.hits(helpers.media_path("e1", "ogg")) >= 1
    assert source.hits(helpers.media_path("e1")) == 0


# Spec: | `--format=<str>` | ... | Override media download format ... |
# Context: the override beats the `Content-Type` derivation.
def test_format_override_beats_content_type(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.set_media("e1", fmt="wav", content_type="video/mp4")
    source.set_preview("e1")
    assert run_cli("sync", "vault", "--format=wav").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.wav"]


# ---------------------------------------------------------------------------
# | Save timing | Metadata phase persists before successful `sync` returns |
# | Download failure interaction | Metadata save still occurs even when one or
#   more downloads fail |
# ---------------------------------------------------------------------------

# Spec: | Save timing | Metadata phase persists before successful `sync` returns |
def test_metadata_persists_before_sync_returns(
    run_cli, vault, source, helpers, workdir
):
    source.set(payload_with(helpers, episodes=["e1"], streams=["s1"]))
    source.serve_entry("e1")
    source.serve_entry("s1")
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]


# Spec: | Download failure interaction | Metadata save still occurs even when
#   one or more downloads fail |
def test_metadata_saved_when_downloads_fail(
    run_cli, vault, source, helpers, workdir
):
    source.set(payload_with(helpers, episodes=["e1"]))
    # no asset registered: every download for `e1` fails
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert helpers.find_entry(helpers.read_catalog(workdir), "e1") is not None


# Spec: | Persistence boundary | Metadata changes must be durably saved before
#   successful sync returns, including runs with download failures |
def test_metadata_durably_saved_with_mixed_download_outcomes(
    run_cli, vault, source, helpers, workdir
):
    source.set(payload_with(helpers, episodes=["e1", "e2"]))
    source.serve_entry("e1")  # e2 has no asset and fails
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["e1", "e2"]


# Spec: | Successful run with skipped downloads due to download failures |
#   Exit code `0` |
def test_download_failures_still_exit_zero(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1", "e2"]))
    result = run_cli("sync", "vault")
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# | Malformed numeric category limit | stderr | non-zero | Abort before any
#   sync work |
# ---------------------------------------------------------------------------

# Spec: | Malformed numeric category limit | stderr | non-zero | ... |
def test_non_numeric_limit_exits_non_zero_with_stderr(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--episodes=abc")
    assert result.returncode != 0
    assert result.stderr.strip() != ""


# Spec: | Malformed numeric category limit | ... | Abort before any sync work |
def test_non_numeric_limit_aborts_before_any_sync_work(
    run_cli, vault, source, helpers, workdir
):
    source.set(payload_with(helpers, episodes=["e1"]))
    before = helpers.read_catalog(workdir)
    result = run_cli("sync", "vault", "--episodes=abc")
    assert result.returncode != 0
    assert source.hits("/source.json") == 0
    assert helpers.read_catalog(workdir) == before


# Spec: | `--episodes=<n>` | non-negative integer | ... |
# Context: a negative value is not a non-negative integer, so it is malformed.
def test_negative_limit_is_malformed(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--episodes=-1")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert source.hits("/source.json") == 0


# Spec: | Malformed numeric category limit | ... |
# Context: a fractional value is not an integer.
def test_fractional_limit_is_malformed(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--clips=1.5")
    assert result.returncode != 0
    assert source.hits("/source.json") == 0


# Spec: | Malformed numeric category limit | ... |
# Context: every category limit is validated the same way.
def test_each_category_limit_validates_its_value(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    for option in ("--episodes=x", "--streams=x", "--clips=x"):
        result = run_cli("sync", "vault", option)
        assert result.returncode != 0, option
        assert result.stderr.strip() != "", option


# ---------------------------------------------------------------------------
# | Unrecognized CLI option | stderr | non-zero | Abort before any sync work |
# ---------------------------------------------------------------------------

# Spec: | Unrecognized CLI option | stderr | non-zero | ... |
def test_unrecognized_option_exits_non_zero_with_stderr(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--nope")
    assert result.returncode != 0
    assert result.stderr.strip() != ""


# Spec: | Unrecognized CLI option | ... | Abort before any sync work |
def test_unrecognized_option_aborts_before_any_sync_work(
    run_cli, vault, source, helpers, workdir
):
    source.set(payload_with(helpers, episodes=["e1"]))
    before = helpers.read_catalog(workdir)
    result = run_cli("sync", "vault", "--nope=1")
    assert result.returncode != 0
    assert source.hits("/source.json") == 0
    assert helpers.read_catalog(workdir) == before


# ---------------------------------------------------------------------------
# | Source metadata fetch failure during `sync` | stderr | non-zero | Abort run |
# ---------------------------------------------------------------------------

# Spec: | Source metadata fetch failure during `sync` | stderr | non-zero | Abort run |
# Context: the download phase must not run when the metadata phase aborts.
def test_fetch_failure_aborts_before_download_phase(
    run_cli, vault, source, helpers, workdir
):
    source.set_raw("not json", status=200)
    source.set_media("e1")
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert helpers.listing(helpers.media_dir(vault)) == []


# ---------------------------------------------------------------------------
# `sync` Post-Summary
# ---------------------------------------------------------------------------

# Spec: | Trigger | Successful `sync` run that includes metadata phase |
#       | Output stream | stdout |
def test_post_summary_written_to_stdout(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""


# Spec: | Counts reported | Added, removed, updated |
def test_post_summary_reports_three_counts(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--skip-download")
    text = result.stdout.lower()
    for word in ("added", "removed", "updated"):
        assert word in text, text


# Spec: | Counts reported | Added, ... |
# Context: two first-seen entries are two additions.
def test_post_summary_counts_additions(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"], streams=["s1"]))
    result = run_cli("sync", "vault", "--skip-download")
    assert "2" in result.stdout


# Spec: | Counts reported | ..., removed, ... |
def test_post_summary_counts_removals(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1", "e2"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--skip-download")
    assert result.returncode == 0, result.stderr
    lowered = result.stdout.lower()
    assert "1 removed" in lowered or "removed: 1" in lowered, result.stdout


# Spec: | Counts reported | ..., updated |
def test_post_summary_counts_updates(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    changed = helpers.make_source_entry("e1", title="New title")
    source.set(helpers.make_payload(episodes=[changed]))
    result = run_cli("sync", "vault", "--skip-download")
    lowered = result.stdout.lower()
    assert "1 updated" in lowered or "updated: 1" in lowered, result.stdout


# Spec: | Post-sync counts | Deterministic for the same vault state and source
#   metadata |
def test_post_summary_counts_are_deterministic(run_cli, vault, source, helpers):
    """Two vaults driven through the same states report the same counts."""
    assert run_cli("init", "vault2", source.url).returncode == 0

    def drive(name):
        source.set(payload_with(helpers, episodes=["e1", "e2"]))
        assert run_cli("sync", name, "--skip-download").returncode == 0
        source.set(payload_with(helpers, episodes=["e1"], clips=["c1"]))
        result = run_cli("sync", name, "--skip-download")
        assert result.returncode == 0, result.stderr
        return [int(tok) for tok in result.stdout.split() if tok.isdigit()]

    assert drive("vault") == drive("vault2")


# Spec: | Wall-clock usage outside digest trailing line | Not part of file
#   naming or vault content |
# Context: downloaded file names are derived from the entry id and extension only.
def test_downloaded_file_names_carry_no_timestamp(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    source.serve_entry("e1")
    assert run_cli("sync", "vault").returncode == 0
    assert helpers.listing(helpers.media_dir(vault)) == ["e1.mp4"]
    assert helpers.listing(helpers.preview_dir(vault)) == ["e1.jpg"]
