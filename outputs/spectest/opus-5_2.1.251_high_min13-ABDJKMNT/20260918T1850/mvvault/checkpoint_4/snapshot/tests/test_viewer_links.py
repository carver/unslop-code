"""Spec sections: `digest` and Post-Sync Viewer Links, `digest` Viewer Link --
Version-Aware Category, Post-Sync Viewer Link -- Version-Aware Category."""

import pytest
import responses

from conftest import (
    V1_SOURCE_TEMPLATE,
    V2_LATER,
    V2_STAMP,
    payload,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

from mvaultlib.commands import SyncOptions, sync_vault

#: Prefix every viewer link is built on, with the spec's default scheme/host/port.
BASE = "http://127.0.0.1:8840"


def line_with(stdout, needle):
    """The single output line containing `needle`."""
    matches = [line for line in stdout.splitlines() if needle in line]
    assert len(matches) == 1, f"expected one line with {needle!r}, got {matches}"
    return matches[0]


@pytest.fixture
def mocked_source(tmp_path, monkeypatch):
    """Run `sync` in-process against a mocked source, from inside `tmp_path`."""
    monkeypatch.chdir(tmp_path)
    with responses.RequestsMock() as mock:
        yield mock


# Spec: `digest <name>` | Each changed-entry line includes viewer link on same
# line as title
# Spec: Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`
def test_digest_line_carries_the_viewer_link(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    line = line_with(run("digest", "vault").stdout, "Title e1")
    assert f"{BASE}/catalog/vault/episodes/e1" in line


# Spec: Default scheme | `http://`; Default host | `127.0.0.1`; Default port | `8840`
def test_viewer_link_uses_the_default_scheme_host_and_port(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]), name="archive")
    assert "http://127.0.0.1:8840/catalog/archive/episodes/e1" in run("digest", "archive").stdout


# Spec: `digest <name>` | ... on the same line as the title (field updates keep
# their suffix)
def test_digest_update_line_keeps_title_suffix_and_link(run, tmp_path):
    entry = v3_entry("e1", title={V2_STAMP: "Old", V2_LATER: "New title"})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    line = line_with(run("digest", "vault").stdout, "New title")
    assert "(title)" in line
    assert f"{BASE}/catalog/vault/episodes/e1" in line


# Spec: v1 | `entries`
def test_v1_digest_links_use_the_entries_category(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    line = line_with(run("digest", "vault").stdout, "Title e1")
    assert f"{BASE}/catalog/vault/entries/e1" in line


# Spec: v2 | Category where entry resides (`episodes`, `streams`, or `clips`)
def test_v2_digest_links_use_the_entrys_own_category(run, tmp_path):
    write_vault(tmp_path, v2_catalog(streams=[v2_entry("s1")], clips=[v2_entry("c1")]))
    stdout = run("digest", "vault").stdout
    assert f"{BASE}/catalog/vault/streams/s1" in line_with(stdout, "Title s1")
    assert f"{BASE}/catalog/vault/clips/c1" in line_with(stdout, "Title c1")


# Spec: v3 | Category where entry resides (`episodes`, `streams`, or `clips`)
def test_v3_digest_links_use_the_entrys_own_category(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")], clips=[v3_entry("c1")]))
    stdout = run("digest", "vault").stdout
    assert f"{BASE}/catalog/vault/episodes/e1" in line_with(stdout, "Title e1")
    assert f"{BASE}/catalog/vault/clips/c1" in line_with(stdout, "Title c1")


# Spec: Post-sync summary | Each changed-entry line includes viewer link on same
# line as title
def test_post_sync_line_carries_the_viewer_link(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    stdout = run("sync", "vault", "--skip-download").stdout
    assert f"{BASE}/catalog/vault/episodes/e1" in line_with(stdout, "Title e1")


# Spec: v3 vault after `sync` | Category where entry resides
def test_post_sync_links_follow_the_entrys_category(run, source, vault):
    source.serve(
        payload(
            episodes=[source_entry("e1")],
            streams=[source_entry("s1")],
            clips=[source_entry("c1")],
        )
    )
    stdout = run("sync", "vault", "--skip-download").stdout
    assert f"{BASE}/catalog/vault/episodes/e1" in line_with(stdout, "Title e1")
    assert f"{BASE}/catalog/vault/streams/s1" in line_with(stdout, "Title s1")
    assert f"{BASE}/catalog/vault/clips/c1" in line_with(stdout, "Title c1")


# Spec: Post-sync summary | ... removed entries are changed entries too
def test_post_sync_removal_line_carries_the_viewer_link(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault", "--skip-download")
    source.serve(payload())
    stdout = run("sync", "vault", "--skip-download").stdout
    assert f"{BASE}/catalog/vault/episodes/e1" in line_with(stdout, "Title e1")


# Spec: v2 vault after `sync` | Category where entry resides
def test_post_sync_on_a_v2_vault_uses_the_entrys_category(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(clips=[v2_entry("c1")], source=source.url))
    source.serve(payload(clips=[source_entry("c1", title="Renamed clip")]))
    stdout = run("sync", "vault", "--skip-download").stdout
    assert f"{BASE}/catalog/vault/clips/c1" in line_with(stdout, "Renamed clip")


# Spec: v1 vault after `sync` auto-migrates it to v3 | `episodes` for migrated
# episode entries
def test_post_sync_on_a_v1_vault_uses_episodes(mocked_source, tmp_path, capsys):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    mocked_source.get(
        V1_SOURCE_TEMPLATE.format("chan-1"),
        json=payload(episodes=[source_entry("e1", title="Renamed episode")]),
    )

    sync_vault("vault", SyncOptions(skip_download=True))
    stdout = capsys.readouterr().out
    assert f"{BASE}/catalog/vault/episodes/e1" in line_with(stdout, "Renamed episode")
