"""`sync` on legacy vaults: the download phase runs against the migrated v3 catalog."""

from conftest import ISO_KEY, legacy_entry, names_in, read_catalog, source_entry, v2_catalog, write_vault


# Spec: "Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata
# phase, the download phase always operates against a v3 catalog. The source URL
# for downloads is the migrated `source` value."
def test_v2_vault_downloads_from_the_migrated_source(tmp_path, run_cli, source):
    vault = write_vault(tmp_path, "legacy", v2_catalog(source.url, episodes=[legacy_entry("e1", ISO_KEY)]))
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "legacy")

    assert result.returncode == 0, result.stderr
    assert read_catalog(vault)["version"] == 3
    assert source.asset_requests["media/e1"] == 1
    assert names_in(vault / "media") == ["e1.mp4"]


# Spec: "the download phase always operates against a v3 catalog" -- entries the
# migration moves into v3 categories are candidates in the usual way.
def test_migrated_stream_and_clip_entries_are_candidates(tmp_path, run_cli, source):
    vault = write_vault(
        tmp_path,
        "legacy",
        v2_catalog(source.url, streams=[legacy_entry("s1", ISO_KEY)], clips=[legacy_entry("c1", ISO_KEY)]),
    )
    source.serve(streams=[source_entry("s1")], clips=[source_entry("c1")])

    result = run_cli("sync", "legacy")

    assert result.returncode == 0, result.stderr
    assert names_in(vault / "media") == ["c1.mp4", "s1.mp4"]


# Spec: "| `--skip-metadata` | flag | Skip source fetch and metadata update; run
# download phase against existing vault state |" -- with no metadata phase there
# is no migration to persist, but downloads still resolve the source.
def test_skip_metadata_downloads_without_rewriting_the_legacy_catalog(tmp_path, run_cli, source):
    vault = write_vault(tmp_path, "legacy", v2_catalog(source.url, episodes=[legacy_entry("e1", ISO_KEY)]))

    result = run_cli("sync", "legacy", "--skip-metadata")

    assert result.returncode == 0, result.stderr
    assert read_catalog(vault)["version"] == 2
    assert names_in(vault / "media") == ["e1.mp4"]
