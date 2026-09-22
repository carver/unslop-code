"""Spec sections: `/vault` Static File Endpoints and `/vault` Static File Safety
Rules."""

from conftest import (
    add_media,
    add_previews,
    is_redirect,
    v3_catalog,
    v3_entry,
    write_vault,
)


def vault_with_assets(tmp_path, media=(), previews=()):
    """A one-entry v3 vault holding the named downloaded files."""
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    add_media(vault_dir, *media)
    add_previews(vault_dir, *previews)
    return vault_dir


# Spec: `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>`
def test_media_endpoint_serves_the_stored_file(serve, tmp_path):
    vault_with_assets(tmp_path, media=["e1.mp4"])
    response = serve().get("/vault/vault/media/e1.mp4")
    assert response.status_code == 200
    assert response.content == b"media-bytes"


# Spec: `GET` | `/vault/<name>/media/<file>` | ... with an appropriate media
# MIME type
def test_media_endpoint_sends_a_media_mime_type(serve, tmp_path):
    vault_with_assets(tmp_path, media=["e1.mp4"])
    response = serve().get("/vault/vault/media/e1.mp4")
    assert response.headers["Content-Type"].startswith("video/")


# Spec: `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview image
# from `<vault>/previews/`
def test_preview_endpoint_serves_the_matching_image(serve, tmp_path):
    vault_with_assets(tmp_path, previews=["e1.png"])
    response = serve().get("/vault/vault/preview/e1")
    assert response.status_code == 200
    assert response.content == b"preview-bytes"


# Spec: `GET` | `/vault/<name>/preview/<id>` | ... whose saved filename contains
# `<id>`
def test_preview_is_matched_by_a_filename_containing_the_id(serve, tmp_path):
    vault_with_assets(tmp_path, previews=["thumb-e1-small.png"])
    assert serve().get("/vault/vault/preview/e1").status_code == 200


# Spec: `GET` | `/vault/<name>/preview/<id>` | ... with an appropriate image
# MIME type
def test_preview_endpoint_sends_an_image_mime_type(serve, tmp_path):
    vault_with_assets(tmp_path, previews=["e1.png"])
    response = serve().get("/vault/vault/preview/e1")
    assert response.headers["Content-Type"].startswith("image/")


# Spec: Path traversal | Requests containing traversal sequences must not escape
# `media/`
# Spec: Path traversal attempt | HTTP `403` or HTTP `404`
def test_encoded_traversal_out_of_media_is_refused(serve, tmp_path):
    vault_with_assets(tmp_path, media=["e1.mp4"])
    response = serve().get("/vault/vault/media/..%2Fcatalog.json")
    assert response.status_code in (403, 404)
    assert "episodes" not in response.text


# Spec: Path traversal | ... must not escape `media/`
def test_plain_traversal_out_of_media_is_refused(serve, tmp_path):
    vault_with_assets(tmp_path, media=["e1.mp4"])
    response = serve().get("/vault/vault/media/../../../etc/passwd")
    assert response.status_code in (403, 404)
    assert "root:" not in response.text


# Spec: Path traversal | ... must not escape `previews/`
def test_traversal_out_of_previews_is_refused(serve, tmp_path):
    vault_with_assets(tmp_path, previews=["e1.png"])
    response = serve().get("/vault/vault/preview/..%2F..%2Fcatalog.json")
    assert response.status_code in (403, 404)
    assert "episodes" not in response.text


# Spec: Non-existent media file | HTTP `404`
def test_missing_media_file_is_not_found(serve, tmp_path):
    vault_with_assets(tmp_path, media=["e1.mp4"])
    assert serve().get("/vault/vault/media/other.mp4").status_code == 404


# Spec: Non-existent media file | HTTP `404` (a vault that never downloaded any)
def test_media_endpoint_without_a_media_directory_is_not_found(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    assert serve().get("/vault/vault/media/e1.mp4").status_code == 404


# Spec: Non-existent preview image | HTTP `404`
def test_missing_preview_image_is_not_found(serve, tmp_path):
    vault_with_assets(tmp_path, previews=["e1.png"])
    assert serve().get("/vault/vault/preview/e2").status_code == 404


# Spec: Non-existent vault on detail or static route | Redirect to landing page
# with vault-not-found indication
def test_static_route_on_a_missing_vault_redirects_to_the_landing_page(serve):
    viewer = serve()
    assert is_redirect(viewer.get("/vault/ghost/media/e1.mp4"), "/")
    assert is_redirect(viewer.get("/vault/ghost/preview/e1"), "/")


# Spec: ... landing page shows vault-not-found indication
def test_static_route_on_a_missing_vault_names_it_on_the_landing_page(serve):
    body = serve().get("/vault/ghost/media/e1.mp4", follow=True).text
    assert "ghost" in body
    assert "not found" in body.lower()


# Spec: Preview lookup | `/vault/<name>/preview/<id>` resolves the saved preview
# asset whose filename contains the requested `id`
def test_preview_lookup_picks_the_asset_for_the_requested_id(serve, tmp_path):
    vault_with_assets(tmp_path, previews=["e1.png", "e2.png"])
    viewer = serve()
    assert viewer.get("/vault/vault/preview/e1").status_code == 200
    assert viewer.get("/vault/vault/preview/e2").status_code == 200


# Spec: Downloaded media reference | When rendered, the detail page uses the
# matched saved filename in `/vault/<name>/media/<file>`
def test_the_media_url_the_detail_page_renders_serves_the_file(serve, tmp_path):
    vault_with_assets(tmp_path, media=["archive-e1.webm"])
    viewer = serve()
    body = viewer.get("/catalog/vault/episodes/e1").text
    assert "/vault/vault/media/archive-e1.webm" in body
    assert viewer.get("/vault/vault/media/archive-e1.webm").status_code == 200
