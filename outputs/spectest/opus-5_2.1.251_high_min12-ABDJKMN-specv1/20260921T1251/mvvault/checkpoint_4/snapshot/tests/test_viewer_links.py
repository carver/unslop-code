"""Spec section: `digest` and Post-Sync Viewer Links."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mvault  # noqa: E402  (in-process checks for states HTTP cannot reach)

LINK_RE = re.compile(r"http://[^\s\"'<>]+")


def payload_with(helpers, **categories):
    return helpers.make_payload(
        **{name: [helpers.make_source_entry(i) for i in ids]
           for name, ids in categories.items()})


def line_for(stdout, needle):
    """The single output line carrying `needle`."""
    matches = [line for line in stdout.splitlines() if needle in line]
    assert matches, f"no line contains {needle!r} in:\n{stdout}"
    return matches[0]


# ---------------------------------------------------------------------------
# | `digest <name>` | Each changed-entry line includes viewer link on same line
#   as title |
# ---------------------------------------------------------------------------

# Spec: | `digest <name>` | Each changed-entry line includes viewer link on same
#   line as title |
def test_digest_addition_line_carries_the_link(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    line = line_for(run_cli("digest", "vault").stdout, "Title e1")
    assert "http://127.0.0.1:8840/catalog/vault/episodes/e1" in line, line


# Spec: | ... viewer link on same line as title |
# Context: a field-update line carries the link too.
def test_digest_update_line_carries_the_link(run_cli, make_vault, catalogs):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 2}
    make_vault(catalogs.catalog(episodes=[entry]))
    line = line_for(run_cli("digest", "vault").stdout, "Title e1")
    assert "/catalog/vault/episodes/e1" in line, line


# Spec: | ... viewer link on same line as title |
# Context: a removal line carries the link too.
def test_digest_removal_line_carries_the_link(run_cli, make_vault, catalogs):
    entry = catalogs.entry("e1")
    entry["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    line = line_for(run_cli("digest", "vault").stdout, "Title e1")
    assert "/catalog/vault/episodes/e1" in line, line


# Spec: | ... Each changed-entry line ... |
# Context: every changed entry gets its own link, and only changed entries are
# listed at all.
def test_digest_links_every_changed_entry(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")],
                                streams=[catalogs.entry("s1")],
                                clips=[catalogs.entry("c1")]))
    stdout = run_cli("digest", "vault").stdout
    assert "/catalog/vault/episodes/e1" in line_for(stdout, "Title e1")
    assert "/catalog/vault/streams/s1" in line_for(stdout, "Title s1")
    assert "/catalog/vault/clips/c1" in line_for(stdout, "Title c1")


# Spec: | ... on same line as title | (the title is not pushed onto its own line)
def test_digest_link_and_title_share_one_line(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    stdout = run_cli("digest", "vault").stdout
    links = [line for line in stdout.splitlines() if "/catalog/vault/" in line]
    assert links, stdout
    for line in links:
        assert "Title e1" in line, line


# Spec: | Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |
#       | Default scheme | `http://` | | Default host | `127.0.0.1` |
#       | Default port | `8840` |
def test_digest_link_uses_the_documented_format(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    line = line_for(run_cli("digest", "vault").stdout, "Title e1")
    link = LINK_RE.search(line).group(0).rstrip(").,")
    assert link == "http://127.0.0.1:8840/catalog/vault/episodes/e1", link


# Spec: | Link format | `http://<host>:<port>/catalog/<name>/...` |
# Context: `<name>` is the vault name as given on the command line.
def test_digest_link_carries_the_vault_name(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="other")
    line = line_for(run_cli("digest", "other").stdout, "Title e1")
    assert "http://127.0.0.1:8840/catalog/other/episodes/e1" in line, line


# Spec: | No notable changes anywhere | ... | + link rules
# Context: with nothing changed there is no changed-entry line to link.
def test_digest_without_changes_has_no_links(run_cli, make_vault, catalogs):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 5, catalogs.STAMP_2: 5}
    make_vault(catalogs.catalog(episodes=[entry]))
    stdout = run_cli("digest", "vault").stdout
    assert "/catalog/vault/episodes/e1" not in stdout, stdout


# ---------------------------------------------------------------------------
# | `digest` Viewer Link - Version-Aware Category |
# ---------------------------------------------------------------------------

# Spec: | v1 | `entries` |
def test_digest_v1_link_uses_the_entries_category(run_cli, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    line = line_for(run_cli("digest", "vault").stdout, "Title e1")
    assert "http://127.0.0.1:8840/catalog/vault/entries/e1" in line, line


# Spec: | v2 | Category where entry resides (`episodes`, `streams`, or `clips`) |
def test_digest_v2_link_uses_the_residing_category(run_cli, make_vault, legacy):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")],
                                 streams=[legacy.v2_entry("s1")],
                                 clips=[legacy.v2_entry("c1")]))
    stdout = run_cli("digest", "vault").stdout
    assert "/catalog/vault/episodes/e1" in line_for(stdout, "Title e1")
    assert "/catalog/vault/streams/s1" in line_for(stdout, "Title s1")
    assert "/catalog/vault/clips/c1" in line_for(stdout, "Title c1")


# Spec: | v3 | Category where entry resides (`episodes`, `streams`, or `clips`) |
def test_digest_v3_link_uses_the_residing_category(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(streams=[catalogs.entry("s1")]))
    line = line_for(run_cli("digest", "vault").stdout, "Title s1")
    assert "/catalog/vault/streams/s1" in line
    assert "/catalog/vault/episodes/s1" not in line


# Spec: | v1 | `entries` |
# Context: a v1 digest never names a v2/v3 category, even though `sync` would
# migrate those same entries into `episodes`.
def test_digest_v1_link_never_says_episodes(run_cli, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert "/catalog/vault/episodes/" not in run_cli("digest", "vault").stdout


# ---------------------------------------------------------------------------
# | Post-sync summary | Each changed-entry line includes viewer link on same
#   line as title |
# ---------------------------------------------------------------------------

# Spec: | Post-sync summary | Each changed-entry line includes viewer link on
#   same line as title |
def test_post_sync_addition_line_carries_the_link(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--skip-download")
    assert result.returncode == 0, result.stderr
    line = line_for(result.stdout, "Title e1")
    assert "http://127.0.0.1:8840/catalog/vault/episodes/e1" in line, line


# Spec: | Post-sync summary | ... |
# Context: an updated entry is a changed entry too.
def test_post_sync_update_line_carries_the_link(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("e1", title="Renamed")]))
    result = run_cli("sync", "vault", "--skip-download")
    line = line_for(result.stdout, "Renamed")
    assert "/catalog/vault/episodes/e1" in line, line


# Spec: | Post-sync summary | ... |
# Context: a removed entry is a changed entry too.
def test_post_sync_removal_line_carries_the_link(run_cli, vault, source, helpers):
    source.set(payload_with(helpers, episodes=["e1", "e2"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    source.set(payload_with(helpers, episodes=["e1"]))
    result = run_cli("sync", "vault", "--skip-download")
    line = line_for(result.stdout, "Title e2")
    assert "/catalog/vault/episodes/e2" in line, line


# Spec: | Post-sync summary | Each changed-entry line ... |
# Context: entries the sync did not change are not listed.
def test_post_sync_unchanged_entries_are_not_linked(run_cli, vault, source,
                                                    helpers):
    source.set(payload_with(helpers, episodes=["e1"]))
    assert run_cli("sync", "vault", "--skip-download").returncode == 0
    result = run_cli("sync", "vault", "--skip-download")
    assert "/catalog/vault/episodes/e1" not in result.stdout, result.stdout


# Spec: | Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |
def test_post_sync_link_uses_the_documented_format(run_cli, vault, source,
                                                   helpers):
    source.set(payload_with(helpers, clips=["c1"]))
    result = run_cli("sync", "vault", "--skip-download")
    line = line_for(result.stdout, "Title c1")
    link = LINK_RE.search(line).group(0).rstrip(").,")
    assert link == "http://127.0.0.1:8840/catalog/vault/clips/c1", link


# ---------------------------------------------------------------------------
# | Post-Sync Viewer Link - Version-Aware Category |
# ---------------------------------------------------------------------------

# Spec: | v3 vault after `sync` | Category where entry resides |
def test_post_sync_v3_links_use_the_residing_category(run_cli, vault, source,
                                                      helpers):
    source.set(payload_with(helpers, episodes=["e1"], streams=["s1"],
                            clips=["c1"]))
    stdout = run_cli("sync", "vault", "--skip-download").stdout
    assert "/catalog/vault/episodes/e1" in line_for(stdout, "Title e1")
    assert "/catalog/vault/streams/s1" in line_for(stdout, "Title s1")
    assert "/catalog/vault/clips/c1" in line_for(stdout, "Title c1")


# Spec: | v2 vault after `sync` | Category where entry resides (`episodes`,
#   `streams`, or `clips`) |
def test_post_sync_v2_links_use_the_residing_category(run_cli, make_vault,
                                                      legacy, source, helpers):
    make_vault(legacy.v2_catalog(streams=[legacy.v2_entry("s1")]))
    source.set(helpers.make_payload(
        streams=[helpers.make_source_entry("s1", views=999)]))
    stdout = run_cli("sync", "vault", "--skip-download").stdout
    assert "/catalog/vault/streams/s1" in line_for(stdout, "Title s1"), stdout


# Spec: | v2 vault after `sync` | ... |
# Context: the post-sync link never uses the v1 `entries` category.
def test_post_sync_v2_link_never_says_entries(run_cli, make_vault, legacy,
                                              source, helpers):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("e1", views=7)]))
    stdout = run_cli("sync", "vault", "--skip-download").stdout
    assert "/catalog/vault/entries/" not in stdout, stdout


# Spec: | v1 vault after `sync` auto-migrates it to v3 | `episodes` for
#   migrated episode entries |
# Context: a v1 vault's derived source URL is not reachable from a test, so the
# migrated-then-synced state is built in process and handed to the same
# summary code the CLI uses.
def test_post_sync_v1_migrated_entries_link_as_episodes(legacy, helpers):
    stamp = "2024-07-01T00:00:00"
    catalog = mvault.migrate_catalog(
        legacy.v1_catalog(entries=[legacy.v1_entry("e1")]), 1, stamp)
    assert catalog["version"] == 3
    payload = helpers.make_payload(
        episodes=[helpers.make_source_entry("e1", title="Renamed")])
    counts, changes = mvault.apply_source(catalog, payload, stamp)
    lines = mvault.sync_summary_lines("vault", stamp, counts, changes)
    line = line_for("\n".join(lines), "Renamed")
    assert "http://127.0.0.1:8840/catalog/vault/episodes/e1" in line, line


# Spec: | v1 vault after `sync` auto-migrates it to v3 | `episodes` ... |
# Context: the same catalog read by `digest` before any sync links `entries`
# instead - the two surfaces differ exactly because the vault version differs.
def test_v1_digest_and_post_sync_categories_differ(run_cli, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    stdout = run_cli("digest", "vault").stdout
    assert "/catalog/vault/entries/e1" in stdout
    assert "/catalog/vault/episodes/e1" not in stdout


# ---------------------------------------------------------------------------
# | Link format | `http://<host>:<port>/...` + the viewer serves that link
# ---------------------------------------------------------------------------

# Spec: "appends viewer links to human-facing change reports" + | `GET` |
#   `/catalog/<name>/<category>/<id>` | HTML response for that viewer link
#   target |
# Context: the link `digest` prints resolves on a running server.
def test_digest_link_path_resolves_on_the_server(run_cli, make_vault, catalogs,
                                                 serve):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    line = line_for(run_cli("digest", "vault").stdout, "Title e1")
    path = LINK_RE.search(line).group(0).rstrip(").,").split("8840", 1)[1]
    response = serve().client.get(path)
    assert response.status == 200, (path, response.status)
    assert "Title e1" in response.body
