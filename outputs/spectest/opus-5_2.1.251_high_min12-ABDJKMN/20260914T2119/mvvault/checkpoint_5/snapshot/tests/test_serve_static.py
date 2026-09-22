"""Spec: the `/vault` static file endpoints and their safety rules."""
import pytest

from digest_helpers import v1, v1_entry, v2, v3, v3_entry, legacy_entry


def content_type(response):
    for key, value in response.headers:
        if key.lower() == "content-type":
            return value
    return ""


# --------------------------------------------------------------------------
# Media endpoint
# --------------------------------------------------------------------------
# Spec: "| `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>`
# with an appropriate media MIME type |"
def test_media_endpoint_serves_the_file(serve, make_vault, save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("media", "e1.mp4", body=b"MEDIABYTES")
    response = serve().get("/vault/vault/media/e1.mp4")
    assert response.status == 200, response
    assert response.body == "MEDIABYTES"


# Spec: "| ... | ... with an appropriate media MIME type |"
@pytest.mark.parametrize("filename,expected", [
    ("e1.mp4", "video/mp4"),
    ("e1.webm", "video/webm"),
    ("e1.mp3", "audio/mpeg"),
])
def test_media_endpoint_sets_a_media_mime_type(serve, make_vault, save_asset,
                                               filename, expected):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("media", filename)
    response = serve().get("/vault/vault/media/%s" % filename)
    assert response.status == 200, response
    assert content_type(response).split(";")[0].strip() == expected


# Spec: "| `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>`
# ... |" -- the exact saved filename is what the endpoint takes, whatever it
# looks like.
def test_media_endpoint_serves_any_saved_filename(serve, make_vault,
                                                  save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("media", "archive-e1-final.webm", body=b"OK")
    response = serve().get("/vault/vault/media/archive-e1-final.webm")
    assert response.status == 200, response
    assert response.body == "OK"


# Spec: the media endpoint works for a vault of any supported version.
@pytest.mark.parametrize("catalog", [
    v1(entries=[v1_entry(id="e1")]),
    v2(episodes=[legacy_entry(id="e1")]),
    v3(episodes=[v3_entry(id="e1")]),
])
def test_media_endpoint_for_every_version(serve, make_vault, save_asset,
                                          catalog):
    make_vault(catalog)
    save_asset("media", "e1.mp4", body=b"BYTES")
    assert serve().get("/vault/vault/media/e1.mp4").status == 200


# --------------------------------------------------------------------------
# Preview endpoint
# --------------------------------------------------------------------------
# Spec: "| `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview
# image from `<vault>/previews/` whose saved filename contains `<id>`, with an
# appropriate image MIME type |"
def test_preview_endpoint_serves_the_matching_image(serve, make_vault,
                                                    save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("previews", "e1.jpg", body=b"PREVIEWBYTES")
    response = serve().get("/vault/vault/preview/e1")
    assert response.status == 200, response
    assert response.body == "PREVIEWBYTES"
    assert content_type(response).startswith("image/")


# Spec: "| Preview lookup | `/vault/<name>/preview/<id>` resolves the saved
# preview asset whose filename contains the requested `id` |"
def test_preview_lookup_matches_a_filename_containing_the_id(serve, make_vault,
                                                             save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("previews", "thumb-e1-large.png", body=b"PNGBYTES")
    response = serve().get("/vault/vault/preview/e1")
    assert response.status == 200, response
    assert response.body == "PNGBYTES"
    assert content_type(response).split(";")[0].strip() == "image/png"


# Spec: "| ... whose saved filename contains `<id>` ... |" -- a preview saved
# for another entry is not served for this id.
def test_preview_lookup_ignores_other_entries(serve, make_vault, save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1"), v3_entry(id="e2")]))
    save_asset("previews", "e2.jpg", body=b"TWO")
    server = serve()
    assert server.get("/vault/vault/preview/e2").body == "TWO"
    assert server.get("/vault/vault/preview/e1").status == 404


# --------------------------------------------------------------------------
# Safety rules
# --------------------------------------------------------------------------
# Spec: "| Path traversal | Requests containing traversal sequences must not
# escape `media/` or `previews/` |" + "| Path traversal attempt | HTTP `403` or
# HTTP `404` |"
@pytest.mark.parametrize("path", [
    "/vault/vault/media/../catalog.json",
    "/vault/vault/media/..%2Fcatalog.json",
    "/vault/vault/media/../../etc/passwd",
    "/vault/vault/media/..%2F..%2Fetc%2Fpasswd",
    "/vault/vault/preview/../catalog.json",
    "/vault/vault/preview/..%2Fcatalog.json",
    "/vault/vault/media/%2e%2e%2fcatalog.json",
])
def test_traversal_is_refused(serve, make_vault, path):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get(path)
    assert response.status in (403, 404), response
    assert '"version"' not in response.body, response.body


# Spec: "| Path traversal | ... must not escape `media/` or `previews/` |" --
# the catalog itself is never handed out through a static route.
def test_traversal_never_serves_the_catalog(serve, make_vault):
    make_vault(v3(source="https://secret.example.com/x",
                  episodes=[v3_entry(id="e1")]))
    server = serve()
    for path in ("/vault/vault/media/../catalog.json",
                 "/vault/vault/preview/../../vault/catalog.json"):
        response = server.get(path)
        assert "secret.example.com" not in response.body, response


# Spec: "| Path traversal | ... |" -- an absolute path is refused too.
def test_absolute_path_is_refused(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get("/vault/vault/media//etc/passwd")
    assert response.status in (403, 404), response


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
# Spec: "| Non-existent media file | HTTP `404` |"
def test_missing_media_file_is_404(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    assert serve().get("/vault/vault/media/nope.mp4").status == 404


# Spec: "| Non-existent media file | HTTP `404` |" -- with no `media/`
# directory at all.
def test_media_route_without_a_media_directory_is_404(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    assert serve().get("/vault/vault/media/e1.mp4").status == 404


# Spec: "| Non-existent preview image | HTTP `404` |"
def test_missing_preview_image_is_404(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    assert serve().get("/vault/vault/preview/e1").status == 404


# Spec: "| Non-existent vault on detail or static route | Redirect to landing
# page with vault-not-found indication |"
def test_missing_vault_on_media_route_redirects(serve):
    response = serve().get("/vault/ghost/media/e1.mp4")
    assert response.is_redirect, response
    assert response.location == "/"


def test_missing_vault_on_preview_route_redirects(serve):
    response = serve().get("/vault/ghost/preview/e1")
    assert response.is_redirect, response
    assert response.location == "/"


# Spec: "| Non-existent vault ... | Redirect to landing page with
# vault-not-found indication |"
def test_missing_vault_on_static_route_shows_the_indication(serve):
    response = serve().get("/vault/ghost-vault/media/e1.mp4", follow=True)
    assert response.status == 200, response
    assert "not found" in response.body.lower()
    assert "ghost-vault" in response.body


# Spec: "| Any HTTP error | Well-formed response; no raw stack trace or
# internal detail exposure |"
@pytest.mark.parametrize("path", [
    "/vault",
    "/vault/",
    "/vault/vault",
    "/vault/vault/",
    "/vault/vault/bogus/e1",
    "/vault/vault/media",
    "/vault/vault/media/",
    "/vault/vault/preview",
])
def test_incomplete_static_paths_are_well_formed(serve, make_vault, path):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get(path)
    assert response.status in (200, 302, 303, 400, 403, 404), response
    lowered = response.body.lower()
    assert "traceback (most recent call last)" not in lowered
    assert "stack trace" not in lowered


# Spec: "| Any HTTP error | ... |" -- the server keeps serving afterwards.
def test_server_survives_static_route_abuse(serve, make_vault, save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Fine")]))
    save_asset("media", "e1.mp4", body=b"OK")
    server = serve()
    for path in ("/vault/vault/media/../catalog.json", "/vault/ghost/media/x",
                 "/vault/vault/preview/nope", "/vault/"):
        server.get(path)
    assert server.get("/vault/vault/media/e1.mp4").body == "OK"
