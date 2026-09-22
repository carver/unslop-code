"""Spec: `digest` and Post-Sync Viewer Links, and the two version-aware
category tables."""
import re

import pytest

from conftest import make_entry
from digest_helpers import (K1, K2, E1, E2, v1, v1_entry, v2, v3, v3_entry,
                            legacy_entry, section_links, sections, split_link,
                            summary_links, summary_sections)

DEFAULT_ORIGIN = "http://127.0.0.1:8840"
URL_RE = re.compile(r"https?://\S+")


def all_links(mapping):
    """Every link in a `{category: {group: [link, ...]}}` mapping."""
    found = []
    for groups in mapping.values():
        for links in groups.values():
            found.extend(links)
    return found


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------
# Spec: "| `digest <name>` | Each changed-entry line includes viewer link on
# same line as title |"
def test_digest_line_carries_a_viewer_link(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep One")]))
    stdout = run("digest", "vault").stdout
    assert sections(stdout)["Episodes"]["Added"] == ["Ep One"]
    assert section_links(stdout)["Episodes"]["Added"] == [
        "%s/catalog/vault/episodes/e1" % DEFAULT_ORIGIN]


# Spec: "| `digest <name>` | Each changed-entry line includes viewer link on
# *same line* as title |" -- title and link share one physical line.
def test_link_is_on_the_same_line_as_the_title(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep One")]))
    stdout = run("digest", "vault").stdout
    matching = [line for line in stdout.split("\n") if "Ep One" in line]
    assert len(matching) == 1, stdout
    assert "/catalog/vault/episodes/e1" in matching[0]


# Spec: "| Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`
# |" + "| Default scheme | `http://` |" + "| Default host | `127.0.0.1` |" +
# "| Default port | `8840` |"
def test_default_link_format(run, make_vault):
    make_vault(v3(clips=[v3_entry(id="c-9", title="Clip")]), name="myvault")
    stdout = run("digest", "myvault").stdout
    assert section_links(stdout)["Clips"]["Added"] == [
        "http://127.0.0.1:8840/catalog/myvault/clips/c-9"]


# Spec: "| `digest <name>` | Each *changed-entry* line ... |" -- every reported
# line in every group carries a link.
def test_every_digest_group_line_has_a_link(run, make_vault):
    make_vault(v3(episodes=[
        v3_entry(id="a1", title="Added"),
        v3_entry(id="u1", title={K1: "x", K2: "Updated"}),
        v3_entry(id="r1", title="Removed", removed={K1: False, K2: True}),
    ]))
    stdout = run("digest", "vault").stdout
    links = section_links(stdout)["Episodes"]
    assert links["Added"] == ["%s/catalog/vault/episodes/a1" % DEFAULT_ORIGIN]
    assert links["Updated"] == ["%s/catalog/vault/episodes/u1" % DEFAULT_ORIGIN]
    assert links["Removed"] == ["%s/catalog/vault/episodes/r1" % DEFAULT_ORIGIN]


# Spec: "| v3 | Category where entry resides (`episodes`, `streams`, or
# `clips`) |"
def test_v3_link_category_is_where_the_entry_resides(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")], streams=[v3_entry(id="s1")],
                  clips=[v3_entry(id="c1")]))
    links = section_links(run("digest", "vault").stdout)
    assert links["Episodes"]["Added"] == ["%s/catalog/vault/episodes/e1" % DEFAULT_ORIGIN]
    assert links["Streams"]["Added"] == ["%s/catalog/vault/streams/s1" % DEFAULT_ORIGIN]
    assert links["Clips"]["Added"] == ["%s/catalog/vault/clips/c1" % DEFAULT_ORIGIN]


# Spec: "| v2 | Category where entry resides (`episodes`, `streams`, or
# `clips`) |"
def test_v2_link_category_is_where_the_entry_resides(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")],
                  streams=[legacy_entry(id="s1")],
                  clips=[legacy_entry(id="c1")]))
    links = section_links(run("digest", "vault").stdout)
    assert links["Episodes"]["Added"] == ["%s/catalog/vault/episodes/e1" % DEFAULT_ORIGIN]
    assert links["Streams"]["Added"] == ["%s/catalog/vault/streams/s1" % DEFAULT_ORIGIN]
    assert links["Clips"]["Added"] == ["%s/catalog/vault/clips/c1" % DEFAULT_ORIGIN]


# Spec: "| v1 | `entries` |" -- a v1 digest links into the `entries` category.
def test_v1_link_category_is_entries(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title={E1: "Flat"})]))
    stdout = run("digest", "vault").stdout
    assert section_links(stdout)["Entries"]["Added"] == [
        "%s/catalog/vault/entries/e1" % DEFAULT_ORIGIN]


# Spec: "| Link format | .../catalog/<name>/... |" -- the vault name in the
# link is the name the command was given.
def test_link_uses_the_requested_vault_name(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="other-name")
    stdout = run("digest", "other-name").stdout
    assert all_links(section_links(stdout)) == [
        "%s/catalog/other-name/episodes/e1" % DEFAULT_ORIGIN]


# Spec: viewer links follow the field-change annotation rather than replacing
# it, so the changed-field list survives.
def test_link_follows_the_changed_field_annotation(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "x", K2: "New"},
                                     views={K1: 1, K2: 2})]))
    stdout = run("digest", "vault").stdout
    assert sections(stdout)["Episodes"]["Updated"] == ["New (title, views)"]
    assert section_links(stdout)["Episodes"]["Updated"] == [
        "%s/catalog/vault/episodes/e1" % DEFAULT_ORIGIN]


# Spec: "| Any ... | ... |" -- a digest with nothing to report has no link.
def test_no_links_when_nothing_changed(run, make_vault):
    make_vault(v3())
    stdout = run("digest", "vault").stdout
    assert all_links(section_links(stdout)) == []


# Spec: "| Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`
# |" -- the link resolves to the route the viewer actually serves.
def test_digest_link_target_is_served(run, make_vault, serve):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep One")]))
    stdout = run("digest", "vault").stdout
    link = section_links(stdout)["Episodes"]["Added"][0]
    path = link.split("8840", 1)[1]
    assert path == "/catalog/vault/episodes/e1"
    server = serve()
    assert server.get(path).status == 200


# --------------------------------------------------------------------------
# post-sync summary
# --------------------------------------------------------------------------
# Spec: "| Post-sync summary | Each changed-entry line includes viewer link on
# same line as title |"
def test_post_sync_summary_lists_changed_entries_with_links(run, source, vault):
    source.serve(episodes=[make_entry(id="e1", title="Ep One")])
    res = run("sync", "vault", "--skip-download")
    assert res.returncode == 0, res
    assert summary_sections(res.stdout)["Episodes"]["Added"] == ["Ep One"]
    assert summary_links(res.stdout)["Episodes"]["Added"] == [
        "%s/catalog/vault/episodes/e1" % DEFAULT_ORIGIN]


# Spec: "| Post-sync summary | ... on same line as title |"
def test_post_sync_link_shares_the_title_line(run, source, vault):
    source.serve(episodes=[make_entry(id="e1", title="Ep One")])
    res = run("sync", "vault", "--skip-download")
    matching = [line for line in res.stdout.split("\n") if "Ep One" in line]
    assert len(matching) == 1, res.stdout
    assert "/catalog/vault/episodes/e1" in matching[0]


# Spec: "| v3 vault after `sync` | Category where entry resides ... |"
def test_post_sync_v3_link_category(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")], streams=[make_entry(id="s1")],
                 clips=[make_entry(id="c1")])
    res = run("sync", "vault", "--skip-download")
    links = summary_links(res.stdout)
    assert links["Episodes"]["Added"] == ["%s/catalog/vault/episodes/e1" % DEFAULT_ORIGIN]
    assert links["Streams"]["Added"] == ["%s/catalog/vault/streams/s1" % DEFAULT_ORIGIN]
    assert links["Clips"]["Added"] == ["%s/catalog/vault/clips/c1" % DEFAULT_ORIGIN]


# Spec: "| v2 vault after `sync` | Category where entry resides (`episodes`,
# `streams`, or `clips`) |"
def test_post_sync_v2_link_category(run, source, make_vault):
    from conftest import make_v2_catalog
    make_vault(make_v2_catalog(source=source.url, episodes=[],
                               streams=[], clips=[]))
    source.serve(streams=[make_entry(id="s1", title="Stream One")])
    res = run("sync", "vault", "--skip-download")
    assert res.returncode == 0, res
    assert summary_links(res.stdout)["Streams"]["Added"] == [
        "%s/catalog/vault/streams/s1" % DEFAULT_ORIGIN]


# Spec: "| Post-sync summary | Each changed-entry line ... |" -- updates and
# removals get links too.
def test_post_sync_updates_and_removals_have_links(run, source, vault):
    source.serve(episodes=[make_entry(id="e1", title="A"),
                           make_entry(id="e2", title="B")])
    run("sync", "vault", "--skip-download")
    source.serve(episodes=[make_entry(id="e1", title="A2")],
                 clips=[make_entry(id="c1", title="C")])
    res = run("sync", "vault", "--skip-download")
    links = summary_links(res.stdout)
    assert links["Episodes"]["Updated"] == ["%s/catalog/vault/episodes/e1" % DEFAULT_ORIGIN]
    assert links["Episodes"]["Removed"] == ["%s/catalog/vault/episodes/e2" % DEFAULT_ORIGIN]
    assert links["Clips"]["Added"] == ["%s/catalog/vault/clips/c1" % DEFAULT_ORIGIN]


# Spec: "| Trigger | Successful `sync` run that includes metadata phase |" --
# an unchanged run reports no changed-entry lines and therefore no links.
def test_post_sync_unchanged_run_has_no_links(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault", "--skip-download")
    res = run("sync", "vault", "--skip-download")
    assert URL_RE.search("\n".join(
        line for line in res.stdout.split("\n") if line.startswith(" "))) is None


# Spec: "| Post-sync summary | ... |" -- a `--skip-metadata` run has no
# metadata phase, so no changed-entry lines at all.
def test_no_summary_lines_when_metadata_skipped(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault", "--skip-download")
    res = run("sync", "vault", "--skip-metadata", "--skip-download")
    assert res.stdout.strip() == "", res


# Spec: "| v1 vault after `sync` auto-migrates it to v3 | `episodes` for
# migrated episode entries |".
#
# A v1 vault's source URL is derived from `source_id` and always points at
# `https://media.example.com/...`, which no test server can answer, so this
# case is driven in-process with the source fetch stubbed out.
def test_post_sync_v1_links_use_episodes(tmp_path, monkeypatch, capsys):
    import json
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import mvault

    directory = tmp_path / "vault"
    directory.mkdir()
    with open(str(directory / "catalog.json"), "w", encoding="utf-8") as fh:
        json.dump(v1(entries=[v1_entry(id="e1", title={E1: "Old"})]), fh)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mvault, "fetch_source", lambda url: {
        "episodes": [make_entry(id="e1", title="New"),
                     make_entry(id="e2", title="Fresh")],
        "streams": [], "clips": []})

    assert mvault.main(["sync", "vault", "--skip-download"]) == 0
    stdout = capsys.readouterr().out
    links = summary_links(stdout)
    assert links["Episodes"]["Added"] == [
        "%s/catalog/vault/episodes/e2" % DEFAULT_ORIGIN]
    assert links["Episodes"]["Updated"] == [
        "%s/catalog/vault/episodes/e1" % DEFAULT_ORIGIN]
    # The vault is v3 on disk afterwards, and nothing links to `entries`.
    assert "/catalog/vault/entries/" not in stdout


# Spec: "| Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`
# |" -- the post-sync link resolves to a route the viewer serves.
def test_post_sync_link_target_is_served(run, source, vault, serve):
    source.serve(episodes=[make_entry(id="e1", title="Ep One")])
    res = run("sync", "vault", "--skip-download")
    link = summary_links(res.stdout)["Episodes"]["Added"][0]
    path = link.split("8840", 1)[1]
    server = serve()
    assert server.get(path).status == 200


# Spec: "| Post-sync summary | ... |" -- the three counts are still reported
# alongside the per-entry lines.
def test_post_sync_counts_still_reported(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    res = run("sync", "vault", "--skip-download")
    assert re.search(r"1\s+added", res.stdout, re.IGNORECASE), res.stdout
