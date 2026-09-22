"""`digest` and Post-Sync Viewer Links."""

import mvault
import pytest
from mvaultlib import source as source_module

from conftest import (
    SOURCE_URL,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    viewer_link,
)

OLD_ISO, NEW_ISO = "2024-01-01T00:00:00", "2024-06-15T09:40:00"
OLD_EPOCH, NEW_EPOCH = "1718444400", "1718448000"


def line_for(output, title):
    """The single report line naming `title`."""
    matches = [line for line in output.splitlines() if title in line]
    assert len(matches) == 1, output
    return matches[0]


def updated(entry_factory, entry_id, old_stamp, new_stamp, **overrides):
    """An entry whose `views` history has two values, so it reads as updated."""
    return entry_factory(entry_id, stamp=old_stamp, views={old_stamp: 10, new_stamp: 20}, **overrides)


@pytest.fixture
def digest(run_cli, make_vault):
    """Write a catalog and return the `digest` output for it."""

    def run(catalog, name="v"):
        make_vault(catalog, name)
        result = run_cli("digest", name)
        assert result.returncode == 0, result.stderr
        return result.stdout

    return run


@pytest.fixture
def synced(run_cli, make_vault, source):
    """Write a catalog pointed at the local source, sync it, return the output."""

    def run(catalog, name="v", episodes=(), streams=(), clips=()):
        make_vault({**catalog, "source": source.url}, name)
        source.payload = {"episodes": list(episodes), "streams": list(streams), "clips": list(clips)}
        result = run_cli("sync", name, "--skip-download")
        assert result.returncode == 0, result.stderr
        return result.stdout

    return run


@pytest.fixture
def sync_v1(monkeypatch, tmp_path, make_vault, capsys):
    """Sync a version 1 vault in-process, since its source URL is derived."""

    def run(catalog, episodes=()):
        make_vault(catalog)
        monkeypatch.chdir(tmp_path)
        snapshot = {"episodes": list(episodes), "streams": [], "clips": []}
        monkeypatch.setattr(source_module, "fetch", lambda url: snapshot)
        assert mvault.main(["sync", "v", "--skip-download"]) == 0
        return capsys.readouterr().out

    return run


# Spec: `digest <name>` | Each changed-entry line includes viewer link on same
# line as title
def test_digest_entry_line_carries_a_viewer_link(digest):
    entry = updated(v3_entry, "a", OLD_ISO, NEW_ISO)
    assert viewer_link("v", "episodes", "a") in line_for(digest(v3_catalog(SOURCE_URL, episodes=[entry])), "title-a")


# Spec: Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`
# Spec: Default scheme | `http://` | Default host | `127.0.0.1` | Default port | `8840`
def test_digest_link_uses_the_default_scheme_host_and_port(digest):
    output = digest(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]))
    assert "http://127.0.0.1:8840/catalog/v/episodes/a" in line_for(output, "title-a")


# Spec: `digest` Viewer Link | v1 | `entries`
def test_v1_digest_links_use_the_entries_category(digest):
    entry = updated(v1_entry, "a", OLD_EPOCH, NEW_EPOCH)
    assert viewer_link("v", "entries", "a") in line_for(digest(v1_catalog([entry])), "title-a")


# Spec: `digest` Viewer Link | v2 | Category where entry resides
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_digest_links_use_the_entry_category(digest, category):
    entry = updated(v2_entry, "a", OLD_ISO, NEW_ISO)
    output = digest(v2_catalog(SOURCE_URL, **{category: [entry]}))
    assert viewer_link("v", category, "a") in line_for(output, "title-a")


# Spec: `digest` Viewer Link | v3 | Category where entry resides
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_digest_links_use_the_entry_category(digest, category):
    entry = updated(v3_entry, "a", OLD_ISO, NEW_ISO)
    output = digest(v3_catalog(SOURCE_URL, **{category: [entry]}))
    assert viewer_link("v", category, "a") in line_for(output, "title-a")


# Spec: Link format | ... `/catalog/<name>/...` (the vault name is the one named
# on the command line)
def test_digest_link_names_the_vault(digest):
    output = digest(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]), name="other")
    assert viewer_link("other", "episodes", "a") in line_for(output, "title-a")


# Spec: `digest <name>` | Each changed-entry line includes viewer link (a
# removed entry is a changed entry too)
def test_digest_removal_line_carries_a_viewer_link(digest):
    entry = v3_entry("a", removed={OLD_ISO: False, NEW_ISO: True})
    output = digest(v3_catalog(SOURCE_URL, episodes=[entry]))
    assert viewer_link("v", "episodes", "a") in line_for(output, "title-a")


# Spec: Post-sync summary | Each changed-entry line includes viewer link on same
# line as title
def test_post_sync_summary_lists_changed_entries_with_links(synced):
    output = synced(v3_catalog(SOURCE_URL), episodes=[source_entry("a")])
    assert viewer_link("v", "episodes", "a") in line_for(output, "title-a")


# Spec: Post-Sync Viewer Link | v3 vault after `sync` | Category where entry resides
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_post_sync_links_use_the_entry_category(synced, category):
    output = synced(v3_catalog(SOURCE_URL), **{category: [source_entry("a")]})
    assert viewer_link("v", category, "a") in line_for(output, "title-a")


# Spec: Post-Sync Viewer Link | v2 vault after `sync` | Category where entry resides
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_post_sync_links_use_the_entry_category(synced, category):
    catalog = v2_catalog(SOURCE_URL, **{category: [v2_entry("a", views={OLD_ISO: 10})]})
    output = synced(catalog, **{category: [source_entry("a", views=99)]})
    assert viewer_link("v", category, "a") in line_for(output, "title-a")


# Spec: Post-Sync Viewer Link | v1 vault after `sync` auto-migrates it to v3 |
# `episodes` for migrated episode entries
def test_v1_post_sync_links_use_the_episodes_category(sync_v1):
    output = sync_v1(v1_catalog([v1_entry("a")]), episodes=[source_entry("a", views=99)])
    assert viewer_link("v", "episodes", "a") in line_for(output, "title-a")


# Spec: Post-sync summary | Each changed-entry line includes viewer link (a
# removed entry is a changed entry too)
def test_post_sync_removal_line_carries_a_viewer_link(synced, run_cli, source):
    synced(v3_catalog(SOURCE_URL), episodes=[source_entry("a")])
    source.payload = {"episodes": [], "streams": [], "clips": []}
    result = run_cli("sync", "v", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert viewer_link("v", "episodes", "a") in line_for(result.stdout, "title-a")


# Spec: Post-sync summary | Each changed-entry line ... (unchanged entries are
# not changed-entry lines)
def test_post_sync_summary_omits_unchanged_entries(synced, run_cli, source):
    synced(v3_catalog(SOURCE_URL), episodes=[source_entry("a")])
    result = run_cli("sync", "v", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert "title-a" not in result.stdout


# Spec: Post-sync summary | ... (a `--skip-metadata` run prints no summary)
def test_skip_metadata_prints_no_viewer_links(synced, run_cli):
    synced(v3_catalog(SOURCE_URL), episodes=[source_entry("a")])
    result = run_cli("sync", "v", "--skip-metadata", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert "/catalog/" not in result.stdout


# Spec: `digest` ... (an unchanged vault reports no entry lines and no links)
def test_digest_without_changes_prints_no_links(digest):
    assert "/catalog/" not in digest(v3_catalog(SOURCE_URL))
