"""Spec sections: the `/vault` static file endpoints, their safety rules, and
the HTTP error handling of the detail and static routes."""

import pytest
from conftest import (
    place_media,
    place_preview,
    v3_catalog,
    v3_entry,
    write_vault,
)

REDIRECTS = (302, 303)
SOURCE = "https://example.test/a"

# Traversal spelled both ways a browser can send it: raw, and percent-encoded
# so the path only becomes a traversal once the segment is decoded.
TRAVERSALS = ["../../catalog.json", "..%2F..%2Fcatalog.json", "%2e%2e%2f%2e%2e%2fcatalog.json"]


@pytest.fixture
def stocked_vault(tmp_path):
    """A v3 vault holding one entry with a saved media file and preview."""
    vault = write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("e1")]))
    place_media(vault, "e1.mp4", b"movie-bytes")
    place_preview(vault, "preview-e1.jpg", b"image-bytes")
    return vault


# `/vault` Static File Endpoints: "`GET` | `/vault/<name>/media/<file>` | Serve
# `<vault>/media/<file>` with an appropriate media MIME type".
def test_media_endpoint_serves_the_stored_file(viewer, stocked_vault):
    response = viewer.get("/vault/demo/media/e1.mp4")

    assert response.status == 200
    assert response.body == "movie-bytes"
    assert response.headers["Content-Type"] == "video/mp4"


# `/vault` Static File Endpoints: "`GET` | `/vault/<name>/preview/<id>` | Serve
# the matching preview image from `<vault>/previews/` whose saved filename
# contains `<id>`, with an appropriate image MIME type".
def test_preview_endpoint_serves_the_matching_image(viewer, stocked_vault):
    response = viewer.get("/vault/demo/preview/e1")

    assert response.status == 200
    assert response.body == "image-bytes"
    assert response.headers["Content-Type"].startswith("image/")


# Determinism: "Preview lookup | `/vault/<name>/preview/<id>` resolves the
# saved preview asset whose filename contains the requested `id`".
def test_preview_lookup_matches_a_filename_containing_the_id(viewer, tmp_path):
    vault = write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("e1")]))
    place_preview(vault, "thumb-e1-large.png", b"png-bytes")

    response = viewer.get("/vault/demo/preview/e1")

    assert response.status == 200
    assert response.body == "png-bytes"


# `/vault` Static File Safety Rules: "Path traversal | Requests containing
# traversal sequences must not escape `media/` or `previews/`".
@pytest.mark.parametrize("attempt", TRAVERSALS)
def test_media_endpoint_refuses_traversal(viewer, stocked_vault, attempt):
    response = viewer.get(f"/vault/demo/media/{attempt}")

    assert response.status in (403, 404)
    assert '"version"' not in response.body


@pytest.mark.parametrize("attempt", TRAVERSALS)
def test_preview_endpoint_refuses_traversal(viewer, stocked_vault, attempt):
    response = viewer.get(f"/vault/demo/preview/{attempt}")

    assert response.status in (403, 404)
    assert '"version"' not in response.body


# `/vault` Static File Safety Rules: "Path traversal ... must not escape
# `media/`" — an absolute path is not a way out either.
def test_media_endpoint_refuses_an_absolute_path(viewer, stocked_vault):
    response = viewer.get("/vault/demo/media/%2Fetc%2Fhostname")

    assert response.status in (403, 404)


# HTTP Error Handling: "Non-existent media file | HTTP `404`".
def test_missing_media_file_is_not_found(viewer, stocked_vault):
    response = viewer.get("/vault/demo/media/absent.mp4")

    assert response.status == 404
    assert "Traceback" not in response.body


# HTTP Error Handling: "Non-existent preview image | HTTP `404`".
def test_missing_preview_image_is_not_found(viewer, stocked_vault):
    response = viewer.get("/vault/demo/preview/absent")

    assert response.status == 404
    assert "Traceback" not in response.body


# HTTP Error Handling: "Non-existent media file | HTTP `404`" — a vault with no
# media directory at all answers the same way.
def test_media_endpoint_without_a_media_directory_is_not_found(viewer, tmp_path):
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("e1")]))

    assert viewer.get("/vault/demo/media/e1.mp4").status == 404


# HTTP Error Handling: "Missing entry in specified category | HTTP `404`, or
# redirect to category listing with error indication".
def test_missing_entry_is_refused(viewer, tmp_path):
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("e1")]))

    response = viewer.get("/catalog/demo/episodes/absent")

    assert response.status == 404 or (
        response.status in REDIRECTS and response.location == "/catalog/demo/episodes"
    )
    assert "Traceback" not in response.body


# HTTP Error Handling: "Non-existent vault on detail or static route | Redirect
# to landing page with vault-not-found indication".
@pytest.mark.parametrize(
    "path",
    [
        "/catalog/ghost/episodes/e1",
        "/vault/ghost/media/e1.mp4",
        "/vault/ghost/preview/e1",
    ],
)
def test_non_existent_vault_returns_to_the_landing_page(viewer, tmp_path, path):
    response = viewer.get(path)

    assert response.status in REDIRECTS
    assert response.location == "/"
    assert "ghost" in viewer.get("/").body


# HTTP Error Handling: "Invalid category on detail route | Same handling allowed
# as invalid category listing route".
def test_invalid_category_on_the_detail_route_is_handled_like_a_listing(viewer, tmp_path):
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("e1")]))

    detail = viewer.get("/catalog/demo/nonsense/e1")
    listing = viewer.get("/catalog/demo/nonsense")

    assert detail.status == listing.status
    assert detail.location == listing.location
    assert "Traceback" not in detail.body


# HTTP Error Handling: "Any HTTP error | Well-formed response; no raw stack
# trace or internal detail exposure".
@pytest.mark.parametrize(
    "path",
    [
        "/vault",
        "/vault/demo",
        "/vault/demo/media",
        "/vault/demo/archive/e1.mp4",
        "/vault/demo/media/nested/e1.mp4",
        "/catalog/demo/episodes/e1/extra",
    ],
)
def test_unroutable_vault_paths_are_well_formed(viewer, stocked_vault, path):
    response = viewer.get(path)

    assert response.status in REDIRECTS + (400, 403, 404)
    assert "Traceback" not in response.body
    assert "movie-bytes" not in response.body
