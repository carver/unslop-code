"""`serve` Command, `/` Routes, `/` Recent Vaults and HTTP Error Handling."""

import re

import pytest

from conftest import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    SOURCE_URL,
    free_port,
    v1_catalog,
    v1_entry,
    v3_catalog,
    v3_entry,
)


@pytest.fixture
def vaults(make_vault):
    """Write the named vaults to the served directory and start nothing."""

    def make(**catalogs):
        for name, catalog in catalogs.items():
            make_vault(catalog, name)

    return make


def location(response):
    """The `Location` header of an unfollowed redirect response."""
    assert response.status_code in (302, 303), response.status_code
    return response.headers["Location"]


# Spec: Syntax | `python mvault.py serve [<name>] [--host=<host>] [--port=<port>]`
def test_serve_starts_a_server_without_a_name(viewer):
    assert viewer().get("/").status_code == 200


# Spec: Syntax | `python mvault.py serve [<name>] ...` (with a vault name)
def test_serve_accepts_a_vault_name(viewer, vaults):
    vaults(v=v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]))
    assert viewer("v").get("/").status_code == 200


# Spec: Default bind address | `127.0.0.1:8840`
def test_default_bind_address_is_the_documented_one(viewer):
    client = viewer(port=DEFAULT_PORT, pass_port=False)
    assert client.base_url == f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    assert client.get("/").status_code == 200


# Spec: `--port=<port>` | Override bind port
def test_port_option_overrides_the_bind_port(viewer):
    port = free_port()
    client = viewer(f"--port={port}", port=port)
    assert client.get("/").status_code == 200


# Spec: `--host=<host>` | Override bind host
def test_host_option_overrides_the_bind_host(viewer):
    client = viewer("--host=0.0.0.0")
    assert client.get("/").status_code == 200


# Spec: `serve` without `<name>` | Start server and open browser to `/`
def test_serve_without_name_opens_the_landing_page(viewer):
    client = viewer()
    assert client.opened_urls() == [client.base_url + "/"]


# Spec: `serve <name>` | Start server and open browser to default category page
# for vault
def test_serve_with_name_opens_the_default_category_page(viewer, vaults):
    vaults(v=v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]))
    client = viewer("v")
    assert client.opened_urls() == [client.base_url + "/catalog/v/episodes"]


# Spec: `serve <name>` ... default category page for vault (version aware)
def test_serve_with_a_v1_name_opens_the_entries_page(viewer, vaults):
    vaults(v=v1_catalog([v1_entry("a")]))
    client = viewer("v")
    assert client.opened_urls() == [client.base_url + "/catalog/v/entries"]


# Spec: `GET` | `/` | HTML page containing a form input for vault name
def test_landing_page_is_html(viewer):
    response = viewer().get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]


# Spec: `GET` | `/` | HTML page containing a form input for vault name
def test_landing_page_has_a_form_input_for_the_vault_name(viewer):
    body = viewer().get("/").text
    assert "<form" in body
    assert 'name="catalog"' in body


# Spec: `POST` | `/` | Accept form-encoded body; redirect to `/catalog/<value>`
# when `catalog` field is present
def test_post_redirects_to_the_named_catalog(viewer, vaults):
    vaults(v=v3_catalog(SOURCE_URL))
    response = viewer().post("/", {"catalog": "v"}, follow=False)
    assert location(response) == "/catalog/v"


# Spec: `POST` | `/` | ... otherwise redirect to `/`
# Spec: Missing `catalog` field on `POST /` | Redirect to `/`
def test_post_without_the_catalog_field_redirects_to_the_landing_page(viewer):
    response = viewer().post("/", {"other": "v"}, follow=False)
    assert location(response) == "/"


# Spec: Redirect status | HTTP `302` or `303`
def test_post_redirect_uses_a_redirect_status(viewer):
    response = viewer().post("/", {"catalog": "v"}, follow=False)
    assert response.status_code in (302, 303)


# Spec: Trigger | Navigation to any vault through viewer
# Spec: Display location | Landing page
def test_visited_vault_appears_on_the_landing_page(viewer, vaults):
    vaults(v=v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]))
    client = viewer()
    client.get("/catalog/v/episodes")
    assert "v" in recent_names(client.get("/").text)


# Spec: Link target | Each recent-vault link points directly to that vault's
# resolved default category page
def test_recent_vault_link_points_at_the_default_category_page(viewer, vaults):
    vaults(v=v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]))
    client = viewer()
    client.get("/catalog/v/episodes")
    assert "/catalog/v/episodes" in recent_links(client.get("/").text)


# Spec: Recent-vault links on `/` | Use the same resolved default-category route
# as `/catalog/<name>` would redirect to (v1 resolves to `entries`)
def test_recent_vault_link_is_version_aware(viewer, vaults):
    vaults(v=v1_catalog([v1_entry("a")]))
    client = viewer()
    client.get("/catalog/v")
    assert "/catalog/v/entries" in recent_links(client.get("/").text)


# Spec: Ordering | Most recently visited first
def test_recent_vaults_are_ordered_most_recent_first(viewer, vaults):
    vaults(one=v3_catalog(SOURCE_URL), two=v3_catalog(SOURCE_URL))
    client = viewer()
    client.get("/catalog/one/episodes")
    client.get("/catalog/two/episodes")
    assert recent_names(client.get("/").text)[:2] == ["two", "one"]


# Spec: Ordering | Most recently visited first (a revisit moves a vault back up)
def test_revisiting_a_vault_moves_it_to_the_front(viewer, vaults):
    vaults(one=v3_catalog(SOURCE_URL), two=v3_catalog(SOURCE_URL))
    client = viewer()
    client.get("/catalog/one/episodes")
    client.get("/catalog/two/episodes")
    client.get("/catalog/one/episodes")
    assert recent_names(client.get("/").text)[:2] == ["one", "two"]


# Spec: Persistence | Later browser session from same browser must still show
# visited vault
def test_recent_vaults_survive_a_later_browser_session(viewer, vaults):
    vaults(v=v3_catalog(SOURCE_URL))
    first = viewer()
    first.get("/catalog/v/episodes")
    later = viewer()
    later.forget_cookies()
    assert "v" in recent_names(later.get("/").text)


# Spec: Empty state | Area may be empty or absent
def test_landing_page_without_visits_lists_no_vaults(viewer):
    assert recent_names(viewer().get("/").text) == []


# Spec: Non-existent vault on any `/catalog/<name>` route | Redirect to `/`
def test_missing_vault_redirects_to_the_landing_page(viewer):
    response = viewer().get("/catalog/nope", follow=False)
    assert location(response).startswith("/")
    assert location(response).split("?")[0] == "/"


# Spec: Non-existent vault ... | landing page shows vault-not-found indication
def test_missing_vault_shows_a_not_found_indication(viewer):
    response = viewer().get("/catalog/nope")
    assert response.status_code == 200
    assert "not found" in response.text.lower()


# Spec: Non-existent vault ... | response must not be HTTP `500`
@pytest.mark.parametrize("path", ["/catalog/nope", "/catalog/nope/episodes", "/catalog/nope/episodes/a"])
def test_missing_vault_is_never_a_server_error(viewer, path):
    assert viewer().get(path).status_code != 500


# Spec: Non-existent vault ... (an unreadable catalog is no server error either)
def test_unreadable_catalog_is_never_a_server_error(viewer, make_vault):
    make_vault("{ not json", "broken")
    assert viewer().get("/catalog/broken/episodes").status_code != 500


# Spec: Any HTTP error | Well-formed HTTP response; no raw exception or stack
# trace exposure
@pytest.mark.parametrize("path", ["/catalog/nope", "/nothing/here", "/catalog/v/bogus/x/y/z"])
def test_errors_expose_no_stack_trace(viewer, path):
    response = viewer().get(path)
    assert response.status_code != 500
    assert "Traceback" not in response.text


# Spec: Any HTTP error | Well-formed HTTP response (unknown paths answer with a
# status and a body)
def test_unknown_path_is_a_well_formed_response(viewer):
    response = viewer().get("/nothing/here")
    assert response.status_code == 404
    assert "text/html" in response.headers["Content-Type"]
    assert response.text


def recent_names(html):
    """Vault names listed in the landing page's recent-vaults area."""
    return [link.split("/catalog/", 1)[1].split("/")[0] for link in recent_links(html)]


def recent_links(html):
    """`/catalog/...` hrefs on the landing page, in document order."""
    return re.findall(r'href="(/catalog/[^"]+)"', html)
