"""Spec sections: `serve` Command / `/` Routes / `/` Recent Vaults /
`/catalog` Routes / Version-Aware Default Category Redirect / Version-Aware
Valid Categories / Listing Rules / HTTP Error Handling / `serve` Required
Public Surface / Determinism (viewer)."""
import os
import re

import pytest
from conftest import (DEFAULT_VIEWER_PORT, free_port, make_vault, opened_urls,
                      place_file, read_catalog, v1_entry, v2_entry, v3_entry,
                      write_raw)

REDIRECTS = (302, 303)

T1 = "2024-01-01T00:00:00"
T2 = "2024-02-01T00:00:00"

# Numeric and lexicographic order disagree for this pair: numerically
# 1000000000 > 999999999, lexicographically "999999999" > "1000000000".
E_OLD = "999999999"
E_NEW = "1000000000"


# --------------------------------------------------------------------------
# vault fixtures
# --------------------------------------------------------------------------

def v1_vault(tmp_path, entries=(), name="v", source_id="chan42"):
    return make_vault(tmp_path, name, {"version": 1, "source_id": source_id,
                                       "entries": list(entries)})


def v2_vault(tmp_path, episodes=(), streams=(), clips=(), name="v"):
    return make_vault(tmp_path, name,
                      {"version": 2, "source": "http://example.invalid/f.json",
                       "episodes": list(episodes), "streams": list(streams),
                       "clips": list(clips)})


def v3_vault(tmp_path, episodes=(), streams=(), clips=(), name="v"):
    return make_vault(tmp_path, name,
                      {"version": 3, "source": "http://example.invalid/f.json",
                       "episodes": list(episodes), "streams": list(streams),
                       "clips": list(clips)})


def body_of(browser, path):
    page = browser.get(path)
    assert page.status == 200, (path, page.status)
    return page.body


def entry_href(name, category, eid):
    return "/catalog/%s/%s/%s" % (name, category, eid)


def has_link(page, href):
    return any(link.split("?")[0].rstrip("/") == href for link in page.links())


def unescape(text):
    return (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"')
                .replace("&#39;", "'"))


def visible_order(body, titles):
    """Index of each title in the page body; -1 when absent."""
    plain = unescape(body)
    return [plain.find(title) for title in titles]


# --------------------------------------------------------------------------
# `serve` Command
# --------------------------------------------------------------------------

# Phrase: "CLI `serve` command | Required"
# Context: `serve` Required Public Surface.
def test_serve_is_a_documented_subcommand(run):
    result = run("--help")
    assert result.returncode == 0
    assert "serve" in result.stdout


# Phrase: "Syntax | `python mvault.py serve [<name>] [--host=<host>]
#          [--port=<port>]`"
# Context: every argument is optional.
def test_serve_accepts_no_arguments(viewer, tmp_path):
    v3_vault(tmp_path)
    server = viewer()
    assert server.browser().get("/").status == 200


# Phrase: "Default bind address | `127.0.0.1:8840`"
def test_default_bind_address_is_127_0_0_1_8840(viewer, tmp_path):
    v3_vault(tmp_path)
    try:
        server = viewer(defaults=True)
    except AssertionError as exc:            # port already taken on this box
        pytest.skip("port %d unavailable: %s" % (DEFAULT_VIEWER_PORT, exc))
    assert server.port == DEFAULT_VIEWER_PORT
    assert server.browser().get("/").status == 200


# Phrase: "`serve` without `<name>` | Start server and open browser to `/`"
def test_serve_without_name_opens_root(viewer, tmp_path):
    v3_vault(tmp_path)
    log = tmp_path / "opened.txt"
    server = viewer(browser_log=log)
    urls = wait_for_browser(log)
    assert urls, "no browser launch recorded"
    assert urls[0] == "%s/" % server.base or urls[0] == server.base + "/"


# Phrase: "`serve <name>` | Start server and open browser to default category
#          page for vault"
# Context: a v3 vault's default category is `episodes`.
def test_serve_with_name_opens_default_category_page(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    log = tmp_path / "opened.txt"
    server = viewer("v", browser_log=log)
    urls = wait_for_browser(log)
    assert urls[0] == "%s/catalog/v/episodes" % server.base


# Phrase: "`serve <name>` | ... default category page for vault"
# Context: a v1 vault's default category is `entries`.
def test_serve_with_v1_name_opens_entries_page(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    log = tmp_path / "opened.txt"
    server = viewer("v", browser_log=log)
    urls = wait_for_browser(log)
    assert urls[0] == "%s/catalog/v/entries" % server.base


# Phrase: "`--host=<host>` | Override bind host; the browser URL uses this host
#          as given"
def test_host_override_is_used_verbatim_in_browser_url(viewer, tmp_path):
    v3_vault(tmp_path)
    log = tmp_path / "opened.txt"
    port = free_port()
    server = viewer("--host=localhost", "--port=%d" % port,
                    host="localhost", port=port, browser_log=log)
    urls = wait_for_browser(log)
    assert urls[0].startswith("http://localhost:%d/" % port), urls
    assert server.browser().get("/").status == 200


# Phrase: "`--port=<port>` | Override bind port"
def test_port_override_binds_that_port(viewer, tmp_path):
    v3_vault(tmp_path)
    port = free_port()
    server = viewer("--port=%d" % port, port=port)
    assert server.port == port
    assert server.browser().get("/").status == 200


def wait_for_browser(log, timeout=15.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        urls = opened_urls(log)
        if urls:
            return urls
        time.sleep(0.05)
    return opened_urls(log)


# --------------------------------------------------------------------------
# `/` Routes
# --------------------------------------------------------------------------

# Phrase: "`GET` | `/` | HTML page containing a form input for vault name"
def test_root_is_html_with_a_form_input(viewer, tmp_path):
    server = viewer()
    page = server.browser().get("/")
    assert page.status == 200
    assert "<form" in page.body.lower()
    assert "<input" in page.body.lower()
    assert re.search(r'name\s*=\s*"catalog"', page.body), page.body


# Phrase: "`GET` | `/` | HTML page ..."
# Context: the response announces itself as HTML.
def test_root_declares_html_content_type(viewer, tmp_path):
    page = viewer().browser().get("/")
    assert "text/html" in (page.header("Content-Type") or "")


# Phrase: "`POST` | `/` | Accept form-encoded body; redirect to
#          `/catalog/<value>` when `catalog` field is present"
def test_post_root_redirects_to_catalog_of_value(viewer, tmp_path):
    v3_vault(tmp_path)
    page = viewer().browser().post("/", {"catalog": "v"})
    assert page.status in REDIRECTS, page.status
    assert page.location.split("?")[0].rstrip("/").endswith("/catalog/v")


# Phrase: "... redirect to `/catalog/<value>` ..."
# Context: the value names a vault that does not exist; the POST still routes
# to `/catalog/<value>`, which then handles the missing vault.
def test_post_root_redirects_even_for_unknown_vault(viewer, tmp_path):
    page = viewer().browser().post("/", {"catalog": "nope"})
    assert page.status in REDIRECTS
    assert page.location.split("?")[0].rstrip("/").endswith("/catalog/nope")


# Phrase: "... otherwise redirect to `/`" + "Missing `catalog` field on
#          `POST /` | Redirect to `/`"
def test_post_root_without_catalog_field_redirects_to_root(viewer, tmp_path):
    page = viewer().browser().post("/", {"other": "x"})
    assert page.status in REDIRECTS
    assert page.location.split("?")[0] in ("/", "")


# Phrase: "Accept form-encoded body"
# Context: an empty body is still accepted, not an error.
def test_post_root_with_empty_body_is_accepted(viewer, tmp_path):
    page = viewer().browser().post("/", raw="")
    assert page.status in REDIRECTS
    assert page.status != 500


# --------------------------------------------------------------------------
# `/catalog` Routes + Version-Aware Default Category Redirect
# --------------------------------------------------------------------------

# Phrase: "`GET` | `/catalog/<name>` | Redirect to default category page for
#          vault" + "v1 | `/catalog/<name>/entries`"
def test_v1_catalog_redirects_to_entries(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    page = viewer().browser().get("/catalog/v")
    assert page.status in REDIRECTS, page.status
    assert page.location.endswith("/catalog/v/entries"), page.location


# Phrase: "v2 | `/catalog/<name>/episodes`"
def test_v2_catalog_redirects_to_episodes(viewer, tmp_path):
    v2_vault(tmp_path, episodes=[v2_entry("e1")])
    page = viewer().browser().get("/catalog/v")
    assert page.status in REDIRECTS
    assert page.location.endswith("/catalog/v/episodes"), page.location


# Phrase: "v3 | `/catalog/<name>/episodes`"
def test_v3_catalog_redirects_to_episodes(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get("/catalog/v")
    assert page.status in REDIRECTS
    assert page.location.endswith("/catalog/v/episodes"), page.location


# Phrase: "Redirect status | HTTP `302` or `303`"
def test_catalog_redirect_status_is_302_or_303(viewer, tmp_path):
    v3_vault(tmp_path)
    assert viewer().browser().get("/catalog/v").status in REDIRECTS


# Phrase: "`GET` | `/catalog/<name>/<category>` | HTML listing for category"
def test_category_listing_is_html(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", title="Alpha")])
    page = viewer().browser().get("/catalog/v/episodes")
    assert page.status == 200
    assert "text/html" in (page.header("Content-Type") or "")
    assert "Alpha" in unescape(page.body)


# Phrase: "`GET` | `/catalog/<name>/<category>/<id>` | HTML response for that
#          viewer link target"
def test_entry_route_returns_html(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", title="Alpha")])
    page = viewer().browser().get("/catalog/v/episodes/e1")
    assert page.status == 200
    assert "text/html" in (page.header("Content-Type") or "")


# Phrase: "may reuse the category listing page with the entry highlighted or
#          otherwise surfaced"
# Context: whatever form it takes, the target entry is present on the page.
def test_entry_route_surfaces_the_entry(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", title="Alpha"),
                                 v3_entry("e2", title="Beta")])
    page = viewer().browser().get("/catalog/v/episodes/e2")
    assert "Beta" in unescape(page.body)


# Phrase: "`GET` | `/catalog/<name>/<category>/<id>`"
# Context: v1 vaults expose their entries under `entries`.
def test_v1_entry_route_returns_html(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1", title="Solo")])
    page = viewer().browser().get("/catalog/v/entries/e1")
    assert page.status == 200
    assert "Solo" in unescape(page.body)


# --------------------------------------------------------------------------
# Version-Aware Valid Categories
# --------------------------------------------------------------------------

# Phrase: "v2 | `episodes`, `streams`, `clips`"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_categories_all_listed(viewer, tmp_path, category):
    v2_vault(tmp_path, episodes=[v2_entry("e1")], streams=[v2_entry("s1")],
             clips=[v2_entry("c1")])
    page = viewer().browser().get("/catalog/v/%s" % category)
    assert page.status == 200, (category, page.status)


# Phrase: "v3 | `episodes`, `streams`, `clips`"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_categories_all_listed(viewer, tmp_path, category):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], streams=[v3_entry("s1")],
             clips=[v3_entry("c1")])
    page = viewer().browser().get("/catalog/v/%s" % category)
    assert page.status == 200, (category, page.status)


# Phrase: "v1 | `entries`"
def test_v1_entries_category_is_valid(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1", title="Solo")])
    page = viewer().browser().get("/catalog/v/entries")
    assert page.status == 200
    assert "Solo" in unescape(page.body)


# Phrase: "v1 | `entries`"
# Context: the v2/v3 category names are not valid for a v1 vault.
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v1_rejects_v3_category_names(viewer, tmp_path, category):
    v1_vault(tmp_path, [v1_entry("e1")])
    page = viewer().browser().get("/catalog/v/%s" % category)
    assert page.status in (400, 404) or (
        page.status in REDIRECTS and page.location.endswith("/catalog/v/entries")
    ), (page.status, page.location)


# Phrase: "v2 | `episodes`, `streams`, `clips`"
# Context: `entries` is not a v2/v3 category.
def test_v3_rejects_entries_category(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get("/catalog/v/entries")
    assert page.status in (400, 404) or (
        page.status in REDIRECTS and page.location.endswith("/catalog/v/episodes")
    ), (page.status, page.location)


# --------------------------------------------------------------------------
# Listing Rules
# --------------------------------------------------------------------------

# Phrase: "Category matching | Case-sensitive"
def test_category_matching_is_case_sensitive(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get("/catalog/v/Episodes")
    assert page.status in (400, 404) or (
        page.status in REDIRECTS and page.location.endswith("/catalog/v/episodes")
    ), (page.status, page.location)


# Phrase: "Entry order | Same order as category array in `catalog.json`"
# Context: the stored order is deliberately not sorted by id or published.
def test_listing_follows_catalog_array_order(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[
        v3_entry("z9", title="Zulu", published="2020-01-01T00:00:00"),
        v3_entry("a1", title="Alfa", published="2024-01-01T00:00:00"),
        v3_entry("m5", title="Mike", published="2022-01-01T00:00:00"),
    ])
    body = body_of(viewer().browser(), "/catalog/v/episodes")
    positions = visible_order(body, ["Zulu", "Alfa", "Mike"])
    assert -1 not in positions, body
    assert positions == sorted(positions), positions


# Phrase: "Listing order | Matches category-array order in `catalog.json`"
# Context: Determinism; the same vault renders the same order every time.
def test_listing_order_is_stable_across_requests(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("b"), v3_entry("a"), v3_entry("c")])
    browser = viewer().browser()
    first = body_of(browser, "/catalog/v/episodes")
    second = body_of(browser, "/catalog/v/episodes")
    assert first == second


# Phrase: "Entry order | Same order as category array"
# Context: v1 entries come from the `entries` array.
def test_v1_listing_follows_entries_array_order(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e2", title="Second"),
                        v1_entry("e1", title="First")])
    body = body_of(viewer().browser(), "/catalog/v/entries")
    positions = visible_order(body, ["Second", "First"])
    assert -1 not in positions
    assert positions[0] < positions[1]


# Phrase: "Current title | Latest value from `title` history, resolved using
#          the vault version's key format" + "v2/v3 title resolution | Latest
#          by lexicographic comparison of ISO 8601 string keys"
def test_v3_title_is_latest_iso_key(viewer, tmp_path):
    item = v3_entry("e1")
    item["title"] = {T1: "Old Title", T2: "New Title"}
    v3_vault(tmp_path, episodes=[item])
    body = unescape(body_of(viewer().browser(), "/catalog/v/episodes"))
    assert "New Title" in body
    assert "Old Title" not in body


# Phrase: "v1 title resolution | Latest by numeric comparison of UNIX-epoch
#          string keys"
# Context: lexicographic order would pick the wrong one here.
def test_v1_title_is_latest_by_numeric_epoch(viewer, tmp_path):
    item = v1_entry("e1")
    item["title"] = {E_OLD: "Lexicographically Last", E_NEW: "Numerically Last"}
    v1_vault(tmp_path, [item])
    body = unescape(body_of(viewer().browser(), "/catalog/v/entries"))
    assert "Numerically Last" in body
    assert "Lexicographically Last" not in body


# Phrase: "v2/v3 title resolution | Latest by lexicographic comparison of ISO
#          8601 string keys"
# Context: a v2 vault resolves the same way a v3 vault does.
def test_v2_title_is_latest_iso_key(viewer, tmp_path):
    item = v2_entry("e1")
    item["title"] = {T1: "Stale", T2: "Fresh"}
    v2_vault(tmp_path, episodes=[item])
    body = unescape(body_of(viewer().browser(), "/catalog/v/episodes"))
    assert "Fresh" in body
    assert "Stale" not in body


# Phrase: "Downloaded state (v2/v3) | Entry counts as downloaded when a media
#          filename in `<vault>/media/` contains entry `id`" + "Visual
#          distinction | Downloaded and undownloaded states must be
#          distinguishable"
def test_downloaded_and_undownloaded_entries_differ(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1", title="Got It"),
                                         v3_entry("e2", title="Missing")])
    place_file(vault, "media", "e1.mp4")
    body = body_of(viewer().browser(), "/catalog/v/episodes")
    assert rendering(body, "Got It", "e1") != rendering(body, "Missing", "e2"), body


# Phrase: "Entry counts as downloaded when a media filename ... contains entry
#          `id`"
# Context: containment, not an exact name match.
def test_downloaded_matches_filename_containing_id(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1", title="Got It"),
                                         v3_entry("e2", title="Missing")])
    place_file(vault, "media", "prefix-e1-suffix.mp4")
    body = body_of(viewer().browser(), "/catalog/v/episodes")
    assert marked_downloaded(body, "Got It")
    assert not marked_downloaded(body, "Missing")


# Phrase: "Downloaded state (v1) | Same rule as v2/v3"
def test_v1_downloaded_state_uses_the_same_rule(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1", title="Got It"),
                                v1_entry("e2", title="Missing")])
    place_file(vault, "media", "e1.mp4")
    body = body_of(viewer().browser(), "/catalog/v/entries")
    assert marked_downloaded(body, "Got It")
    assert not marked_downloaded(body, "Missing")


# Phrase: "Downloaded state ... in `<vault>/media/`"
# Context: a vault with no media directory lists everything as undownloaded.
def test_missing_media_directory_lists_nothing_as_downloaded(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", title="Alpha")])
    body = body_of(viewer().browser(), "/catalog/v/episodes")
    assert not marked_downloaded(body, "Alpha")


# Phrase: "Downloaded state ... `<vault>/media/`"
# Context: a preview file is not a media file.
def test_preview_file_does_not_mark_entry_downloaded(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1", title="Alpha")])
    place_file(vault, "previews", "e1.png")
    body = body_of(viewer().browser(), "/catalog/v/episodes")
    assert not marked_downloaded(body, "Alpha")


# Phrase: "Removed indicator (v3 only) | Entries with latest `removed` value
#          `true` are visually distinct from active entries"
def test_removed_entries_are_visually_distinct(viewer, tmp_path):
    gone = v3_entry("e1", title="Gone")
    gone["removed"] = {T1: False, T2: True}
    v3_vault(tmp_path, episodes=[gone, v3_entry("e2", title="Here")])
    body = body_of(viewer().browser(), "/catalog/v/episodes")
    assert rendering(body, "Gone", "e1") != rendering(body, "Here", "e2"), body


# Phrase: "Entries with latest `removed` value `true`"
# Context: an entry whose latest value is `false` is an active entry.
def test_reappeared_entry_is_not_marked_removed(viewer, tmp_path):
    back = v3_entry("e1", title="Back")
    back["removed"] = {T1: True, T2: False}
    v3_vault(tmp_path, episodes=[back, v3_entry("e2", title="Here")])
    body = body_of(viewer().browser(), "/catalog/v/episodes")
    assert rendering(body, "Back", "e1") == rendering(body, "Here", "e2"), body


# Phrase: "Removed indicator (v1/v2) | Not applicable; no `removed` field
#          exists"
def test_v2_listing_renders_without_removed_state(viewer, tmp_path):
    v2_vault(tmp_path, episodes=[v2_entry("e1", title="Alpha"),
                                 v2_entry("e2", title="Beta")])
    body = body_of(viewer().browser(), "/catalog/v/episodes")
    assert rendering(body, "Alpha", "e1") == rendering(body, "Beta", "e2"), body


# Phrase: "Entry navigation | Each listed entry includes a link to
#          `/catalog/<name>/<category>/<id>`"
def test_each_entry_links_to_its_entry_route(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")],
             streams=[v3_entry("s1")])
    page = viewer().browser().get("/catalog/v/episodes")
    assert has_link(page, entry_href("v", "episodes", "e1")), page.links()
    assert has_link(page, entry_href("v", "episodes", "e2")), page.links()


# Phrase: "Each listed entry includes a link to `/catalog/<name>/<category>/<id>`"
# Context: the link carries the category actually being listed.
def test_entry_links_use_the_listed_category(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], clips=[v3_entry("c1")])
    page = viewer().browser().get("/catalog/v/clips")
    assert has_link(page, entry_href("v", "clips", "c1")), page.links()


# Phrase: "Each listed entry includes a link ..."
# Context: v1 links use the `entries` category.
def test_v1_entry_links_use_entries_category(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    page = viewer().browser().get("/catalog/v/entries")
    assert has_link(page, entry_href("v", "entries", "e1")), page.links()


# Phrase: "HTML listing for category"
# Context: an empty category still renders a page rather than failing.
def test_empty_category_still_renders(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get("/catalog/v/clips")
    assert page.status == 200


# Phrase: "The viewer works on vaults of any supported version without
#          requiring prior migration."
def test_viewing_a_v1_vault_does_not_migrate_it(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    browser = viewer().browser()
    browser.get("/catalog/v")
    browser.get("/catalog/v/entries")
    browser.get("/catalog/v/entries/e1")
    assert read_catalog(vault)["version"] == 1
    assert not os.path.exists(os.path.join(str(vault), "catalog.bak"))


# Phrase: "works on vaults of any supported version"
# Context: a v2 vault is viewable as stored.
def test_viewing_a_v2_vault_does_not_migrate_it(viewer, tmp_path):
    vault = v2_vault(tmp_path, episodes=[v2_entry("e1")])
    viewer().browser().get("/catalog/v/episodes")
    assert read_catalog(vault)["version"] == 2


def line_for(body, title):
    """The rendered line (list item) carrying `title`."""
    plain = unescape(body)
    for chunk in re.split(r"<li[^>]*>|</li>|\n", plain):
        if title in chunk:
            return chunk.strip()
    return None


def rendering(body, title, eid):
    """One entry's rendered line with its title and id neutralized.

    Two entries that differ only in state therefore render differently only
    when the viewer actually distinguishes that state -- by marker text, by
    class, or by any other markup.
    """
    line = line_for(body, title)
    assert line is not None, "no rendered line for %r in %r" % (title, body)
    return " ".join(line.replace(title, "@T").replace(eid, "@I").split())


def marked_downloaded(body, title):
    """Whether the rendered entry for `title` reads as downloaded."""
    line = line_for(body, title)
    assert line is not None, "no rendered line for %r in %r" % (title, body)
    lowered = line.lower()
    if "not downloaded" in lowered or "undownloaded" in lowered:
        return False
    return "downloaded" in lowered


# --------------------------------------------------------------------------
# `/` Recent Vaults
# --------------------------------------------------------------------------

# Phrase: "Trigger | Navigation to any vault through viewer" +
#         "Display location | Landing page"
def test_visited_vault_appears_on_landing_page(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], name="alpha")
    browser = viewer().browser()
    browser.get("/catalog/alpha/episodes")
    page = browser.get("/")
    assert "alpha" in page.body


# Phrase: "Trigger | Navigation to any vault through viewer"
# Context: the `/catalog/<name>` redirect is itself a navigation.
def test_redirect_route_records_the_visit(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], name="alpha")
    browser = viewer().browser()
    browser.get("/catalog/alpha")
    assert "alpha" in browser.get("/").body


# Phrase: "Trigger | Navigation to any vault through viewer"
# Context: an entry page is a navigation too.
def test_entry_route_records_the_visit(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], name="alpha")
    browser = viewer().browser()
    browser.get("/catalog/alpha/episodes/e1")
    assert "alpha" in browser.get("/").body


# Phrase: "Ordering | Most recently visited first"
def test_recent_vaults_are_most_recent_first(viewer, tmp_path):
    for name in ("alpha", "beta", "gamma"):
        v3_vault(tmp_path, episodes=[v3_entry("e1")], name=name)
    browser = viewer().browser()
    for name in ("alpha", "beta", "gamma"):
        browser.get("/catalog/%s/episodes" % name)
    body = browser.get("/").body
    positions = [body.find("/catalog/%s/" % n) for n in ("gamma", "beta", "alpha")]
    assert -1 not in positions, body
    assert positions == sorted(positions), positions


# Phrase: "Ordering | Most recently visited first"
# Context: revisiting a vault moves it back to the front.
def test_revisit_moves_vault_to_the_front(viewer, tmp_path):
    for name in ("alpha", "beta"):
        v3_vault(tmp_path, episodes=[v3_entry("e1")], name=name)
    browser = viewer().browser()
    browser.get("/catalog/alpha/episodes")
    browser.get("/catalog/beta/episodes")
    browser.get("/catalog/alpha/episodes")
    body = browser.get("/").body
    assert body.find("/catalog/alpha/") < body.find("/catalog/beta/"), body


# Phrase: "Persistence | Later browser session from same browser must still
#          show visited vault"
def test_recent_vaults_survive_a_later_browser_session(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], name="alpha")
    server = viewer()
    browser = server.browser()
    browser.get("/catalog/alpha/episodes")
    later = browser.clone()               # same stored cookies, new session
    assert "alpha" in later.get("/").body


# Phrase: "Persistence | Later browser session from same browser must still
#          show visited vault"
# Context: the server is restarted between sessions.
def test_recent_vaults_survive_a_server_restart(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], name="alpha")
    first = viewer()
    browser = first.browser()
    browser.get("/catalog/alpha/episodes")
    cookies = dict(browser.cookies)
    first.stop()

    second = viewer(port=first.port)
    later = second.browser()
    later.cookies.update(cookies)
    assert "alpha" in later.get("/").body


# Phrase: "Link target | Each recent-vault link points directly to that
#          vault's resolved default category page" + "Recent-vault links on
#          `/` | Use the same resolved default-category route as
#          `/catalog/<name>` would redirect to"
def test_recent_link_points_at_v3_default_category(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], name="alpha")
    browser = viewer().browser()
    redirect = browser.get("/catalog/alpha")
    target = redirect.location
    page = browser.get("/")
    assert any(link.endswith("/catalog/alpha/episodes") for link in page.links()), \
        page.links()
    assert target.endswith("/catalog/alpha/episodes")


# Phrase: "Each recent-vault link points directly to that vault's resolved
#          default category page"
# Context: a v1 vault resolves to `entries`.
def test_recent_link_points_at_v1_default_category(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")], name="legacy")
    browser = viewer().browser()
    browser.get("/catalog/legacy")
    page = browser.get("/")
    assert any(link.endswith("/catalog/legacy/entries") for link in page.links()), \
        page.links()


# Phrase: "Empty state | Area may be empty or absent"
def test_landing_page_without_history_is_fine(viewer, tmp_path):
    page = viewer().browser().get("/")
    assert page.status == 200


# Phrase: "Trigger | Navigation to any vault through viewer"
# Context: a vault that does not exist was never visited.
def test_unknown_vault_is_not_recorded_as_recent(viewer, tmp_path):
    browser = viewer().browser()
    browser.get("/catalog/ghost")
    page = browser.get("/")
    assert "/catalog/ghost" not in page.body


# --------------------------------------------------------------------------
# HTTP Error Handling
# --------------------------------------------------------------------------

# Phrase: "Invalid category on `GET /catalog/<name>/<category>` for v1 vault |
#          Redirect to `/catalog/<name>/entries` or return HTTP `400`/`404`"
def test_invalid_category_for_v1_vault(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    page = viewer().browser().get("/catalog/v/nonsense")
    assert page.status in (400, 404) or (
        page.status in REDIRECTS and page.location.endswith("/catalog/v/entries")
    ), (page.status, page.location)


# Phrase: "Invalid category on `GET /catalog/<name>/<category>` for v2/v3 vault
#          | Redirect to `/catalog/<name>/episodes` or return HTTP `400`/`404`"
@pytest.mark.parametrize("version", [2, 3])
def test_invalid_category_for_v2_v3_vault(viewer, tmp_path, version):
    if version == 2:
        v2_vault(tmp_path, episodes=[v2_entry("e1")])
    else:
        v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get("/catalog/v/nonsense")
    assert page.status in (400, 404) or (
        page.status in REDIRECTS and page.location.endswith("/catalog/v/episodes")
    ), (page.status, page.location)


# Phrase: "Non-existent vault on any `/catalog/<name>` route | Redirect to `/`;
#          landing page shows vault-not-found indication; response must not be
#          HTTP `500`"
@pytest.mark.parametrize("path", ["/catalog/ghost", "/catalog/ghost/episodes",
                                  "/catalog/ghost/episodes/e1",
                                  "/catalog/ghost/entries"])
def test_missing_vault_redirects_to_root(viewer, tmp_path, path):
    page = viewer().browser().get(path)
    assert page.status != 500
    assert page.status in REDIRECTS, (page.status, page.body)
    landing = page.location.split("?")[0]
    assert landing.endswith("/") and landing.count("/") <= 3, page.location


# Phrase: "landing page shows vault-not-found indication"
def test_landing_page_reports_the_missing_vault(viewer, tmp_path):
    browser = viewer().browser()
    target, page = browser.follow("/catalog/ghost")
    assert page.status == 200
    assert re.search(r"not\s*found", page.body, re.IGNORECASE), page.body


# Phrase: "response must not be HTTP `500`"
# Context: a catalog that cannot be parsed is not a server crash either.
def test_unreadable_catalog_is_not_a_500(viewer, tmp_path):
    vault = tmp_path / "broken"
    vault.mkdir()
    write_raw(vault, "{not json")
    for path in ("/catalog/broken", "/catalog/broken/episodes",
                 "/catalog/broken/episodes/e1"):
        page = viewer().browser().get(path)
        assert page.status != 500, (path, page.status)


# Phrase: "response must not be HTTP `500`"
# Context: an unsupported catalog version is handled, not crashed on.
def test_unsupported_version_is_not_a_500(viewer, tmp_path):
    make_vault(tmp_path, "future", {"version": 99, "source": "http://x/",
                                    "episodes": [], "streams": [], "clips": []})
    page = viewer().browser().get("/catalog/future")
    assert page.status != 500


# Phrase: "Any HTTP error | Well-formed HTTP response; no raw exception or
#          stack trace exposure"
@pytest.mark.parametrize("path", ["/nope", "/catalog", "/catalog/", "/favicon.ico",
                                  "/catalog/ghost/episodes/e1/extra"])
def test_unknown_paths_are_well_formed_without_tracebacks(viewer, tmp_path, path):
    page = viewer().browser().get(path)
    assert page.status < 600
    assert "Traceback" not in page.body
    assert "File \"" not in page.body


# Phrase: "no raw exception or stack trace exposure"
# Context: a malformed catalog must not leak a parser exception either.
def test_broken_catalog_error_page_has_no_traceback(viewer, tmp_path):
    vault = tmp_path / "broken"
    vault.mkdir()
    write_raw(vault, "{not json")
    _, page = viewer().browser().follow("/catalog/broken/episodes")
    assert "Traceback" not in page.body


# Phrase: "Any HTTP error | Well-formed HTTP response"
# Context: unusual names must not escape the vault root or crash the server.
@pytest.mark.parametrize("name", ["..", "%2e%2e", "a%20b", "with.dot"])
def test_odd_vault_names_are_handled(viewer, tmp_path, name):
    page = viewer().browser().get("/catalog/%s" % name)
    assert page.status != 500
    assert "Traceback" not in page.body


# Phrase: "Well-formed HTTP response"
# Context: the server keeps serving after an error.
def test_server_survives_errors(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    browser = viewer().browser()
    browser.get("/catalog/ghost")
    browser.get("/nope")
    assert browser.get("/catalog/v/episodes").status == 200
