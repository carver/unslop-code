"""`/vault` static file endpoints, their safety rules and the viewer's HTTP errors."""

import pytest

from conftest import ASSET_BYTES, SOURCE_URL, v1_catalog, v1_entry, v3_catalog, v3_entry

#: A catalog with one downloadable entry, used by most of the static tests.
ONE_ENTRY = v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])


def bounces_to_landing(response):
    """Whether a response is the redirect a missing vault is answered with."""
    return response.status_code in (302, 303) and response.headers["Location"] == "/"


# Spec: `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>`
def test_media_endpoint_serves_the_stored_file(served):
    response = served(ONE_ENTRY, media=["a.mp4"]).get("/vault/v/media/a.mp4")
    assert response.status_code == 200
    assert response.content == ASSET_BYTES


# Spec: `GET` | `/vault/<name>/media/<file>` | ... with an appropriate media
# MIME type
def test_media_endpoint_sends_a_media_mime_type(served):
    response = served(ONE_ENTRY, media=["a.mp4"]).get("/vault/v/media/a.mp4")
    assert response.headers["Content-Type"] == "video/mp4"


# Spec: `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview image
# from `<vault>/previews/` whose saved filename contains `<id>`
def test_preview_endpoint_serves_the_matching_image(served):
    response = served(ONE_ENTRY, previews=["a.jpg"]).get("/vault/v/preview/a")
    assert response.status_code == 200
    assert response.content == ASSET_BYTES


# Spec: Preview lookup | `/vault/<name>/preview/<id>` resolves the saved preview
# asset whose filename contains the requested `id`
def test_preview_lookup_matches_a_decorated_filename(served):
    response = served(ONE_ENTRY, previews=["prefix-a-suffix.png"]).get("/vault/v/preview/a")
    assert response.status_code == 200
    assert response.content == ASSET_BYTES


# Spec: `GET` | `/vault/<name>/preview/<id>` | ... with an appropriate image
# MIME type
@pytest.mark.parametrize("filename, media_type", [("a.jpg", "image/jpeg"), ("a.png", "image/png")])
def test_preview_endpoint_sends_an_image_mime_type(served, filename, media_type):
    response = served(ONE_ENTRY, previews=[filename]).get("/vault/v/preview/a")
    assert response.headers["Content-Type"] == media_type


# Spec: Path traversal | Requests containing traversal sequences must not escape
# `media/` or `previews/`
@pytest.mark.parametrize(
    "path",
    [
        "/vault/v/media/../catalog.json",
        "/vault/v/media/..%2Fcatalog.json",
        "/vault/v/media/..%2F..%2Fsecret.txt",
        "/vault/v/media/%2e%2e%2fcatalog.json",
        "/vault/v/preview/../catalog.json",
        "/vault/v/preview/..%2Fcatalog.json",
    ],
)
def test_traversal_requests_do_not_escape_the_asset_directories(served, path, tmp_path):
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    response = served(ONE_ENTRY, media=["a.mp4"], previews=["a.jpg"]).get(path, follow=False)
    assert response.status_code in (403, 404)
    assert "secret" not in response.text
    assert "catalog" not in response.text


# Spec: Path traversal attempt | HTTP `403` or HTTP `404`
def test_a_traversal_attempt_is_refused(served):
    response = served(ONE_ENTRY, media=["a.mp4"]).get("/vault/v/media/..%2Fcatalog.json", follow=False)
    assert response.status_code in (403, 404)


# Spec: Non-existent media file | HTTP `404`
def test_a_missing_media_file_is_not_found(served):
    assert served(ONE_ENTRY, media=["a.mp4"]).get("/vault/v/media/b.mp4").status_code == 404


# Spec: Non-existent media file | HTTP `404` (a vault with no media directory)
def test_a_vault_without_a_media_directory_is_not_found(served):
    assert served(ONE_ENTRY).get("/vault/v/media/a.mp4").status_code == 404


# Spec: Non-existent preview image | HTTP `404`
def test_a_missing_preview_image_is_not_found(served):
    assert served(ONE_ENTRY, previews=["a.jpg"]).get("/vault/v/preview/b").status_code == 404


# Spec: Non-existent preview image | HTTP `404` (a vault with no previews directory)
def test_a_vault_without_a_previews_directory_is_not_found(served):
    assert served(ONE_ENTRY).get("/vault/v/preview/a").status_code == 404


# Spec: Non-existent vault on detail or static route | Redirect to landing page
# with vault-not-found indication
@pytest.mark.parametrize(
    "path",
    ["/catalog/ghost/episodes/a", "/vault/ghost/media/a.mp4", "/vault/ghost/preview/a"],
)
def test_a_missing_vault_bounces_to_the_landing_page(served, path):
    client = served(ONE_ENTRY)
    assert bounces_to_landing(client.get(path, follow=False))
    assert "ghost" in client.get(path).text


# Spec: Missing entry in specified category | HTTP `404`, or redirect to
# category listing with error indication
def test_a_missing_entry_is_reported(served):
    response = served(ONE_ENTRY).get("/catalog/v/episodes/nope", follow=False)
    assert response.status_code == 404 or response.headers.get("Location", "").startswith("/catalog/v/episodes")


# Spec: Invalid category on detail route | Same handling allowed for invalid
# category listing route
def test_an_invalid_category_on_the_detail_route(served):
    response = served(ONE_ENTRY).get("/catalog/v/entries/a", follow=False)
    assert response.status_code in (302, 303, 400, 404)
    if response.status_code in (302, 303):
        assert response.headers["Location"] == "/catalog/v/episodes"


# Spec: Invalid category on detail route | Same handling ... (v1 vault)
def test_an_invalid_category_on_the_detail_route_of_a_v1_vault(served):
    response = served(v1_catalog([v1_entry("a")])).get("/catalog/v/episodes/a", follow=False)
    assert response.status_code in (302, 303, 400, 404)
    if response.status_code in (302, 303):
        assert response.headers["Location"] == "/catalog/v/entries"


# Spec: Any HTTP error | Well-formed response; no raw stack trace or internal
# detail exposure
@pytest.mark.parametrize(
    "path",
    [
        "/catalog/v/episodes/nope",
        "/vault/v/media/b.mp4",
        "/vault/v/preview/b",
        "/vault/v/media/..%2Fcatalog.json",
        "/vault/v",
        "/vault",
        "/nonsense",
    ],
)
def test_error_responses_expose_nothing_internal(served, path):
    response = served(ONE_ENTRY, media=["a.mp4"], previews=["a.jpg"]).get(path, follow=False)
    assert response.status_code != 500
    for leak in ("Traceback", "File \"/", "mvaultlib", "Exception"):
        assert leak not in response.text


# Spec: Any HTTP error | Well-formed response (an error page is HTML)
def test_error_responses_are_well_formed_html(served):
    response = served(ONE_ENTRY).get("/catalog/v/episodes/nope")
    assert response.status_code == 404
    assert "text/html" in response.headers["Content-Type"]
    assert response.text.startswith("<!DOCTYPE html>")
