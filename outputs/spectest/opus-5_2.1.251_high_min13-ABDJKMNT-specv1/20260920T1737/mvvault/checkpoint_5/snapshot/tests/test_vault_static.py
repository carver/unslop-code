"""Spec sections: `/vault` Static File Endpoints and Static File Safety Rules."""

import pytest
from conftest import write_media, write_previews
from detail_fixtures import v1_vault, v3_vault

TRAVERSAL_STATUSES = (403, 404)


# Phrase: "| `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>`
# with an appropriate media MIME type |".
def test_media_endpoint_serves_the_named_file(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_media(vault, "e1.mp4")

    response = viewer.client.get("/vault/demo/media/e1.mp4")

    assert response.status == 200
    assert response.body == "media-bytes"


# Phrase: "... with an appropriate media MIME type |".
def test_media_endpoint_sends_a_media_mime_type(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_media(vault, "e1.mp4")

    content_type = viewer.client.get("/vault/demo/media/e1.mp4").headers["Content-Type"]

    assert content_type.startswith("video/")


# Phrase: "| `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview
# image from `<vault>/previews/` whose saved filename contains `<id>` ... |".
def test_preview_endpoint_serves_the_matching_image(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_previews(vault, "e1.jpg")

    response = viewer.client.get("/vault/demo/preview/e1")

    assert response.status == 200
    assert response.body == "preview-bytes"


# Phrase: "| Preview lookup | `/vault/<name>/preview/<id>` resolves the saved
# preview asset whose filename contains the requested `id` |".
def test_preview_lookup_matches_a_filename_containing_the_id(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_previews(vault, "thumb-e1-large.png")

    assert viewer.client.get("/vault/demo/preview/e1").status == 200


# Phrase: "... with an appropriate image MIME type |".
@pytest.mark.parametrize("filename", ["e1.jpg", "e1.png"])
def test_preview_endpoint_sends_an_image_mime_type(viewer, tmp_path, filename):
    vault = v3_vault(tmp_path)
    write_previews(vault, filename)

    content_type = viewer.client.get("/vault/demo/preview/e1").headers["Content-Type"]

    assert content_type.startswith("image/")


# Phrase: "| Preview lookup | ... whose filename contains the requested `id` |"
# -- a preview stored for another entry is not served.
def test_preview_of_another_entry_is_not_served(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_previews(vault, "s1.jpg")

    assert viewer.client.get("/vault/demo/preview/e1").status == 404


# Phrase: "| `GET` | `/vault/<name>/media/<file>` | ... |" -- the endpoints work
# for a vault of any supported version.
def test_media_endpoint_works_for_a_v1_vault(viewer, tmp_path):
    vault = v1_vault(tmp_path)
    write_media(vault, "e1.mp4")

    assert viewer.client.get("/vault/demo/media/e1.mp4").status == 200


# Phrase: "| Path traversal | Requests containing traversal sequences must not
# escape `media/` or `previews/` |".
@pytest.mark.parametrize(
    "path",
    [
        "/vault/demo/media/..%2f..%2fcatalog.json",
        "/vault/demo/media/%2e%2e%2f%2e%2e%2fsecret.txt",
        "/vault/demo/preview/..%2f..%2fcatalog.json",
        "/vault/demo/media/%2fetc%2fpasswd",
    ],
)
def test_traversal_requests_do_not_escape(viewer, tmp_path, path):
    v3_vault(tmp_path)
    (tmp_path / "secret.txt").write_text("secret")

    response = viewer.client.get(path)

    assert response.status in TRAVERSAL_STATUSES
    assert "secret" not in response.body
    assert "version" not in response.body


# Phrase: "| Path traversal | ... must not escape `media/` or `previews/` |" --
# a traversal that would land on a real file outside the vault is refused.
def test_traversal_never_serves_a_file_outside_the_asset_directory(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_media(vault, "e1.mp4")
    (vault / "outside.txt").write_text("outside-bytes")

    response = viewer.client.get("/vault/demo/media/..%2foutside.txt")

    assert response.status in TRAVERSAL_STATUSES
    assert "outside-bytes" not in response.body
