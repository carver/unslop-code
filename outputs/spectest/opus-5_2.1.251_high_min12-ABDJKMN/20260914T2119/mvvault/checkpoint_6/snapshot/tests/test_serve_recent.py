"""Spec: the `/` Recent Vaults table."""
from digest_helpers import v1, v1_entry, v2, v3, v3_entry, legacy_entry
from viewer_helpers import catalog_links, hrefs


def recent_hrefs(server):
    """Links into `/catalog/` on the landing page, in page order."""
    return [href for href, _ in catalog_links(server.get("/").body)]


# Spec: "| Trigger | Navigation to any vault through viewer |" +
# "| Display location | Landing page |"
def test_visiting_a_vault_adds_it_to_the_landing_page(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="alpha")
    server = serve()
    assert recent_hrefs(server) == []
    server.get("/catalog/alpha", follow=True)
    assert "/catalog/alpha/episodes" in recent_hrefs(server)


# Spec: "| Trigger | Navigation to any vault through viewer |" -- reaching a
# category page directly counts as navigation too.
def test_direct_category_navigation_counts(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="alpha")
    server = serve()
    server.get("/catalog/alpha/episodes")
    assert "/catalog/alpha/episodes" in recent_hrefs(server)


# Spec: "| Trigger | Navigation to any vault through viewer |" -- so does
# opening an entry page.
def test_entry_navigation_counts(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="alpha")
    server = serve()
    server.get("/catalog/alpha/episodes/e1")
    assert "/catalog/alpha/episodes" in recent_hrefs(server)


# Spec: "| Link target | Each recent-vault link points directly to that vault's
# resolved default category page |" -- v1 resolves to `entries`.
def test_recent_link_for_v1_points_at_entries(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]), name="old")
    server = serve()
    server.get("/catalog/old/entries")
    assert "/catalog/old/entries" in recent_hrefs(server)


# Spec: "| Link target | ... resolved default category page |" -- v2 resolves
# to `episodes` even when the visit was to another category.
def test_recent_link_uses_default_category_not_visited_one(serve, make_vault):
    make_vault(v2(clips=[legacy_entry(id="c1")]), name="two")
    server = serve()
    server.get("/catalog/two/clips")
    assert "/catalog/two/episodes" in recent_hrefs(server)


# Spec: "| Recent-vault links on `/` | Use the same resolved default-category
# route as `/catalog/<name>` would redirect to |"
def test_recent_link_matches_the_catalog_redirect(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]), name="one")
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="three")
    server = serve()
    for name in ("one", "three"):
        redirect = server.get("/catalog/%s" % name)
        assert redirect.is_redirect, redirect
        assert redirect.location in recent_hrefs(server)


# Spec: "| Ordering | Most recently visited first |"
def test_most_recently_visited_first(serve, make_vault):
    for name in ("alpha", "beta", "gamma"):
        make_vault(v3(episodes=[v3_entry(id="e1")]), name=name)
    server = serve()
    server.get("/catalog/alpha/episodes")
    server.get("/catalog/beta/episodes")
    server.get("/catalog/gamma/episodes")
    assert recent_hrefs(server) == ["/catalog/gamma/episodes",
                                    "/catalog/beta/episodes",
                                    "/catalog/alpha/episodes"]


# Spec: "| Recent-vault order | Most recently visited first |" -- revisiting an
# older vault moves it back to the front instead of duplicating it.
def test_revisit_moves_vault_to_front_without_duplicating(serve, make_vault):
    for name in ("alpha", "beta"):
        make_vault(v3(episodes=[v3_entry(id="e1")]), name=name)
    server = serve()
    server.get("/catalog/alpha/episodes")
    server.get("/catalog/beta/episodes")
    server.get("/catalog/alpha/episodes")
    assert recent_hrefs(server) == ["/catalog/alpha/episodes",
                                    "/catalog/beta/episodes"]


# Spec: "| Persistence | Later browser session from same browser must still
# show visited vault |" -- the record outlives the process that recorded it.
def test_recent_vaults_persist_across_sessions(serve, make_vault, tmp_path):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="alpha")
    first = serve()
    first.get("/catalog/alpha/episodes")
    first.stop()

    second = serve()
    assert "/catalog/alpha/episodes" in recent_hrefs(second)


# Spec: "| Persistence | ... |" -- ordering survives the restart too.
def test_recent_order_persists_across_sessions(serve, make_vault):
    for name in ("alpha", "beta"):
        make_vault(v3(episodes=[v3_entry(id="e1")]), name=name)
    first = serve()
    first.get("/catalog/alpha/episodes")
    first.get("/catalog/beta/episodes")
    first.stop()

    second = serve()
    assert recent_hrefs(second) == ["/catalog/beta/episodes",
                                    "/catalog/alpha/episodes"]


# Spec: "| Empty state | Area may be empty or absent |" -- before any
# navigation the landing page carries no vault links.
def test_empty_state_before_any_navigation(serve):
    server = serve()
    assert recent_hrefs(server) == []
    assert server.get("/").status == 200


# Spec: "| Trigger | Navigation to any vault through viewer |" -- a vault that
# does not exist was never navigated to, so it is not recorded.
def test_missing_vault_is_not_recorded_as_recent(serve):
    server = serve()
    server.get("/catalog/ghost", follow=True)
    assert [href for href in recent_hrefs(server) if "ghost" in href] == []


# Spec: "| Display location | Landing page |" -- the recent link names the
# vault it points at.
def test_recent_link_text_names_the_vault(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="alpha")
    server = serve()
    server.get("/catalog/alpha/episodes")
    matches = [text for href, text in catalog_links(server.get("/").body)]
    assert any("alpha" in text for text in matches), matches


# Spec: "| Trigger | Navigation to any vault through viewer |" -- arriving via
# the landing-page form records the vault as well.
def test_form_navigation_records_the_vault(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="alpha")
    server = serve()
    server.post("/", fields={"catalog": "alpha"}, follow=True)
    assert "/catalog/alpha/episodes" in recent_hrefs(server)
