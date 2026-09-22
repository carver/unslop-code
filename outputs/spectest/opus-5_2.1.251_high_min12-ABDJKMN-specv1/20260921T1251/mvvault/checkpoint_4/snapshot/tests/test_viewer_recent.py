"""Spec section: `/` Recent Vaults."""

from __future__ import annotations

import re


def recent_links(body):
    """Every `/catalog/...` link on the landing page, in document order."""
    return re.findall(r'href="(/catalog/[^"]*)"', body)


def recent_names(body):
    """Vault names of the landing page's catalog links, in document order."""
    seen = []
    for href in recent_links(body):
        name = href.split("/")[2] if len(href.split("/")) > 2 else ""
        if name and name not in seen:
            seen.append(name)
    return seen


# ---------------------------------------------------------------------------
# | Trigger | Navigation to any vault through viewer |
# | Display location | Landing page |
# ---------------------------------------------------------------------------

# Spec: | Trigger | Navigation to any vault through viewer |
#       | Display location | Landing page |
def test_visited_vault_appears_on_the_landing_page(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    client = serve().client
    client.get("/catalog/vault", follow=True)
    assert "vault" in recent_names(client.get("/").body)


# Spec: | Trigger | Navigation to any vault through viewer |
# Context: navigating straight to a category page is navigation to that vault.
def test_category_navigation_records_the_vault(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="alpha")
    client = serve().client
    client.get("/catalog/alpha/episodes")
    assert "alpha" in recent_names(client.get("/").body)


# Spec: | Trigger | Navigation to any vault through viewer |
# Context: an entry link target is navigation to that vault as well.
def test_entry_navigation_records_the_vault(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="beta")
    client = serve().client
    client.get("/catalog/beta/episodes/e1")
    assert "beta" in recent_names(client.get("/").body)


# Spec: | Trigger | Navigation to any vault through viewer |
# Context: the landing form's POST leads to a vault, so that vault is recorded.
def test_posting_the_form_records_the_vault(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="gamma")
    client = serve().client
    client.post("/", {"catalog": "gamma"}, follow=True)
    assert "gamma" in recent_names(client.get("/").body)


# ---------------------------------------------------------------------------
# | Empty state | Area may be empty or absent |
# ---------------------------------------------------------------------------

# Spec: | Empty state | Area may be empty or absent |
def test_landing_page_without_visits_still_renders(serve):
    response = serve().client.get("/")
    assert response.status == 200
    assert recent_names(response.body) == []


# ---------------------------------------------------------------------------
# | Ordering | Most recently visited first |
# ---------------------------------------------------------------------------

# Spec: | Ordering | Most recently visited first |
def test_recent_vaults_are_most_recent_first(serve, make_vault, catalogs):
    for name in ("one", "two", "three"):
        make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name=name)
    client = serve().client
    for name in ("one", "two", "three"):
        client.get(f"/catalog/{name}/episodes")
    assert recent_names(client.get("/").body)[:3] == ["three", "two", "one"]


# Spec: | Ordering | Most recently visited first |
# Context: revisiting an older vault moves it back to the front.
def test_revisiting_moves_a_vault_to_the_front(serve, make_vault, catalogs):
    for name in ("one", "two"):
        make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name=name)
    client = serve().client
    client.get("/catalog/one/episodes")
    client.get("/catalog/two/episodes")
    client.get("/catalog/one/episodes")
    assert recent_names(client.get("/").body)[:2] == ["one", "two"]


# Spec: | Ordering | Most recently visited first |
# Context: a revisited vault is listed once, not twice.
def test_revisiting_does_not_duplicate_a_vault(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="solo")
    client = serve().client
    client.get("/catalog/solo/episodes")
    client.get("/catalog/solo/episodes")
    names = recent_names(client.get("/").body)
    assert names.count("solo") == 1, names


# ---------------------------------------------------------------------------
# | Persistence | Later browser session from same browser must still show
#   visited vault |
# ---------------------------------------------------------------------------

# Spec: | Persistence | Later browser session from same browser must still show
#   visited vault |
def test_visited_vault_survives_a_later_browser_session(serve, make_vault,
                                                        catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="kept")
    process = serve()
    process.client.get("/catalog/kept/episodes")
    later = process.client.later_session()
    assert "kept" in recent_names(later.get("/").body)


# Spec: | Persistence | Later browser session ... must still show visited vault |
# Context: "later session" includes one that outlives the server process.
def test_visited_vault_survives_a_server_restart(serve, make_vault, catalogs,
                                                 viewer_helpers):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="kept")
    first = serve()
    first.client.get("/catalog/kept/episodes")
    cookies = dict(first.client.cookies)
    first.stop()

    second = serve()
    later = viewer_helpers.client(second.host, second.port, cookies=cookies)
    assert "kept" in recent_names(later.get("/").body)


# ---------------------------------------------------------------------------
# | Link target | Each recent-vault link points directly to that vault's
#   resolved default category page |
# ---------------------------------------------------------------------------

# Spec: | Link target | Each recent-vault link points directly to that vault's
#   resolved default category page |
# Context: v3 resolves to `episodes`.
def test_recent_link_targets_the_v3_default_category(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="v3v")
    client = serve().client
    client.get("/catalog/v3v/episodes")
    assert "/catalog/v3v/episodes" in recent_links(client.get("/").body)


# Spec: | Link target | ... resolved default category page |
# Context: v1 resolves to `entries`.
def test_recent_link_targets_the_v1_default_category(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]), name="v1v")
    client = serve().client
    client.get("/catalog/v1v", follow=True)
    assert "/catalog/v1v/entries" in recent_links(client.get("/").body)


# Spec: | Recent-vault links on `/` | Use the same resolved default-category
#   route as `/catalog/<name>` would redirect to | (Determinism)
def test_recent_link_matches_the_catalog_redirect(serve, make_vault, legacy):
    make_vault(legacy.v2_catalog(streams=[legacy.v2_entry("s1")]), name="v2v")
    client = serve().client
    redirect = client.get("/catalog/v2v")
    client.get("/catalog/v2v/streams")
    links = recent_links(client.get("/").body)
    assert redirect.location.split("//")[-1].partition("/")[2].rstrip("/") \
        in [link.lstrip("/") for link in links], (redirect.location, links)


# Spec: | Link target | ... points directly to that vault's resolved default
#   category page |
# Context: the link a visitor follows must render the listing itself.
def test_recent_link_is_directly_followable(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="direct")
    process = serve()
    process.client.get("/catalog/direct/episodes")
    link = [href for href in recent_links(process.client.get("/").body)
            if "direct" in href][0]
    response = process.client.get(link)
    assert response.status == 200
    assert "Title e1" in response.body
