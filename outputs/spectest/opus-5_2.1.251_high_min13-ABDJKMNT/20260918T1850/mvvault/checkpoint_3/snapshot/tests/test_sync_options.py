"""Spec sections: `sync` Options (skip flags), `sync` on Legacy Vaults, Error Handling
(CLI option errors)."""

import json

import pytest

from conftest import (
    media_stems,
    payload,
    preview_names,
    read_catalog,
    source_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)


# Spec: Metadata-only run | `--skip-download`
def test_skip_download_writes_metadata_and_downloads_nothing(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    result = run("sync", "vault", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert [e["id"] for e in read_catalog(vault)["episodes"]] == ["e1"]
    assert source.asset_requests() == []
    assert media_stems(vault) == []


# Spec: Download-only run | `--skip-metadata`
def test_skip_metadata_downloads_without_fetching_source(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    assert run("sync", "vault", "--skip-download").returncode == 0
    metadata_fetches = source.request_count

    result = run("sync", "vault", "--skip-metadata")
    assert result.returncode == 0, result.stderr
    assert source.request_count == metadata_fetches
    assert media_stems(vault) == ["e1"]


# Spec: `--skip-metadata` | Skip source fetch and metadata update
def test_skip_metadata_leaves_catalog_untouched(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    run("sync", "vault", "--skip-download")
    before = (vault / "catalog.json").read_text()

    run("sync", "vault", "--skip-metadata")
    assert (vault / "catalog.json").read_text() == before


# Spec: `--skip-metadata` | ... run download phase against existing vault state
def test_skip_metadata_on_empty_vault_downloads_nothing(run, source, vault):
    source.serve_assets("e1")
    result = run("sync", "vault", "--skip-metadata")
    assert result.returncode == 0, result.stderr
    assert source.asset_requests() == []


# Spec: `--skip-download` combined with `--skip-metadata` leaves a valid, quiet run
def test_both_skip_flags_do_nothing(run, source, vault):
    result = run("sync", "vault", "--skip-metadata", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert source.requests == []


# Spec: `--format=<str>` | Override media download format and output extension
# (previews are unaffected by the media format override)
def test_format_override_does_not_change_preview_extension(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_media("e1", suffix=".mkv")
    source.serve_preview("e1", content_type="image/png")
    run("sync", "vault", "--format=mkv")
    assert preview_names(vault) == ["e1.png"]


# Spec: Because `sync` auto-migrates v1 and v2 vaults to v3 ... the download phase
# always operates against a v3 catalog. The source URL is the migrated `source`.
def test_legacy_v2_vault_downloads_from_migrated_source(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=source.url))
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")

    result = run("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert read_catalog(tmp_path / "vault")["version"] == 3
    assert media_stems(tmp_path / "vault") == ["e1"]


# Spec: `sync` on Legacy Vaults ... the download phase always operates against a v3 catalog
def test_legacy_v2_vault_downloads_entries_absent_from_source(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(clips=[v2_entry("c1")], source=source.url))
    source.serve(payload())
    source.serve_assets("c1")

    assert run("sync", "vault").returncode == 0
    assert media_stems(tmp_path / "vault") == ["c1"]


# Spec: Malformed numeric category limit | stderr | non-zero | Abort before any sync work
@pytest.mark.parametrize("value", ["abc", "1.5", "", "-2", "3x"])
def test_malformed_limit_aborts_before_any_sync_work(run, source, vault, value):
    source.serve(payload(episodes=[source_entry("e1")]))
    result = run("sync", "vault", f"--episodes={value}")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert source.requests == []
    assert read_catalog(vault)["episodes"] == []


# Spec: Malformed numeric category limit | ... applies to every category option
@pytest.mark.parametrize("option", ["--episodes", "--streams", "--clips"])
def test_malformed_limit_rejected_for_every_category(run, source, vault, option):
    result = run("sync", "vault", f"{option}=nope")
    assert result.returncode != 0
    assert source.requests == []


# Spec: Unrecognized CLI option | stderr | non-zero | Abort before any sync work
def test_unrecognized_option_aborts_before_any_sync_work(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    result = run("sync", "vault", "--bogus=1")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert source.requests == []
    assert read_catalog(vault)["episodes"] == []


# Spec: `--episodes=<n>` | non-negative integer (a well-formed limit is accepted)
def test_valid_limit_is_accepted(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    assert run("sync", "vault", "--episodes=1").returncode == 0


# Spec: Syntax | `python mvault.py sync <name> [options]` (options may follow the name)
def test_options_may_be_combined(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_media("e1", suffix=".ogg")
    source.serve_preview("e1")
    result = run("sync", "vault", "--episodes=1", "--format=ogg")
    assert result.returncode == 0, result.stderr
    assert media_stems(vault) == ["e1"]
