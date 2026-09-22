"""Spec sections: `serve` Command, `/` Routes, `/` Recent Vaults,
`/catalog` Routes, Version-Aware Default Category Redirect, Version-Aware
Valid Categories, `/catalog/<name>/<category>` Listing Rules, HTTP Error
Handling, `serve` Required Public Surface, and their Determinism rows."""
import os
import re
import socket

import pytest

from conftest import (
    DEFAULT_VIEWER_HOST,
    DEFAULT_VIEWER_PORT,
    ViewerClient,
    browser_stub,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    wait_for_file,
    write_file,
    write_vault,
)

T1 = "2024-01-01T00:00:00"
T2 = "2024-02-01T00:00:00"

REDIRECTS = (302, 303)


def free_port():
    """A port that was free a moment ago."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def catalog_page(client, name, category, eid=None):
    path = "/catalog/%s/%s" % (name, category)
    if eid is not None:
        path += "/" + eid
    return client.get(path)


def entry_row(text, eid):
    """The smallest chunk of markup that describes entry `eid`.

    Markup is free-form, so a row is approximated by splitting the page on
    common block-element starts and keeping the shortest chunk mentioning the
    entry.
    """
    assert eid in text, text
    chunks = re.split(r"(?=<li\b)|(?=<tr\b)|(?=<article\b)|(?=<div\b)|(?=<p\b)",
                      text)
    found = [chunk for chunk in chunks if eid in chunk]
    assert found, text
    row = min(found, key=len)
    for closer in ("</li>", "</tr>", "</article>", "</div>", "</p>"):
        if closer in row:  # drop whatever trails the row itself
            return row.split(closer)[0] + closer
    return row


def row_shape(text, eid):
    """One entry's row with its own id and title blanked out.

    Two entries that are rendered the same way have the same shape, so a
    difference in shape is exactly a difference in how the viewer presents
    their state.
    """
    row = entry_row(text, eid)
    return row.replace("Title %s" % eid, "TITLE").replace(eid, "ID")


@pytest.fixture
def v3_vault(tmp_path):
    write_vault(tmp_path, v3_catalog(
        episodes=[v3_entry("e1"), v3_entry("e2")],
        streams=[v3_entry("s1")],
        clips=[v3_entry("c1")],
    ))
    return "vault"


# ---------------------------------------------------------------------------
# `serve` Command
# ---------------------------------------------------------------------------

# --- Phrase: "| Syntax | `python mvault.py serve [<name>] [--host=<host>]
#     [--port=<port>]` |" + "| CLI `serve` command | Required |"
def test_serve_starts_a_server_without_a_vault_name(viewer):
    client = viewer()
    assert client.get("/").status == 200


def test_serve_accepts_an_optional_vault_name(viewer, v3_vault):
    client = viewer(v3_vault)
    assert client.get("/").status == 200


# --- Phrase: "| Default bind address | `127.0.0.1:8840` |" + "| Default port
#     | `8840` |"
def test_default_bind_address_is_localhost_8840(viewer):
    client = viewer(port=None)
    assert client.base == "http://%s:%d" % (DEFAULT_VIEWER_HOST,
                                            DEFAULT_VIEWER_PORT)
    assert client.get("/").status == 200


# --- Phrase: "| `--port=<port>` | Override bind port |"
def test_port_option_overrides_the_bind_port(viewer):
    port = free_port()
    client = viewer(port=port)
    assert client.base.endswith(":%d" % port), client.base
    assert client.get("/").status == 200


# --- Phrase: "| `--host=<host>` | Override bind host |"
def test_host_option_overrides_the_bind_host(viewer):
    port = free_port()
    client = viewer("--host=0.0.0.0", port=port)
    reachable = ViewerClient("http://127.0.0.1:%d" % port)
    assert reachable.get("/").status == 200


def test_unbindable_host_fails_without_a_traceback(viewer, tmp_path):
    proc = viewer("--host=192.0.2.1", port=free_port(), expect_ready=False)
    assert proc.wait(timeout=30) != 0
    log = open(os.path.join(str(tmp_path), "serve-0.log")).read()
    assert "Traceback" not in log, log


# --- Phrase: "| `serve` without `<name>` | Start server and open browser to
#     `/` |"
def test_serve_without_a_name_opens_the_root_page(viewer, tmp_path):
    script, opened = browser_stub(tmp_path)
    port = free_port()
    viewer(port=port, env={"BROWSER": script, "MVAULT_NO_BROWSER": ""})
    url = wait_for_file(opened).strip()
    assert url.endswith("/"), url
    assert "/catalog/" not in url, url


# --- Phrase: "| `serve <name>` | Start server and open browser to default
#     category page for vault |"
def test_serve_with_a_name_opens_the_default_category_page(viewer, tmp_path,
                                                           v3_vault):
    script, opened = browser_stub(tmp_path)
    viewer(v3_vault, env={"BROWSER": script, "MVAULT_NO_BROWSER": ""})
    url = wait_for_file(opened).strip()
    assert url.endswith("/catalog/vault/episodes"), url


def test_serve_with_a_v1_name_opens_the_entries_page(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]), "old")
    script, opened = browser_stub(tmp_path)
    viewer("old", env={"BROWSER": script, "MVAULT_NO_BROWSER": ""})
    url = wait_for_file(opened).strip()
    assert url.endswith("/catalog/old/entries"), url


# ---------------------------------------------------------------------------
# `/` Routes
# ---------------------------------------------------------------------------

# --- Phrase: "| `GET` | `/` | HTML page containing a form input for vault
#     name |"
def test_root_page_is_html(viewer):
    response = viewer().get("/")
    assert response.status == 200
    assert "text/html" in response.headers.get("Content-Type", ""), response
    assert "<html" in response.text.lower(), response


def test_root_page_has_a_form_input_for_the_vault_name(viewer):
    text = viewer().get("/").text
    assert "<form" in text.lower(), text
    assert "<input" in text.lower(), text
    assert 'name="catalog"' in text, text


# --- Phrase: "| `POST` | `/` | Accept form-encoded body; redirect to
#     `/catalog/<value>` when `catalog` field is present ... |"
def test_post_root_redirects_to_the_named_catalog(viewer):
    response = viewer().post("/", {"catalog": "vault"})
    assert response.status in REDIRECTS, response
    assert response.location == "/catalog/vault", response


def test_post_root_accepts_a_form_encoded_body(viewer, v3_vault):
    client = viewer()
    response = client.post("/", raw="catalog=vault&other=ignored")
    assert response.status in REDIRECTS, response
    assert response.location == "/catalog/vault", response


# --- Phrase: "... otherwise redirect to `/`" + "| Missing `catalog` field on
#     `POST /` | Redirect to `/` |"
def test_post_root_without_the_catalog_field_redirects_to_root(viewer):
    response = viewer().post("/", {"name": "vault"})
    assert response.status in REDIRECTS, response
    assert response.location == "/", response


def test_post_root_with_an_empty_body_redirects_to_root(viewer):
    response = viewer().post("/", raw="")
    assert response.status in REDIRECTS, response
    assert response.location == "/", response


# --- Phrase: "| Redirect status | HTTP `302` or `303` |"
def test_post_root_redirect_uses_a_redirect_status(viewer):
    assert viewer().post("/", {"catalog": "vault"}).status in REDIRECTS


# ---------------------------------------------------------------------------
# `/` Recent Vaults
# ---------------------------------------------------------------------------

# --- Phrase: "| Trigger | Navigation to any vault through viewer |" +
#     "| Display location | Landing page |"
def test_visited_vault_appears_on_the_landing_page(viewer, v3_vault):
    client = viewer()
    client.get("/catalog/vault")
    assert '"/catalog/vault/episodes"' in client.get("/").text


def test_landing_page_lists_a_vault_visited_by_category_page(viewer, v3_vault):
    client = viewer()
    client.get("/catalog/vault/episodes")
    assert '"/catalog/vault/episodes"' in client.get("/").text


# --- Phrase: "| Persistence | Later browser session from same browser must
#     still show visited vault |"
def test_recent_vault_survives_a_later_browser_session(viewer, v3_vault):
    client = viewer()
    client.get("/catalog/vault")
    later = client.later_session()
    assert '"/catalog/vault/episodes"' in later.get("/").text


# --- Phrase: "| Ordering | Most recently visited first |" + "| Recent-vault
#     order | Most recently visited first |"
def test_recent_vaults_are_listed_most_recent_first(viewer, tmp_path):
    for name in ("alpha", "beta"):
        write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]), name)
    client = viewer()
    client.get("/catalog/alpha")
    client.get("/catalog/beta")
    text = client.get("/").text
    assert text.index("beta") < text.index("alpha"), text


def test_revisiting_moves_a_vault_back_to_the_front(viewer, tmp_path):
    for name in ("alpha", "beta"):
        write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]), name)
    client = viewer()
    client.get("/catalog/alpha")
    client.get("/catalog/beta")
    client.get("/catalog/alpha")
    text = client.get("/").text
    assert text.index("alpha") < text.index("beta"), text


# --- Phrase: "| Link target | Each recent-vault link points directly to that
#     vault's resolved default category page |" + "| Recent-vault links on `/`
#     | Use the same resolved default-category route as `/catalog/<name>`
#     would redirect to |"
def test_recent_vault_link_targets_the_default_category_page(viewer, v3_vault):
    client = viewer()
    client.get("/catalog/vault")
    assert '"/catalog/vault/episodes"' in client.get("/").text


def test_recent_v1_vault_link_targets_the_entries_page(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]), "old")
    client = viewer()
    client.get("/catalog/old")
    assert '"/catalog/old/entries"' in client.get("/").text


# --- Phrase: "| Empty state | Area may be empty or absent |"
def test_landing_page_without_visits_is_still_served(viewer):
    response = viewer().get("/")
    assert response.status == 200
    assert "<html" in response.text.lower()


# ---------------------------------------------------------------------------
# `/catalog` Routes and the version-aware default redirect
# ---------------------------------------------------------------------------

# --- Phrase: "| `GET` | `/catalog/<name>` | Redirect to default category page
#     for vault |" + Version-Aware Default Category Redirect table
@pytest.mark.parametrize(
    "catalog,category",
    [
        (v1_catalog(entries=[v1_entry("e1")]), "entries"),
        (v2_catalog(episodes=[v2_entry("e1")]), "episodes"),
        (v3_catalog(episodes=[v3_entry("e1")]), "episodes"),
    ],
)
def test_catalog_redirects_to_the_version_default_category(viewer, tmp_path,
                                                           catalog, category):
    write_vault(tmp_path, catalog)
    response = viewer().get("/catalog/vault")
    assert response.status in REDIRECTS, response
    assert response.location == "/catalog/vault/%s" % category, response


# --- Phrase: "| `GET` | `/catalog/<name>/<category>` | HTML listing for
#     category |"
def test_category_listing_is_html(viewer, v3_vault):
    response = catalog_page(viewer(), "vault", "episodes")
    assert response.status == 200, response
    assert "text/html" in response.headers.get("Content-Type", ""), response
    assert "<html" in response.text.lower(), response


# --- Phrase: Version-Aware Valid Categories, v2/v3 row
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_serves_every_valid_category(viewer, v3_vault, category):
    assert catalog_page(viewer(), "vault", category).status == 200


@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_serves_every_valid_category(viewer, tmp_path, category):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")],
                                     streams=[v2_entry("s1")],
                                     clips=[v2_entry("c1")]))
    assert catalog_page(viewer(), "vault", category).status == 200


# --- Phrase: Version-Aware Valid Categories, v1 row ("`entries`")
def test_v1_serves_the_entries_category(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = catalog_page(viewer(), "vault", "entries")
    assert response.status == 200, response
    assert "Title e1" in response.text, response


# --- Phrase: "| `GET` | `/catalog/<name>/<category>/<id>` | HTML response for
#     that viewer link target ... |"
def test_entry_route_returns_html(viewer, v3_vault):
    response = catalog_page(viewer(), "vault", "episodes", "e1")
    assert response.status == 200, response
    assert "text/html" in response.headers.get("Content-Type", ""), response
    assert "Title e1" in response.text, response


def test_entry_route_surfaces_the_requested_entry(viewer, v3_vault):
    listing = catalog_page(viewer(), "vault", "episodes").text
    detail = catalog_page(viewer(), "vault", "episodes", "e2").text
    assert detail != listing, detail


def test_entry_route_works_for_a_v1_vault(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = catalog_page(viewer(), "vault", "entries", "e1")
    assert response.status == 200, response


# --- Phrase: "The viewer works on vaults of any supported version without
#     requiring prior migration."
@pytest.mark.parametrize(
    "catalog,category",
    [
        (v1_catalog(entries=[v1_entry("e1")]), "entries"),
        (v2_catalog(episodes=[v2_entry("e1")]), "episodes"),
        (v3_catalog(episodes=[v3_entry("e1")]), "episodes"),
    ],
)
def test_viewer_does_not_migrate_the_vault(viewer, tmp_path, catalog,
                                           category):
    write_vault(tmp_path, catalog)
    path = os.path.join(str(tmp_path), "vault", "catalog.json")
    before = open(path).read()
    client = viewer()
    client.get("/catalog/vault")
    catalog_page(client, "vault", category)
    assert open(path).read() == before


# ---------------------------------------------------------------------------
# Listing rules
# ---------------------------------------------------------------------------

# --- Phrase: "| Category matching | Case-sensitive |"
def test_category_matching_is_case_sensitive(viewer, v3_vault):
    response = catalog_page(viewer(), "vault", "Episodes")
    if response.status in REDIRECTS:
        assert response.location == "/catalog/vault/episodes", response
    else:
        assert response.status in (400, 404), response


# --- Phrase: "| Entry order | Same order as category array in `catalog.json`
#     |" + "| Listing order | Matches category-array order in `catalog.json`
#     |"
def test_entries_are_listed_in_catalog_array_order(viewer, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[
        v3_entry("zzz", published="2020-01-01T00:00:00"),
        v3_entry("aaa", published="2024-01-01T00:00:00"),
        v3_entry("mmm", published="2022-01-01T00:00:00"),
    ]))
    text = catalog_page(viewer(), "vault", "episodes").text
    positions = [text.index("Title %s" % eid) for eid in ("zzz", "aaa", "mmm")]
    assert positions == sorted(positions), text


def test_v1_entries_are_listed_in_catalog_array_order(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("b"), v1_entry("a")]))
    text = catalog_page(viewer(), "vault", "entries").text
    assert text.index("Title b") < text.index("Title a"), text


# --- Phrase: "| Current title | Latest value from `title` history, resolved
#     using the vault version's key format |"
def test_listing_shows_the_current_title(viewer, tmp_path):
    write_vault(tmp_path, v3_catalog(
        episodes=[v3_entry("e1", title={T1: "Stale name", T2: "Current name"})]
    ))
    text = catalog_page(viewer(), "vault", "episodes").text
    assert "Current name" in text, text
    assert "Stale name" not in text, text


# --- Phrase: "| v1 title resolution | Latest by numeric comparison of
#     UNIX-epoch string keys |"
def test_v1_title_uses_numeric_key_comparison(viewer, tmp_path):
    # Lexicographically "999999999" > "1000000000"; numerically it is smaller.
    write_vault(tmp_path, v1_catalog(entries=[
        v1_entry("e1", title={"999999999": "Older title",
                              "1000000000": "Newer title"})
    ]))
    text = catalog_page(viewer(), "vault", "entries").text
    assert "Newer title" in text, text
    assert "Older title" not in text, text


# --- Phrase: "| v2/v3 title resolution | Latest by lexicographic comparison
#     of ISO 8601 string keys |"
@pytest.mark.parametrize("build", [v2_catalog, v3_catalog])
def test_v2_and_v3_titles_use_lexicographic_key_comparison(viewer, tmp_path,
                                                           build):
    entry_builder = v2_entry if build is v2_catalog else v3_entry
    titles = {"2024-10-01T00:00:00": "October title",
              "2024-9-01T00:00:00": "September title"}
    write_vault(tmp_path, build(episodes=[entry_builder("e1", title=titles)]))
    text = catalog_page(viewer(), "vault", "episodes").text
    assert "September title" in text, text


# --- Phrase: "| Downloaded state (v2/v3) | Entry counts as downloaded when a
#     media filename in `<vault>/media/` contains entry `id` |" +
#     "| Visual distinction | Downloaded and undownloaded states must be
#     distinguishable |"
def test_downloaded_and_undownloaded_entries_are_distinguishable(viewer,
                                                                 tmp_path):
    write_vault(tmp_path, v3_catalog(
        episodes=[v3_entry("got"), v3_entry("nope")]
    ))
    write_file(os.path.join(str(tmp_path), "vault", "media", "got.mp4"))
    text = catalog_page(viewer(), "vault", "episodes").text
    assert row_shape(text, "got") != row_shape(text, "nope"), text


def test_downloaded_state_matches_a_filename_containing_the_id(viewer,
                                                               tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    plain = catalog_page(viewer(), "vault", "episodes").text
    write_file(os.path.join(str(tmp_path), "vault", "media",
                            "prefix-e1-suffix.mp4"))
    marked = catalog_page(viewer(), "vault", "episodes").text
    assert row_shape(marked, "e1") != row_shape(plain, "e1")


# --- Phrase: "| Downloaded state (v1) | Same rule as v2/v3 |"
def test_v1_downloaded_state_uses_the_same_rule(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("got"),
                                              v1_entry("nope")]))
    write_file(os.path.join(str(tmp_path), "vault", "media", "got.mp4"))
    text = catalog_page(viewer(), "vault", "entries").text
    assert row_shape(text, "got") != row_shape(text, "nope"), text


# --- Phrase: "| Removed indicator (v3 only) | Entries with latest `removed`
#     value `true` are visually distinct from active entries |"
def test_removed_entries_are_visually_distinct(viewer, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[
        v3_entry("gone", removed={T1: False, T2: True}),
        v3_entry("here", removed={T1: False}),
    ]))
    text = catalog_page(viewer(), "vault", "episodes").text
    assert row_shape(text, "gone") != row_shape(text, "here"), text


def test_removed_flag_uses_the_latest_history_value(viewer, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[
        v3_entry("resumed", removed={T1: True, T2: False}),
        v3_entry("steady", removed={T1: False}),
    ]))
    text = catalog_page(viewer(), "vault", "episodes").text
    assert row_shape(text, "resumed") == row_shape(text, "steady"), text


# --- Phrase: "| Removed indicator (v1/v2) | Not applicable; no `removed`
#     field exists |"
@pytest.mark.parametrize(
    "catalog,category",
    [
        (v1_catalog(entries=[v1_entry("e1")]), "entries"),
        (v2_catalog(episodes=[v2_entry("e1")]), "episodes"),
    ],
)
def test_legacy_listings_render_without_a_removed_field(viewer, tmp_path,
                                                        catalog, category):
    write_vault(tmp_path, catalog)
    response = catalog_page(viewer(), "vault", category)
    assert response.status == 200, response
    assert "Title e1" in response.text, response


# --- Phrase: "| Entry navigation | Each listed entry includes a link to
#     `/catalog/<name>/<category>/<id>` |"
def test_each_entry_links_to_its_own_page(viewer, v3_vault):
    text = catalog_page(viewer(), "vault", "episodes").text
    for eid in ("e1", "e2"):
        assert '"/catalog/vault/episodes/%s"' % eid in text, text


def test_v1_entries_link_to_the_entries_route(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    text = catalog_page(viewer(), "vault", "entries").text
    assert '"/catalog/vault/entries/e1"' in text, text


def test_stream_entries_link_into_their_own_category(viewer, v3_vault):
    text = catalog_page(viewer(), "vault", "streams").text
    assert '"/catalog/vault/streams/s1"' in text, text


# --- Phrase: "| Listing order | Matches category-array order ... |"
#     (context: Determinism -- repeated requests agree)
def test_listing_is_identical_across_requests(viewer, v3_vault):
    client = viewer()
    first = catalog_page(client, "vault", "episodes").text
    second = catalog_page(client, "vault", "episodes").text
    assert first == second


# ---------------------------------------------------------------------------
# HTTP Error Handling
# ---------------------------------------------------------------------------

# --- Phrase: "| Invalid category on `GET /catalog/<name>/<category>` for v1
#     vault | Redirect to `/catalog/<name>/entries` or return HTTP `400`/`404`
#     |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips", "bogus"])
def test_invalid_category_on_a_v1_vault(viewer, tmp_path, category):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = catalog_page(viewer(), "vault", category)
    if response.status in REDIRECTS:
        assert response.location == "/catalog/vault/entries", response
    else:
        assert response.status in (400, 404), response


# --- Phrase: "| Invalid category on `GET /catalog/<name>/<category>` for
#     v2/v3 vault | Redirect to `/catalog/<name>/episodes` or return HTTP
#     `400`/`404` |"
@pytest.mark.parametrize("category", ["entries", "bogus"])
def test_invalid_category_on_a_v3_vault(viewer, v3_vault, category):
    response = catalog_page(viewer(), "vault", category)
    if response.status in REDIRECTS:
        assert response.location == "/catalog/vault/episodes", response
    else:
        assert response.status in (400, 404), response


@pytest.mark.parametrize("category", ["entries", "bogus"])
def test_invalid_category_on_a_v2_vault(viewer, tmp_path, category):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")]))
    response = catalog_page(viewer(), "vault", category)
    if response.status in REDIRECTS:
        assert response.location == "/catalog/vault/episodes", response
    else:
        assert response.status in (400, 404), response


# --- Phrase: "| Non-existent vault on any `/catalog/<name>` route | Redirect
#     to `/`; landing page shows vault-not-found indication; response must not
#     be HTTP `500` |"
@pytest.mark.parametrize(
    "path",
    ["/catalog/ghost", "/catalog/ghost/episodes", "/catalog/ghost/entries",
     "/catalog/ghost/episodes/e1"],
)
def test_missing_vault_redirects_to_the_landing_page(viewer, path):
    response = viewer().get(path)
    assert response.status != 500, response
    assert response.status in REDIRECTS, response
    assert response.location.startswith("/"), response
    assert not response.location.startswith("/catalog"), response


def test_missing_vault_landing_page_indicates_not_found(viewer):
    client = viewer()
    response = client.get("/catalog/ghost", follow=True)
    assert response.status == 200, response
    assert "ghost" in response.text, response
    assert "not found" in response.text.lower(), response


def test_missing_vault_is_not_added_to_recent_vaults(viewer, v3_vault):
    client = viewer()
    client.get("/catalog/ghost", follow=True)
    client.get("/catalog/vault")
    text = client.get("/").text
    assert '"/catalog/ghost' not in text, text


def test_unreadable_vault_does_not_return_500(viewer, tmp_path):
    write_vault(tmp_path, "{not json", "broken")
    response = viewer().get("/catalog/broken")
    assert response.status != 500, response
    assert response.status in REDIRECTS, response


def test_unsupported_version_does_not_return_500(viewer, tmp_path):
    write_vault(tmp_path, {"version": 9, "entries": []}, "future")
    response = viewer().get("/catalog/future")
    assert response.status != 500, response


# --- Phrase: "| Any HTTP error | Well-formed HTTP response; no raw exception
#     or stack trace exposure |"
@pytest.mark.parametrize(
    "path",
    ["/nope", "/catalog", "/catalog/", "/favicon.ico", "/catalog/a/b/c/d"],
)
def test_odd_paths_produce_a_well_formed_response(viewer, path):
    response = viewer().get(path)
    assert response.status != 500, response
    assert "Traceback" not in response.text, response
    assert response.headers.get("Content-Type"), response


def test_entry_route_with_an_unknown_id_is_well_formed(viewer, v3_vault):
    response = catalog_page(viewer(), "vault", "episodes", "missing-id")
    assert response.status != 500, response
    assert "Traceback" not in response.text, response


def test_percent_encoded_segments_do_not_break_the_server(viewer, v3_vault):
    response = viewer().get("/catalog/vault/episodes/%2e%2e%2fetc")
    assert response.status != 500, response
    assert "Traceback" not in response.text, response


def test_server_stays_up_after_bad_requests(viewer, v3_vault):
    client = viewer()
    for path in ("/nope", "/catalog/ghost", "/catalog/vault/bogus"):
        client.get(path)
    assert catalog_page(client, "vault", "episodes").status == 200
