"""Spec section: `/` Routes -- the landing page and its form submission."""

from conftest import REDIRECT_STATUSES, v3_catalog, v3_entry, write_vault


# Phrase: "| `GET` | `/` | HTML page containing a form input for vault name |".
def test_landing_page_is_html_with_a_form_input(viewer):
    response = viewer.client.get("/")

    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/html")
    assert "<form" in response.body
    assert "<input" in response.body


# Phrase: "| `POST` | `/` | Accept form-encoded body; redirect to
# `/catalog/<value>` when `catalog` field is present |".
def test_post_with_catalog_field_redirects_to_that_vault(viewer):
    response = viewer.client.post("/", {"catalog": "demo"})

    assert response.status in REDIRECT_STATUSES
    assert response.location == "/catalog/demo"


# Phrase: "| `POST` | `/` | ... otherwise redirect to `/` |".
def test_post_without_catalog_field_redirects_to_the_landing_page(viewer):
    response = viewer.client.post("/", {"other": "demo"})

    assert response.status in REDIRECT_STATUSES
    assert response.location == "/"


# Phrase: "redirect to `/catalog/<value>` when `catalog` field is present" --
# the submitted value drives a real navigation, reaching the vault listing.
def test_submitted_vault_name_reaches_the_listing(viewer, tmp_path):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")]))

    submitted = viewer.client.post("/", {"catalog": "demo"})
    landed = viewer.client.follow(submitted.location)

    assert landed.status == 200
    assert "title-e1" in landed.body
