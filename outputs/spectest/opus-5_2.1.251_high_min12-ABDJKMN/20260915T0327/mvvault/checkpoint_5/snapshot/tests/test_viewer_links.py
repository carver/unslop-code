"""Spec sections: `digest` and Post-Sync Viewer Links, `digest` Viewer Link --
Version-Aware Category, Post-Sync Viewer Link -- Version-Aware Category, and
the Determinism rows for the default scheme, host, and port."""
import socket

import pytest

from conftest import (
    DEFAULT_VIEWER_HOST,
    DEFAULT_VIEWER_PORT,
    entry,
    lines,
    payload,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    viewer_link,
    write_vault,
)

T1 = "2024-01-01T00:00:00"
T2 = "2024-02-01T00:00:00"


def line_with(text, needle):
    """The single output line that mentions `needle`."""
    found = [ln for ln in lines(text) if needle in ln]
    assert len(found) == 1, (needle, text)
    return found[0]


def entry_line(text, title):
    """The changed-entry line for `title`, which must carry its own link."""
    return line_with(text, title)


def digest_of(run, tmp_path, catalog, name="vault"):
    write_vault(tmp_path, catalog, name)
    result = run("digest", name)
    assert result.returncode == 0, result
    return result.stdout


def legacy_host_reachable():
    try:
        socket.getaddrinfo("media.example.com", 443)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# `digest` viewer links
# ---------------------------------------------------------------------------

# --- Phrase: "| `digest <name>` | Each changed-entry line includes viewer
#     link on same line as title |"
def test_digest_line_carries_the_viewer_link_beside_the_title(run, tmp_path):
    out = digest_of(run, tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    line = entry_line(out, "Title e1")
    assert viewer_link("vault", "episodes", "e1") in line, out


def test_every_changed_entry_line_carries_a_link(run, tmp_path):
    catalog = v3_catalog(episodes=[
        v3_entry("fresh"),
        v3_entry("changed", title={T1: "Old", T2: "Title changed"}),
        v3_entry("gone", removed={T1: False, T2: True}),
    ])
    out = digest_of(run, tmp_path, catalog)
    for eid in ("fresh", "changed", "gone"):
        line = entry_line(out, "Title %s" % eid)
        assert viewer_link("vault", "episodes", eid) in line, out


# --- Phrase: "| Link format | `http://<host>:<port>/catalog/<name>/<category>
#     /<id>` |" + "| Default scheme | `http://` |" + "| Default host |
#     `127.0.0.1` |" + "| Default port | `8840` |"
def test_link_uses_the_default_scheme_host_and_port(run, tmp_path):
    out = digest_of(run, tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    line = entry_line(out, "Title e1")
    assert "http://%s:%d/" % (DEFAULT_VIEWER_HOST, DEFAULT_VIEWER_PORT) in line
    assert "https://" not in line, out


def test_link_names_the_vault_it_was_generated_for(run, tmp_path):
    out = digest_of(run, tmp_path, v3_catalog(episodes=[v3_entry("e1")]),
                    name="other-vault")
    assert viewer_link("other-vault", "episodes", "e1") in out, out


# --- Phrase: "| v1 | `entries` |" (digest viewer link category)
def test_v1_digest_links_use_the_entries_category(run, tmp_path):
    out = digest_of(run, tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    line = entry_line(out, "Title e1")
    assert viewer_link("vault", "entries", "e1") in line, out


# --- Phrase: "| v2 | Category where entry resides (`episodes`, `streams`, or
#     `clips`) |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_digest_links_use_the_entry_category(run, tmp_path, category):
    out = digest_of(run, tmp_path,
                    v2_catalog(**{category: [v2_entry("x1")]}))
    line = entry_line(out, "Title x1")
    assert viewer_link("vault", category, "x1") in line, out


# --- Phrase: "| v3 | Category where entry resides (`episodes`, `streams`, or
#     `clips`) |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_digest_links_use_the_entry_category(run, tmp_path, category):
    out = digest_of(run, tmp_path,
                    v3_catalog(**{category: [v3_entry("x1")]}))
    line = entry_line(out, "Title x1")
    assert viewer_link("vault", category, "x1") in line, out


def test_v3_digest_links_distinguish_entries_across_categories(run, tmp_path):
    catalog = v3_catalog(episodes=[v3_entry("a")], streams=[v3_entry("b")],
                         clips=[v3_entry("c")])
    out = digest_of(run, tmp_path, catalog)
    assert viewer_link("vault", "episodes", "a") in out, out
    assert viewer_link("vault", "streams", "b") in out, out
    assert viewer_link("vault", "clips", "c") in out, out


# --- Phrase: "| Current title | Latest value ... |" (context: the link sits
#     on the title's line, so the title is still the current one)
def test_link_line_still_shows_the_current_title(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", title={T1: "Stale name", T2: "Current name"})]
    )
    out = digest_of(run, tmp_path, catalog)
    line = entry_line(out, "Current name")
    assert viewer_link("vault", "episodes", "e1") in line, out
    assert "Stale name" not in out, out


# ---------------------------------------------------------------------------
# Post-sync viewer links
# ---------------------------------------------------------------------------

# --- Phrase: "| Post-sync summary | Each changed-entry line includes viewer
#     link on same line as title |"
def test_post_sync_addition_line_carries_the_viewer_link(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", "--skip-download")
    assert result.returncode == 0, result
    line = entry_line(result.stdout, "Title e1")
    assert viewer_link("vault", "episodes", "e1") in line, result


def test_post_sync_update_line_carries_the_viewer_link(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1", views=1)]))
    run("sync", "vault", "--skip-download")
    source.set_payload(payload(episodes=[entry("e1", views=2)]))
    result = run("sync", "vault", "--skip-download")
    line = entry_line(result.stdout, "Title e1")
    assert viewer_link("vault", "episodes", "e1") in line, result


def test_post_sync_removal_line_carries_the_viewer_link(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    source.set_payload(payload())
    result = run("sync", "vault", "--skip-download")
    line = entry_line(result.stdout, "Title e1")
    assert viewer_link("vault", "episodes", "e1") in line, result


# --- Phrase: "| Default host | `127.0.0.1` |" + "| Default port | `8840` |"
#     (post-sync surface)
def test_post_sync_link_uses_the_documented_defaults(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", "--skip-download")
    line = entry_line(result.stdout, "Title e1")
    assert "http://%s:%d/catalog/" % (DEFAULT_VIEWER_HOST,
                                      DEFAULT_VIEWER_PORT) in line, result


# --- Phrase: "| v3 vault after `sync` | Category where entry resides
#     (`episodes`, `streams`, or `clips`) |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_post_sync_v3_links_use_the_entry_category(run, source, vault,
                                                   category):
    source.set_payload(payload(**{category: [entry("x1")]}))
    result = run("sync", "vault", "--skip-download")
    line = entry_line(result.stdout, "Title x1")
    assert viewer_link("vault", category, "x1") in line, result


def test_post_sync_links_separate_entries_by_category(run, source, vault):
    source.set_payload(payload(episodes=[entry("a")], streams=[entry("b")],
                               clips=[entry("c")]))
    result = run("sync", "vault", "--skip-download")
    assert viewer_link("vault", "episodes", "a") in result.stdout, result
    assert viewer_link("vault", "streams", "b") in result.stdout, result
    assert viewer_link("vault", "clips", "c") in result.stdout, result


# --- Phrase: "| v2 vault after `sync` | Category where entry resides
#     (`episodes`, `streams`, or `clips`) |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_post_sync_v2_links_use_the_entry_category(run, source, tmp_path,
                                                   category):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     **{category: [v2_entry("x1")]}))
    source.set_payload(payload(**{category: [entry("x1", title="Renamed")]}))
    result = run("sync", "vault", "--skip-download")
    assert result.returncode == 0, result
    line = entry_line(result.stdout, "Renamed")
    assert viewer_link("vault", category, "x1") in line, result


# --- Phrase: "| v1 vault after `sync` auto-migrates it to v3 | `episodes` for
#     migrated episode entries |"
@pytest.mark.skipif(not legacy_host_reachable(),
                    reason="the derived v1 source host is not resolvable here")
def test_post_sync_v1_links_use_the_episodes_category(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    result = run("sync", "vault", "--skip-download")
    assert result.returncode == 0, result
    line = entry_line(result.stdout, "Title e1")
    assert viewer_link("vault", "episodes", "e1") in line, result


# --- Phrase: "| Post-sync summary | Each changed-entry line ... |" (context:
#     a run with nothing to report still summarizes, and links nothing)
def test_unchanged_resync_reports_no_entry_links(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    result = run("sync", "vault", "--skip-download")
    assert "/catalog/" not in result.stdout, result


# --- Phrase: "| Post-sync summary | ... |" (context: `--skip-metadata` runs
#     no metadata phase, so there is no summary to link from)
def test_skip_metadata_run_reports_no_links(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    result = run("sync", "vault", "--skip-metadata")
    assert "/catalog/" not in result.stdout, result


# --- Phrase: "| Link format | `http://<host>:<port>/catalog/<name>/<category>
#     /<id>` |" (context: the report link is exactly the viewer's own route)
def test_report_link_matches_the_viewer_entry_route(run, tmp_path, viewer):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    out = run("digest", "vault").stdout
    link = viewer_link("vault", "episodes", "e1")
    assert link in out, out
    path = link.split("%d" % DEFAULT_VIEWER_PORT, 1)[1]
    assert viewer().get(path).status == 200
