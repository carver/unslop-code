"""Spec sections: `/` Routes, `/` Recent Vaults, and their error handling."""

from conftest import (
    RunningViewer,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

REDIRECTS = (302, 303)


def make_v3(tmp_path, name="demo"):
    return write_vault(
        tmp_path, v3_catalog("https://example.test/a", episodes=[v3_entry("e1")]), name=name
    )


# `/` Routes: "`GET` | `/` | HTML page containing a form input for vault name".
def test_landing_page_is_html_with_a_vault_name_input(viewer):
    response = viewer.get("/")

    assert response.status == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "<form" in response.body
    assert 'name="catalog"' in response.body


# `/` Routes: "`POST` | `/` | Accept form-encoded body; redirect to
# `/catalog/<value>` when `catalog` field is present".
def test_post_with_catalog_field_redirects_to_that_vault(viewer, tmp_path):
    make_v3(tmp_path)

    response = viewer.post("/", {"catalog": "demo"})

    assert response.status in REDIRECTS
    assert response.location == "/catalog/demo"


# `/` Routes: "redirect to `/catalog/<value>`" — the field value is used even
# when no such vault exists; the `/catalog` route decides what to do about it.
def test_post_redirects_to_catalog_for_an_unknown_vault(viewer):
    response = viewer.post("/", {"catalog": "nope"})

    assert response.status in REDIRECTS
    assert response.location == "/catalog/nope"


# HTTP Error Handling: "Missing `catalog` field on `POST /` | Redirect to `/`".
def test_post_without_catalog_field_redirects_to_root(viewer):
    response = viewer.post("/", {"other": "demo"})

    assert response.status in REDIRECTS
    assert response.location == "/"


# HTTP Error Handling: "Missing `catalog` field on `POST /` | Redirect to `/`"
# — an empty body carries no field either.
def test_post_with_empty_body_redirects_to_root(viewer):
    response = viewer.post("/", body="")

    assert response.status in REDIRECTS
    assert response.location == "/"


# Determinism: "Redirect status | HTTP `302` or `303`".
def test_post_redirect_uses_a_standard_redirect_status(viewer, tmp_path):
    make_v3(tmp_path)

    assert viewer.post("/", {"catalog": "demo"}).status in REDIRECTS


# `/` Recent Vaults: "Trigger | Navigation to any vault through viewer";
# "Display location | Landing page".
def test_visited_vault_appears_on_the_landing_page(viewer, tmp_path):
    make_v3(tmp_path)

    viewer.get("/catalog/demo", follow=True)

    assert "demo" in viewer.get("/").body


# `/` Recent Vaults: "Empty state | Area may be empty or absent" — a landing
# page served before any visit is still a well-formed page.
def test_landing_page_without_visits_is_well_formed(viewer):
    response = viewer.get("/")

    assert response.status == 200
    assert "<form" in response.body


# `/` Recent Vaults: "Ordering | Most recently visited first".
def test_recent_vaults_are_listed_most_recently_visited_first(viewer, tmp_path):
    make_v3(tmp_path, name="first")
    make_v3(tmp_path, name="second")

    viewer.get("/catalog/first", follow=True)
    viewer.get("/catalog/second", follow=True)
    body = viewer.get("/").body

    assert body.index("second") < body.index("first")


# `/` Recent Vaults: "Ordering | Most recently visited first" — revisiting an
# older vault moves it back to the front.
def test_revisiting_a_vault_moves_it_to_the_front(viewer, tmp_path):
    make_v3(tmp_path, name="first")
    make_v3(tmp_path, name="second")

    viewer.get("/catalog/first", follow=True)
    viewer.get("/catalog/second", follow=True)
    viewer.get("/catalog/first", follow=True)
    body = viewer.get("/").body

    assert body.index("first") < body.index("second")


# `/` Recent Vaults: "Link target | Each recent-vault link points directly to
# that vault's resolved default category page"; Determinism: "Recent-vault
# links on `/` | Use the same resolved default-category route".
def test_recent_link_points_at_the_v3_default_category_page(viewer, tmp_path):
    make_v3(tmp_path)

    viewer.get("/catalog/demo", follow=True)

    assert '"/catalog/demo/episodes"' in viewer.get("/").body


# `/` Recent Vaults: "Link target | ... that vault's resolved default category
# page" — a v1 vault resolves to `entries`, not `episodes`.
def test_recent_link_points_at_the_v1_default_category_page(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]), name="legacy")

    viewer.get("/catalog/legacy", follow=True)

    assert '"/catalog/legacy/entries"' in viewer.get("/").body


# `/` Recent Vaults: "Trigger | Navigation to any vault through viewer" — a
# category page counts as navigation just as the bare vault route does.
def test_visiting_a_category_page_records_the_vault(viewer, tmp_path):
    write_vault(tmp_path, v2_catalog("https://example.test/a", clips=[v2_entry("c1")]), name="two")

    viewer.get("/catalog/two/clips")

    assert '"/catalog/two/episodes"' in viewer.get("/").body


# `/` Recent Vaults: "Persistence | Later browser session from same browser
# must still show visited vault".
def test_visits_survive_a_new_server_and_browser_session(viewer, tmp_path):
    make_v3(tmp_path)
    viewer.get("/catalog/demo", follow=True)
    cookies = dict(viewer.browser.cookies)
    viewer.stop()

    later = RunningViewer(tmp_path)
    try:
        assert "demo" in later.client(cookies).get("/").body
    finally:
        later.stop()


# `/` Recent Vaults: "Persistence | Later browser session from same browser" —
# the cookie that carries the memory outlives the session that set it.
def test_recent_vault_cookie_is_persistent(viewer, tmp_path):
    make_v3(tmp_path)

    response = viewer.client().get("/catalog/demo", follow=True)

    cookie = response.headers.get("Set-Cookie", "")
    assert "demo" in cookie
    assert "Max-Age" in cookie or "Expires" in cookie


# HTTP Error Handling: "Non-existent vault on any `/catalog/<name>` route |
# Redirect to `/`; landing page shows vault-not-found indication; response
# must not be HTTP `500`".
def test_unknown_vault_redirects_to_the_landing_page(viewer):
    response = viewer.get("/catalog/ghost")

    assert response.status in REDIRECTS
    assert response.status != 500
    assert response.location.startswith("/")
    assert not response.location.startswith("/catalog")


# HTTP Error Handling: "landing page shows vault-not-found indication".
def test_landing_page_reports_the_missing_vault(viewer):
    response = viewer.get("/catalog/ghost", follow=True)

    assert response.status == 200
    assert "ghost" in response.body
    assert "not found" in response.body.lower()


# HTTP Error Handling: "Non-existent vault on any `/catalog/<name>` route" —
# the category and entry routes behave like the bare vault route.
def test_unknown_vault_on_deeper_routes_also_redirects(viewer):
    for path in ("/catalog/ghost/episodes", "/catalog/ghost/episodes/e1"):
        response = viewer.get(path)
        assert response.status in REDIRECTS, path
        assert not response.location.startswith("/catalog"), path


# HTTP Error Handling: "Non-existent vault ... response must not be HTTP `500`"
# — a directory whose catalog cannot be read is no more fatal than a missing one.
def test_unreadable_catalog_is_not_a_server_error(viewer, tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "catalog.json").write_text("{not json")

    response = viewer.get("/catalog/broken", follow=True)

    assert response.status == 200
    assert "<form" in response.body


# HTTP Error Handling: "Any HTTP error | Well-formed HTTP response; no raw
# exception or stack trace exposure".
def test_unknown_paths_return_a_clean_response(viewer):
    response = viewer.get("/nowhere")

    assert response.status in (302, 303, 400, 404)
    assert "Traceback" not in response.body
