"""Spec: the `/` Routes table."""
from urllib.parse import quote

from digest_helpers import v3, v3_entry
from viewer_helpers import hrefs, tags


# Spec: "| `GET` | `/` | HTML page containing a form input for vault name |"
def test_get_root_returns_html(serve):
    response = serve().get("/")
    assert response.status == 200
    content_type = dict((k.lower(), v) for k, v in response.headers)
    assert "html" in content_type.get("content-type", "")
    assert "<html" in response.body.lower()


# Spec: "| `GET` | `/` | HTML page containing a form input for vault name |"
def test_landing_page_has_a_form_input(serve):
    body = serve().get("/").body
    assert "<form" in body.lower()
    inputs = tags(body, "input")
    assert inputs, body
    # The POST route reads a `catalog` field, so the input must carry that name.
    assert any(item.get("name") == "catalog" for item in inputs), inputs


# Spec: "| `POST` | `/` | Accept form-encoded body; redirect to
# `/catalog/<value>` when `catalog` field is present ... |"
def test_post_root_redirects_to_catalog_value(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().post("/", fields={"catalog": "vault"})
    assert response.is_redirect, response
    assert response.location == "/catalog/vault"


# Spec: "| `POST` | `/` | Accept form-encoded body ... |" -- the body is read
# as `application/x-www-form-urlencoded`, so values are URL-decoded.
def test_post_root_url_decodes_the_value(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="my vault")
    response = serve().post("/", fields={"catalog": "my vault"})
    assert response.is_redirect, response
    assert response.location in ("/catalog/my vault",
                                "/catalog/%s" % quote("my vault"))


# Spec: "| `POST` | `/` | ... otherwise redirect to `/` |"
def test_post_root_without_catalog_field_redirects_to_root(serve):
    response = serve().post("/", fields={"other": "x"})
    assert response.is_redirect, response
    assert response.location == "/"


# Spec: "| Missing `catalog` field on `POST /` | Redirect to `/` |" -- an
# entirely empty body is the same case.
def test_post_root_with_empty_body_redirects_to_root(serve):
    response = serve().post("/", raw="")
    assert response.is_redirect, response
    assert response.location == "/"


# Spec: "| `POST` | `/` | Accept form-encoded body ... |" -- the redirect a
# POST produces leads, when followed, to a real page rather than an error.
def test_post_root_redirect_is_followable(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep One")]))
    response = serve().post("/", fields={"catalog": "vault"}, follow=True)
    assert response.status == 200, response
    assert "Ep One" in response.body


# Spec: "| Redirect status | HTTP `302` or `303` |" -- for the POST route.
def test_post_redirect_status_is_302_or_303(serve, make_vault):
    make_vault(v3())
    server = serve()
    assert server.post("/", fields={"catalog": "vault"}).status in (302, 303)
    assert server.post("/", fields={}).status in (302, 303)


# Spec: "| `GET` | `/` | HTML page ... |" -- the landing page is reachable and
# well-formed even when no vault exists in the working directory at all.
def test_landing_page_works_with_no_vaults(serve):
    response = serve().get("/")
    assert response.status == 200
    assert "Traceback" not in response.body


# Spec: "| Empty state | Area may be empty or absent |" -- a fresh server has
# no recent-vault links.
def test_landing_page_empty_recent_state(serve):
    body = serve().get("/").body
    assert [href for href in hrefs(body) if href.startswith("/catalog/")] == []
