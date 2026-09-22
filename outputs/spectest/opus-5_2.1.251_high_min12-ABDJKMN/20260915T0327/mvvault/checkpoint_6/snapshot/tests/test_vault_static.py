"""Spec sections: `/vault` Static File Endpoints, `/vault` Static File Safety
Rules, HTTP Error Handling, and the Determinism rows for downloaded media and
preview lookup."""
import pytest

from conftest import v1_catalog, v1_entry, v3_catalog, v3_entry
from detailhelp import build_vault, detail

REDIRECTS = (302, 303)
BLOCKED = (403, 404)


@pytest.fixture
def stocked(tmp_path):
    """A v3 vault with one archived media file and one preview image."""
    return build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1"),
                                                      v3_entry("e2")]),
                       media=["e1.mp4"], previews=["e1.jpg"])


# ---------------------------------------------------------------------------
# `/vault` Static File Endpoints
# ---------------------------------------------------------------------------

# --- Phrase: "| `GET` | `/vault/<name>/media/<file>` | Serve
#     `<vault>/media/<file>` with an appropriate media MIME type |"
def test_media_endpoint_serves_the_file(viewer, stocked):
    response = viewer().get("/vault/vault/media/e1.mp4")
    assert response.status == 200, response
    assert response.body == b"media-bytes-e1.mp4", response


def test_media_endpoint_uses_a_media_mime_type(viewer, stocked):
    response = viewer().get("/vault/vault/media/e1.mp4")
    content_type = response.headers.get("Content-Type", "")
    assert content_type.startswith("video/"), content_type


def test_media_endpoint_serves_an_audio_file(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]),
                media=["e1.m4a"])
    response = viewer().get("/vault/vault/media/e1.m4a")
    assert response.status == 200, response
    content_type = response.headers.get("Content-Type", "")
    assert content_type.split("/")[0] in ("audio", "video", "application"), (
        content_type)


def test_media_endpoint_serves_a_file_whose_name_only_contains_the_id(
        viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]),
                media=["prefix-e1-suffix.mp4"])
    response = viewer().get("/vault/vault/media/prefix-e1-suffix.mp4")
    assert response.status == 200, response
    assert response.body == b"media-bytes-prefix-e1-suffix.mp4", response


# --- Phrase: "| Downloaded media reference | When rendered, the detail page
#     uses the matched saved filename in `/vault/<name>/media/<file>` |"
def test_detail_media_link_is_fetchable(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]),
                media=["e1-archived.mp4"])
    client = viewer()
    text = detail(client, "vault", "episodes", "e1").text
    assert "/vault/vault/media/e1-archived.mp4" in text, text
    response = client.get("/vault/vault/media/e1-archived.mp4")
    assert response.status == 200, response


# --- Phrase: "| `GET` | `/vault/<name>/preview/<id>` | Serve the matching
#     preview image from `<vault>/previews/` whose saved filename contains
#     `<id>`, with an appropriate image MIME type |"
def test_preview_endpoint_serves_the_matching_image(viewer, stocked):
    response = viewer().get("/vault/vault/preview/e1")
    assert response.status == 200, response
    assert response.body.endswith(b"e1.jpg"), response


def test_preview_endpoint_uses_an_image_mime_type(viewer, stocked):
    response = viewer().get("/vault/vault/preview/e1")
    content_type = response.headers.get("Content-Type", "")
    assert content_type.startswith("image/"), content_type


# --- Phrase: "| Preview lookup | `/vault/<name>/preview/<id>` resolves the
#     saved preview asset whose filename contains the requested `id` |"
def test_preview_lookup_matches_a_filename_containing_the_id(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]),
                previews=["preview-e1-thumb.png"])
    response = viewer().get("/vault/vault/preview/e1")
    assert response.status == 200, response
    assert response.body.endswith(b"preview-e1-thumb.png"), response


def test_preview_lookup_ignores_other_entries_files(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1"),
                                               v3_entry("e2")]),
                previews=["e2.jpg"])
    response = viewer().get("/vault/vault/preview/e1")
    assert response.status == 404, response


def test_preview_lookup_is_deterministic(viewer, stocked):
    client = viewer()
    first = client.get("/vault/vault/preview/e1")
    second = client.get("/vault/vault/preview/e1")
    assert first.body == second.body
    assert first.status == second.status == 200


def test_preview_endpoint_works_for_a_v1_vault(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]),
                previews=["e1.jpg"])
    response = viewer().get("/vault/vault/preview/e1")
    assert response.status == 200, response


# ---------------------------------------------------------------------------
# `/vault` Static File Safety Rules
# ---------------------------------------------------------------------------

# --- Phrase: "| Path traversal | Requests containing traversal sequences must
#     not escape `media/` or `previews/` |" + "| Path traversal attempt |
#     HTTP `403` or HTTP `404` |"
@pytest.mark.parametrize("path", [
    "/vault/vault/media/..%2f..%2fcatalog.json",
    "/vault/vault/media/%2e%2e%2f%2e%2e%2fcatalog.json",
    "/vault/vault/media/../../catalog.json",
    "/vault/vault/media/..%2fprevious%2fe1.jpg",
    "/vault/vault/preview/..%2f..%2fcatalog.json",
    "/vault/vault/preview/%2e%2e%2fcatalog",
    "/vault/vault/media/%2e%2e",
    "/vault/../vault/media/e1.mp4",
])
def test_traversal_attempts_are_refused(viewer, stocked, path):
    response = viewer().get(path)
    assert response.status in BLOCKED or response.status in REDIRECTS, response
    assert b'"version"' not in response.body, response
    assert b"episodes" not in response.body, response


def test_traversal_does_not_expose_the_catalog(viewer, stocked):
    response = viewer().get("/vault/vault/media/..%2fcatalog.json")
    assert response.status in BLOCKED, response
    assert "episodes" not in response.text, response


def test_absolute_path_request_is_refused(viewer, stocked):
    response = viewer().get("/vault/vault/media//etc/passwd")
    assert response.status in BLOCKED, response


# ---------------------------------------------------------------------------
# HTTP Error Handling
# ---------------------------------------------------------------------------

# --- Phrase: "| Non-existent media file | HTTP `404` |"
def test_missing_media_file_is_404(viewer, stocked):
    response = viewer().get("/vault/vault/media/nope.mp4")
    assert response.status == 404, response


def test_missing_media_directory_is_404(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = viewer().get("/vault/vault/media/e1.mp4")
    assert response.status == 404, response


# --- Phrase: "| Non-existent preview image | HTTP `404` |"
def test_missing_preview_image_is_404(viewer, stocked):
    response = viewer().get("/vault/vault/preview/nope")
    assert response.status == 404, response


def test_missing_previews_directory_is_404(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = viewer().get("/vault/vault/preview/e1")
    assert response.status == 404, response


# --- Phrase: "| Non-existent vault on detail or static route | Redirect to
#     landing page with vault-not-found indication |"
@pytest.mark.parametrize("path", ["/vault/ghost/media/e1.mp4",
                                  "/vault/ghost/preview/e1"])
def test_missing_vault_on_a_static_route_redirects_to_the_landing_page(
        viewer, path):
    response = viewer().get(path)
    assert response.status in REDIRECTS, response
    assert not response.location.startswith("/vault"), response


def test_missing_vault_static_redirect_indicates_not_found(viewer):
    client = viewer()
    response = client.get("/vault/ghost/media/e1.mp4", follow=True)
    assert response.status == 200, response
    assert "ghost" in response.text, response
    assert "not found" in response.text.lower(), response


# --- Phrase: "| Any HTTP error | Well-formed response; no raw stack trace or
#     internal detail exposure |"
@pytest.mark.parametrize("path", [
    "/vault",
    "/vault/",
    "/vault/vault",
    "/vault/vault/media",
    "/vault/vault/media/",
    "/vault/vault/bogus/e1",
    "/vault/vault/preview",
    "/vault/vault/media/e1.mp4/extra",
])
def test_odd_static_paths_stay_well_formed(viewer, stocked, path):
    response = viewer().get(path)
    assert response.status != 500, response
    assert "Traceback" not in response.text, response
    assert response.headers.get("Content-Type"), response


def test_server_stays_up_after_bad_static_requests(viewer, stocked):
    client = viewer()
    for path in ("/vault/ghost/media/x", "/vault/vault/media/..%2f..%2fx",
                 "/vault/vault/preview/zzz"):
        client.get(path)
    assert client.get("/vault/vault/media/e1.mp4").status == 200
