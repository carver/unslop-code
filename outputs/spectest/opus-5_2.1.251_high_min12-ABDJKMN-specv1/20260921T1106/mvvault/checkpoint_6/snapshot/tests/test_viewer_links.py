"""Spec sections: `digest` and Post-Sync Viewer Links / `digest` Viewer Link
Version-Aware Category / Post-Sync Viewer Link Version-Aware Category /
Determinism (viewer-link scheme, host, port)."""
import re

import pytest
from conftest import (V1_SOURCE_PREFIX, entry, entry_lines_raw, links_in,
                      make_vault, payload, v1_catalog, v1_entry, v2_catalog,
                      v2_entry, v3_catalog, v3_entry, viewer_url)

T1 = "2024-01-01T00:00:00"
T2 = "2024-02-01T00:00:00"
E_OLD = "999999999"
E_NEW = "1000000000"

DEFAULT_BASE = "http://127.0.0.1:8840"


# --------------------------------------------------------------------------
# fixture builders
# --------------------------------------------------------------------------

def updated_v3(eid, first="Old", second="New"):
    """A v3 entry whose title changed: a `Field updates` line."""
    item = v3_entry(eid, stamp=T1, title=first)
    item["title"] = {T1: first, T2: second}
    return item


def updated_v2(eid, first="Old", second="New"):
    item = v2_entry(eid, stamp=T1, title=first)
    item["title"] = {T1: first, T2: second}
    return item


def updated_v1(eid, first="Old", second="New"):
    item = v1_entry(eid, epoch=int(E_OLD), title=first)
    item["title"] = {E_OLD: first, E_NEW: second}
    return item


def changed_lines(text):
    """Every entry line of a report, whatever category or group it is under."""
    collected = []
    for label in ("Entries", "Episodes", "Streams", "Clips"):
        for group in ("Removals", "Additions", "Field updates"):
            collected.extend(entry_lines_raw(text, label, group))
    return collected


def entry_links(text):
    """Viewer links on changed-entry lines only.

    The digest trailing line carries the vault's source URL, which is not a
    viewer link.
    """
    return links_in("\n".join(changed_lines(text)))


def line_with(text, title):
    for line in changed_lines(text):
        if title in line:
            return line
    raise AssertionError("no changed-entry line for %r in:\n%s" % (title, text))


def digest(run, name="v"):
    result = run("digest", name)
    assert result.returncode == 0, result.stderr
    return result.stdout


def sync(run, name="v"):
    result = run("sync", name, "--skip-download")
    assert result.returncode == 0, result.stderr
    return result.stdout


# --------------------------------------------------------------------------
# `digest` viewer links
# --------------------------------------------------------------------------

# Phrase: "`digest <name>` | Each changed-entry line includes viewer link on
#          same line as title"
def test_digest_entry_line_carries_a_viewer_link(run, tmp_path):
    make_vault(tmp_path, "v", v3_catalog(episodes=[updated_v3("e1")]))
    line = line_with(digest(run), "New")
    assert DEFAULT_BASE in line, line


# Phrase: "Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`"
def test_digest_link_format(run, tmp_path):
    make_vault(tmp_path, "v", v3_catalog(episodes=[updated_v3("e1")]))
    line = line_with(digest(run), "New")
    assert viewer_url("v", "episodes", "e1") in line, line


# Phrase: "Default scheme | `http://`" + "Default host | `127.0.0.1`" +
#         "Default port | `8840`"
def test_digest_link_uses_default_scheme_host_and_port(run, tmp_path):
    make_vault(tmp_path, "v", v3_catalog(episodes=[updated_v3("e1")]))
    found = entry_links(digest(run))
    assert found, "no viewer link in digest output"
    for link in found:
        assert link.startswith("http://127.0.0.1:8840/catalog/"), link


# Phrase: "Each changed-entry line includes viewer link on same line as title"
# Context: the vault name in the link is the vault being digested.
def test_digest_link_carries_the_vault_name(run, tmp_path):
    make_vault(tmp_path, "mine", v3_catalog(episodes=[updated_v3("e1")]))
    line = line_with(digest(run, "mine"), "New")
    assert viewer_url("mine", "episodes", "e1") in line


# Phrase: "Each changed-entry line includes viewer link on same line as title"
# Context: additions are changed-entry lines too.
def test_digest_addition_line_has_a_link(run, tmp_path):
    make_vault(tmp_path, "v", v3_catalog(episodes=[v3_entry("e1", title="Fresh")]))
    line = line_with(digest(run), "Fresh")
    assert viewer_url("v", "episodes", "e1") in line


# Phrase: "Each changed-entry line includes viewer link on same line as title"
# Context: removals are changed-entry lines too.
def test_digest_removal_line_has_a_link(run, tmp_path):
    gone = v3_entry("e1", stamp=T1, title="Gone")
    gone["removed"] = {T1: False, T2: True}
    make_vault(tmp_path, "v", v3_catalog(episodes=[gone]))
    line = line_with(digest(run), "Gone")
    assert viewer_url("v", "episodes", "e1") in line


# Phrase: "v1 | `entries`"
# Context: `digest` Viewer Link — Version-Aware Category.
def test_v1_digest_link_uses_entries_category(run, tmp_path):
    make_vault(tmp_path, "v", v1_catalog(entries=[updated_v1("e1")]))
    line = line_with(digest(run), "New")
    assert viewer_url("v", "entries", "e1") in line, line


# Phrase: "v2 | Category where entry resides (`episodes`, `streams`, or
#          `clips`)"
@pytest.mark.parametrize("category,eid", [("episodes", "e1"),
                                          ("streams", "s1"),
                                          ("clips", "c1")])
def test_v2_digest_link_uses_residing_category(run, tmp_path, category, eid):
    catalog = v2_catalog(**{category: [updated_v2(eid, second="Changed")]})
    make_vault(tmp_path, "v", catalog)
    line = line_with(digest(run), "Changed")
    assert viewer_url("v", category, eid) in line, line


# Phrase: "v3 | Category where entry resides (`episodes`, `streams`, or
#          `clips`)"
@pytest.mark.parametrize("category,eid", [("episodes", "e1"),
                                          ("streams", "s1"),
                                          ("clips", "c1")])
def test_v3_digest_link_uses_residing_category(run, tmp_path, category, eid):
    catalog = v3_catalog(**{category: [updated_v3(eid, second="Changed")]})
    make_vault(tmp_path, "v", catalog)
    line = line_with(digest(run), "Changed")
    assert viewer_url("v", category, eid) in line, line


# Phrase: "Category where entry resides"
# Context: entries in different categories get different links in one report.
def test_digest_links_differ_per_category(run, tmp_path):
    make_vault(tmp_path, "v", v3_catalog(
        episodes=[updated_v3("e1", second="EpTitle")],
        clips=[updated_v3("c1", second="ClipTitle")]))
    out = digest(run)
    assert viewer_url("v", "episodes", "e1") in line_with(out, "EpTitle")
    assert viewer_url("v", "clips", "c1") in line_with(out, "ClipTitle")


# Phrase: "Each changed-entry line includes viewer link on same line as title"
# Context: every reported entry line carries exactly one link.
def test_every_digest_entry_line_has_one_link(run, tmp_path):
    make_vault(tmp_path, "v", v3_catalog(
        episodes=[updated_v3("e1", second="A"), v3_entry("e2", title="B")],
        streams=[updated_v3("s1", second="C")]))
    out = digest(run)
    reported = changed_lines(out)
    assert len(reported) == 3, reported
    for line in reported:
        assert len(links_in(line)) == 1, line


# Phrase: "Each changed-entry line includes viewer link on same line as title"
# Context: the title still reads out; the link is additional, not a
# replacement.
def test_digest_line_keeps_the_title(run, tmp_path):
    make_vault(tmp_path, "v", v3_catalog(episodes=[updated_v3("e1")]))
    line = line_with(digest(run), "New")
    assert re.search(r"New\b", line.split("http://")[0]), line


# Phrase: "`digest <name>` | Each changed-entry line ..."
# Context: a digest with nothing to report has no entry lines and no links.
def test_digest_without_changes_has_no_links(run, tmp_path):
    make_vault(tmp_path, "v", v3_catalog())
    assert entry_links(digest(run)) == []


# --------------------------------------------------------------------------
# post-sync viewer links
# --------------------------------------------------------------------------

# Phrase: "Post-sync summary | Each changed-entry line includes viewer link on
#          same line as title"
def test_post_sync_summary_has_entry_lines_with_links(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1", title="Fresh")])
    out = sync(run)
    line = line_with(out, "Fresh")
    assert viewer_url("v", "episodes", "e1") in line, out


# Phrase: "Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`"
# Context: the post-sync link uses the same defaults as the digest link.
def test_post_sync_link_uses_defaults(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1")])
    found = links_in(sync(run))
    assert found
    for link in found:
        assert link.startswith("http://127.0.0.1:8840/catalog/v/"), link


# Phrase: "v2 vault after `sync` | Category where entry resides"
@pytest.mark.parametrize("category,eid", [("episodes", "e1"),
                                          ("streams", "s1"),
                                          ("clips", "c1")])
def test_post_sync_v2_link_uses_residing_category(run, source, tmp_path,
                                                  category, eid):
    make_vault(tmp_path, "v", v2_catalog(source=source.url))
    source.payload = payload(**{category: [entry(eid, title="Fresh")]})
    line = line_with(sync(run), "Fresh")
    assert viewer_url("v", category, eid) in line


# Phrase: "v3 vault after `sync` | Category where entry resides"
@pytest.mark.parametrize("category,eid", [("episodes", "e1"),
                                          ("streams", "s1"),
                                          ("clips", "c1")])
def test_post_sync_v3_link_uses_residing_category(run, source, tmp_path,
                                                  category, eid):
    make_vault(tmp_path, "v", v3_catalog(source=source.url))
    source.payload = payload(**{category: [entry(eid, title="Fresh")]})
    line = line_with(sync(run), "Fresh")
    assert viewer_url("v", category, eid) in line


# Phrase: "v1 vault after `sync` auto-migrates it to v3 | `episodes` for
#          migrated episode entries"
def test_post_sync_v1_link_uses_episodes_after_migration(run_inproc, tmp_path):
    make_vault(tmp_path, "v", v1_catalog(source_id="k",
                                         entries=[v1_entry("e1", title="old")]))
    url = V1_SOURCE_PREFIX + "k"
    result = run_inproc("sync", "v", "--skip-download",
                        responses={url: payload(episodes=[entry("e1", title="new")])})
    assert result.returncode == 0, result.stderr
    line = line_with(result.stdout, "new")
    assert viewer_url("v", "episodes", "e1") in line, result.stdout


# Phrase: "v1 vault after `sync` auto-migrates it to v3 | `episodes` ..."
# Context: an entry added by the sync itself also lands under `episodes`.
def test_post_sync_v1_addition_link_uses_episodes(run_inproc, tmp_path):
    make_vault(tmp_path, "v", v1_catalog(source_id="k", entries=[]))
    url = V1_SOURCE_PREFIX + "k"
    result = run_inproc("sync", "v", "--skip-download",
                        responses={url: payload(episodes=[entry("e2", title="brand")])})
    assert result.returncode == 0, result.stderr
    assert viewer_url("v", "episodes", "e2") in line_with(result.stdout, "brand")


# Phrase: "Post-sync summary | Each changed-entry line includes viewer link"
# Context: removals are changed-entry lines too.
def test_post_sync_removal_line_has_a_link(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1", title="Doomed")])
    sync(run)
    source.payload = payload()
    line = line_with(sync(run), "Doomed")
    assert viewer_url("v", "episodes", "e1") in line


# Phrase: "Post-sync summary | Each changed-entry line includes viewer link"
# Context: a field update is a changed-entry line.
def test_post_sync_update_line_has_a_link(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1", title="One")])
    sync(run)
    source.payload = payload(episodes=[entry("e1", title="Two")])
    line = line_with(sync(run), "Two")
    assert viewer_url("v", "episodes", "e1") in line


# Phrase: "Post-sync summary | Each changed-entry line ..."
# Context: a sync with nothing to report lists no entry lines.
def test_post_sync_without_changes_has_no_links(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1")])
    sync(run)
    assert links_in(sync(run)) == []


# Phrase: "Post-sync summary | Each changed-entry line ..."
# Context: the summary is still a summary; its counts line stays.
def test_post_sync_counts_line_still_printed(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1", title="Fresh")])
    out = sync(run)
    assert re.search(r"added\s+1", out), out


# Phrase: "Post-sync summary | Each changed-entry line includes viewer link on
#          same line as title"
# Context: only entries that changed in this run are listed.
def test_post_sync_lists_only_this_run_changes(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1", title="Kept"),
                                       entry("e2", title="Same")])
    sync(run)
    source.payload = payload(episodes=[entry("e1", title="Kept2"),
                                       entry("e2", title="Same")])
    out = sync(run)
    assert viewer_url("v", "episodes", "e1") in out
    assert viewer_url("v", "episodes", "e2") not in out


# Phrase: "Post-sync summary | ..." + "Trigger | Successful `sync` run that
#          includes metadata phase"
# Context: `--skip-metadata` prints no summary, so no links either.
def test_no_links_when_metadata_phase_is_skipped(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1")])
    sync(run)
    result = run("sync", "v", "--skip-metadata")
    assert result.returncode == 0, result.stderr
    assert links_in(result.stdout) == []


# Phrase: "Post-sync summary | Each changed-entry line ..."
# Context: the vault name in the link is the synced vault.
def test_post_sync_link_carries_the_vault_name(run, source, tmp_path):
    assert run("init", "mine", source.url).returncode == 0
    source.payload = payload(clips=[entry("c1", title="Clip")])
    line = line_with(sync(run, "mine"), "Clip")
    assert viewer_url("mine", "clips", "c1") in line


# Phrase: "`digest` and Post-Sync Viewer Links"
# Context: both surfaces produce the same link for the same entry.
def test_digest_and_post_sync_agree_on_the_link(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1", title="Fresh")])
    summary = sync(run)
    reported = digest(run)
    assert viewer_url("v", "episodes", "e1") in summary
    assert viewer_url("v", "episodes", "e1") in reported


# Phrase: "Each changed-entry line includes viewer link on same line as title"
# Context: the link is reachable -- it is the route the viewer serves.
def test_reported_link_path_matches_the_viewer_route(run, source, tmp_path,
                                                     viewer):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1", title="Fresh")])
    link = links_in(sync(run))[0]
    path = "/" + link.split("/", 3)[3]
    page = viewer().browser().get(path)
    assert page.status == 200, (path, page.status)
    assert "Fresh" in page.body
