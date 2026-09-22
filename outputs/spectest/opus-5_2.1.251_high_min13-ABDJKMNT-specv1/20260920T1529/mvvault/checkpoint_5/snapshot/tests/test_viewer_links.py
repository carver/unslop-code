"""Spec sections: `digest` and Post-Sync Viewer Links, and their categories."""

import pytest

from mvaultlib import sync as sync_module
from mvaultlib.sync import sync_vault

from conftest import (
    V2_KEY,
    V2_OLDER_KEY,
    payload,
    run_cli,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

LINK_BASE = "http://127.0.0.1:8840/catalog"
SOURCE = "https://example.test/a"
LATER_KEY = "2024-12-24T00:00:00"


def updated(entry_id, **overrides):
    """A v3 entry whose `views` changed, so the digest reports it as updated."""
    return v3_entry(entry_id, views={V2_KEY: 10, LATER_KEY: 99}, **overrides)


def digest_lines(tmp_path):
    result = run_cli("digest", "demo", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def line_with(lines, needle):
    """The single reported line mentioning `needle`."""
    matches = [line for line in lines if needle in line]
    assert len(matches) == 1, matches
    return matches[0]


@pytest.fixture
def offline_source(monkeypatch):
    """Stands in for the HTTP fetch, so a v1 vault's derived URL is never read."""
    state = {"payload": payload()}
    monkeypatch.setattr(sync_module, "fetch_source", lambda url: state["payload"])
    return state


def sync_offline(offline_source, capsys, **categories):
    """Sync the `demo` vault in process; returns the summary lines it printed."""
    offline_source["payload"] = payload(**categories)
    sync_vault("demo")
    return capsys.readouterr().out.splitlines()


# `digest` and Post-Sync Viewer Links: "`digest <name>` | Each changed-entry
# line includes viewer link on same line as title"; "Link format |
# `http://<host>:<port>/catalog/<name>/<category>/<id>`".
def test_digest_line_carries_the_viewer_link_beside_the_title(tmp_path):
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[updated("e1")]))

    line = line_with(digest_lines(tmp_path), "title-e1")

    assert f"{LINK_BASE}/demo/episodes/e1" in line


# `digest` and Post-Sync Viewer Links: "Default scheme | `http://`"; "Default
# host | `127.0.0.1`"; "Default port | `8840`".
def test_digest_link_uses_the_default_scheme_host_and_port(tmp_path):
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[updated("e1")]))

    line = line_with(digest_lines(tmp_path), "title-e1")

    assert "http://127.0.0.1:8840/" in line


# `digest` Viewer Link — Version-Aware Category: "v3 | Category where entry
# resides (`episodes`, `streams`, or `clips`)".
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_digest_link_names_the_v3_category_of_the_entry(tmp_path, category):
    write_vault(tmp_path, v3_catalog(SOURCE, **{category: [updated("x1")]}))

    line = line_with(digest_lines(tmp_path), "title-x1")

    assert f"{LINK_BASE}/demo/{category}/x1" in line


# `digest` Viewer Link — Version-Aware Category: "v2 | Category where entry
# resides (`episodes`, `streams`, or `clips`)".
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_digest_link_names_the_v2_category_of_the_entry(tmp_path, category):
    entry = v2_entry("x1", views={V2_OLDER_KEY: 1, V2_KEY: 7})
    write_vault(tmp_path, v2_catalog(SOURCE, **{category: [entry]}))

    line = line_with(digest_lines(tmp_path), "title-x1")

    assert f"{LINK_BASE}/demo/{category}/x1" in line


# `digest` Viewer Link — Version-Aware Category: "v1 | `entries`".
def test_digest_link_for_a_v1_vault_uses_entries(tmp_path):
    entry = v1_entry("e1", views={"1700000000": 1, "1718444400": 7})
    write_vault(tmp_path, v1_catalog([entry]))

    line = line_with(digest_lines(tmp_path), "title-e1")

    assert f"{LINK_BASE}/demo/entries/e1" in line


# `digest` and Post-Sync Viewer Links: "Each changed-entry line includes
# viewer link" — additions and removals are changed entries too.
def test_digest_links_additions_and_removals(tmp_path):
    removed = v3_entry("r1", removed={V2_KEY: False, LATER_KEY: True})
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("a1"), removed]))

    lines = digest_lines(tmp_path)

    assert f"{LINK_BASE}/demo/episodes/a1" in line_with(lines, "title-a1")
    assert f"{LINK_BASE}/demo/episodes/r1" in line_with(lines, "title-r1")


# `digest` and Post-Sync Viewer Links: "Post-sync summary | Each changed-entry
# line includes viewer link on same line as title".
def test_post_sync_summary_links_each_changed_entry(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))

    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    line = line_with(result.stdout.splitlines(), "title-e1")
    assert f"{LINK_BASE}/demo/episodes/e1" in line


# `sync` Post-Summary: "Counts reported | Added, removed, updated" — the
# per-entry lines are added beside the counts, not instead of them.
def test_post_sync_summary_still_reports_the_counts(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))

    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)

    assert "1 added" in result.stdout
    assert "0 removed" in result.stdout


# Post-Sync Viewer Link — Version-Aware Category: "v2 vault after `sync` |
# Category where entry resides".
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_post_sync_link_names_the_v2_category(tmp_path, source, category):
    write_vault(tmp_path, v2_catalog(source.url, **{category: [v2_entry("x1")]}))
    source.serve(payload(**{category: [source_entry("x1", views=99)]}))

    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    line = line_with(result.stdout.splitlines(), "title-x1")
    assert f"{LINK_BASE}/demo/{category}/x1" in line


# Post-Sync Viewer Link — Version-Aware Category: "v3 vault after `sync` |
# Category where entry resides".
def test_post_sync_link_names_the_v3_category(tmp_path, source):
    write_vault(tmp_path, v3_catalog(source.url, clips=[v3_entry("c1")]))
    source.serve(payload(clips=[source_entry("c1", title="fresh")]))

    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert f"{LINK_BASE}/demo/clips/c1" in line_with(result.stdout.splitlines(), "fresh")


# Post-Sync Viewer Link — Version-Aware Category: "v1 vault after `sync`
# auto-migrates it to v3 | `episodes` for migrated episode entries".
def test_post_sync_link_for_a_migrated_v1_vault_uses_episodes(
    tmp_path, offline_source, capsys, monkeypatch
):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]))
    monkeypatch.chdir(tmp_path)

    lines = sync_offline(offline_source, capsys, episodes=[source_entry("e1", title="fresh")])

    assert f"{LINK_BASE}/demo/episodes/e1" in line_with(lines, "fresh")


# `digest` and Post-Sync Viewer Links: "Post-sync summary | Each changed-entry
# line includes viewer link" — a removed entry is reported like any other.
def test_post_sync_summary_links_a_removed_entry(vault, tmp_path, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    run_cli("sync", "demo", "--skip-download", cwd=tmp_path)
    source.serve(payload())

    result = run_cli("sync", "demo", "--skip-download", cwd=tmp_path)

    assert "1 removed" in result.stdout
    assert f"{LINK_BASE}/demo/episodes/e1" in line_with(result.stdout.splitlines(), "title-e1")
