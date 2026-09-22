"""Spec section: `/vault` static file endpoints, their safety rules and errors."""

from __future__ import annotations

import urllib.parse

REDIRECTS = (301, 302, 303, 307, 308)
REFUSALS = (403, 404)


# ---------------------------------------------------------------------------
# | `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>` with an
#   appropriate media MIME type |
# ---------------------------------------------------------------------------

# Spec: | `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>` |
def test_media_endpoint_serves_the_file(serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4", b"\x00\x01movie")
    response = serve().client.get(detail.media_url("vault", "e1.mp4"))
    assert response.status == 200, response.status
    assert response.body == "\x00\x01movie"


# Spec: | ... | Serve `<vault>/media/<file>` with an appropriate media MIME type |
def test_media_endpoint_sets_a_media_mime_type(serve, make_vault, catalogs,
                                               detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    response = serve().client.get(detail.media_url("vault", "e1.mp4"))
    assert response.headers.get("Content-Type", "").startswith("video/mp4"), \
        response.headers


# Spec: | ... | ... an appropriate media MIME type |
# Context: audio downloads get an audio type, not the video one.
def test_media_mime_type_follows_the_extension(serve, make_vault, catalogs,
                                               detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                                  catalogs.entry("e2")]))
    detail.write_media(vault, "e1.mp3")
    detail.write_media(vault, "e2.webm")
    client = serve().client
    audio = client.get(detail.media_url("vault", "e1.mp3"))
    video = client.get(detail.media_url("vault", "e2.webm"))
    assert audio.headers.get("Content-Type", "").startswith("audio/"), audio.headers
    assert video.headers.get("Content-Type", "").startswith("video/"), video.headers


# Spec: | ... | Serve `<vault>/media/<file>` ... |
# Context: the file is named exactly, so a name that merely contains the id is
# not a substitute for the real name.
def test_media_endpoint_is_addressed_by_exact_filename(serve, make_vault,
                                                       catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "prefix-e1.mp4")
    client = serve().client
    assert client.get(detail.media_url("vault", "prefix-e1.mp4")).status == 200
    assert client.get(detail.media_url("vault", "e1.mp4")).status == 404


# Spec: | ... | Serve `<vault>/media/<file>` ... |
# Context: media of one vault is not reachable through another vault's name.
def test_media_endpoint_is_scoped_to_its_vault(serve, make_vault, catalogs,
                                               detail):
    first = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]),
                       name="one")
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="two")
    detail.write_media(first, "e1.mp4")
    client = serve().client
    assert client.get(detail.media_url("one", "e1.mp4")).status == 200
    assert client.get(detail.media_url("two", "e1.mp4")).status == 404


# ---------------------------------------------------------------------------
# | `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview image
#   from `<vault>/previews/` whose saved filename contains `<id>`, with an
#   appropriate image MIME type |
# ---------------------------------------------------------------------------

# Spec: | `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview
#   image from `<vault>/previews/` ... |
def test_preview_endpoint_serves_the_matching_image(serve, make_vault,
                                                    catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_preview(vault, "e1.jpg", b"jpeg-bytes")
    response = serve().client.get(detail.preview_url("vault", "e1"))
    assert response.status == 200, response.status
    assert response.body == "jpeg-bytes"


# Spec: | ... | ... whose saved filename contains `<id>` ... |
# Context: the route is addressed by entry id, not by the saved filename.
def test_preview_endpoint_matches_a_containing_filename(serve, make_vault,
                                                        catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_preview(vault, "thumb-e1-large.png", b"png-bytes")
    response = serve().client.get(detail.preview_url("vault", "e1"))
    assert response.status == 200, response.status
    assert response.body == "png-bytes"


# Spec: | ... | ... with an appropriate image MIME type |
def test_preview_endpoint_sets_an_image_mime_type(serve, make_vault, catalogs,
                                                  detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_preview(vault, "e1.jpg")
    response = serve().client.get(detail.preview_url("vault", "e1"))
    assert response.headers.get("Content-Type", "").startswith("image/"), \
        response.headers


# Spec: | ... | ... with an appropriate image MIME type |
# Context: a PNG preview is served as a PNG.
def test_preview_mime_type_follows_the_extension(serve, make_vault, catalogs,
                                                 detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_preview(vault, "e1.png")
    response = serve().client.get(detail.preview_url("vault", "e1"))
    assert response.headers.get("Content-Type", "").startswith("image/png"), \
        response.headers


# Spec: | Preview lookup | `/vault/<name>/preview/<id>` resolves the saved
#   preview asset whose filename contains the requested `id` |
# Context: another entry's preview is not served for this id.
def test_preview_endpoint_does_not_serve_another_entrys_asset(
        serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                                  catalogs.entry("zz")]))
    detail.write_preview(vault, "zz.jpg")
    client = serve().client
    assert client.get(detail.preview_url("vault", "zz")).status == 200
    assert client.get(detail.preview_url("vault", "e1")).status == 404


# Spec: | Preview lookup | ... resolves the saved preview asset ... |
# Context: previews live in `previews/`, so a media file never answers.
def test_preview_endpoint_does_not_read_the_media_directory(
        serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    assert serve().client.get(detail.preview_url("vault", "e1")).status == 404


# Spec: | Preview lookup | ... |
# Context: the lookup is deterministic - repeated requests answer identically.
def test_preview_lookup_is_deterministic(serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_preview(vault, "a-e1.jpg", b"one")
    detail.write_preview(vault, "b-e1.jpg", b"two")
    client = serve().client
    bodies = {client.get(detail.preview_url("vault", "e1")).body
              for _ in range(4)}
    assert len(bodies) == 1, bodies


# ---------------------------------------------------------------------------
# | Path traversal | Requests containing traversal sequences must not escape
#   `media/` or `previews/` |
# | Path traversal attempt | HTTP `403` or HTTP `404` |
# ---------------------------------------------------------------------------

TRAVERSALS = (
    "../catalog.json",
    "../../catalog.json",
    "..%2fcatalog.json",
    "..%2F..%2Fcatalog.json",
    "%2e%2e%2fcatalog.json",
    "subdir/../../catalog.json",
)


# Spec: | Path traversal | Requests ... must not escape `media/` |
def test_media_traversal_is_refused(serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    client = serve().client
    for attempt in TRAVERSALS:
        response = client.get(f"/vault/vault/media/{attempt}")
        assert response.status in REFUSALS, (attempt, response.status)
        assert "\"version\"" not in response.body, attempt


# Spec: | Path traversal | Requests ... must not escape `previews/` |
def test_preview_traversal_is_refused(serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_preview(vault, "e1.jpg")
    client = serve().client
    for attempt in TRAVERSALS:
        response = client.get(f"/vault/vault/preview/{attempt}")
        assert response.status in REFUSALS, (attempt, response.status)
        assert "\"version\"" not in response.body, attempt


# Spec: | Path traversal | ... must not escape `media/` or `previews/` |
# Context: a traversal through the vault name must not leave the served root.
def test_traversal_in_the_vault_name_is_refused(serve, make_vault, catalogs,
                                                workdir):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    (workdir / "outside.txt").write_text("secret", encoding="utf-8")
    client = serve().client
    for name in ("..", "..%2f..", "vault%2f..%2fvault"):
        response = client.get(f"/vault/{name}/media/outside.txt")
        assert response.status in REFUSALS + REDIRECTS, (name, response.status)
        assert "secret" not in response.body, name


# Spec: | Path traversal | ... must not escape `media/` |
# Context: an absolute-looking file name stays inside the media directory.
def test_absolute_looking_media_name_is_refused(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/vault/vault/media/%2fetc%2fpasswd")
    assert response.status in REFUSALS, response.status
    assert "root:" not in response.body


# ---------------------------------------------------------------------------
# | Non-existent media file | HTTP `404` |
# | Non-existent preview image | HTTP `404` |
# ---------------------------------------------------------------------------

# Spec: | Non-existent media file | HTTP `404` |
def test_missing_media_file_is_404(serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    response = serve().client.get(detail.media_url("vault", "nothing.mp4"))
    assert response.status == 404, response.status


# Spec: | Non-existent media file | HTTP `404` |
# Context: a vault with no `media/` directory answers `404`, not an error page.
def test_media_without_a_media_directory_is_404(serve, make_vault, catalogs,
                                                detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get(detail.media_url("vault", "e1.mp4"))
    assert response.status == 404, response.status


# Spec: | Non-existent preview image | HTTP `404` |
def test_missing_preview_is_404(serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_preview(vault, "e1.jpg")
    response = serve().client.get(detail.preview_url("vault", "unknown"))
    assert response.status == 404, response.status


# Spec: | Non-existent preview image | HTTP `404` |
# Context: a vault with no `previews/` directory answers `404`.
def test_preview_without_a_previews_directory_is_404(serve, make_vault,
                                                     catalogs, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    assert serve().client.get(detail.preview_url("vault", "e1")).status == 404


# ---------------------------------------------------------------------------
# | Non-existent vault on detail or static route | Redirect to landing page
#   with vault-not-found indication |
# ---------------------------------------------------------------------------

# Spec: | Non-existent vault on ... static route | Redirect to landing page ... |
def test_static_route_on_missing_vault_redirects(serve, detail):
    response = serve().client.get(detail.media_url("ghost", "e1.mp4"))
    assert response.status in REDIRECTS, response.status
    assert urllib.parse.urlsplit(response.location or "").path == "/", \
        response.location


# Spec: | Non-existent vault on ... static route | Redirect to landing page
#   with vault-not-found indication |
def test_static_route_on_missing_vault_indicates_not_found(serve, detail):
    client = serve().client
    landed = client.get(detail.preview_url("ghost", "e1"), follow=True)
    assert landed.status == 200, landed.status
    assert "ghost" in landed.body, landed.body


# Spec: | Non-existent vault on detail ... route | Redirect to landing page
#   with vault-not-found indication |
def test_detail_route_on_missing_vault_redirects(serve, detail):
    response = serve().client.get(detail.path("ghost", "episodes", "e1"))
    assert response.status in REDIRECTS, response.status
    assert urllib.parse.urlsplit(response.location or "").path == "/", \
        response.location


# Spec: | Non-existent vault on detail ... route | ... vault-not-found
#   indication |
def test_detail_route_on_missing_vault_indicates_not_found(serve, detail):
    landed = serve().client.get(detail.path("ghost", "episodes", "e1"),
                                follow=True)
    assert landed.status == 200, landed.status
    assert "ghost" in landed.body, landed.body


# Spec: | Non-existent vault on detail or static route | ... |
# Context: a directory without a catalog is not a vault.
def test_static_route_on_catalogless_directory_redirects(serve, workdir, detail):
    (workdir / "bare" / "media").mkdir(parents=True)
    (workdir / "bare" / "media" / "e1.mp4").write_bytes(b"x")
    response = serve().client.get(detail.media_url("bare", "e1.mp4"))
    assert response.status in REDIRECTS, response.status
    assert urllib.parse.urlsplit(response.location or "").path == "/"


# ---------------------------------------------------------------------------
# | Invalid category on detail route | Same handling allowed for invalid
#   category listing route |
# ---------------------------------------------------------------------------

# Spec: | Invalid category on detail route | Same handling allowed for invalid
#   category listing route |
def test_invalid_category_on_detail_route(serve, make_vault, catalogs, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    client = serve().client
    listing = client.get("/catalog/vault/nonsense")
    detail_response = client.get(detail.path("vault", "nonsense", "e1"))
    assert detail_response.status in REDIRECTS + (400, 404), \
        detail_response.status
    if detail_response.status in REDIRECTS:
        assert listing.status in REDIRECTS, listing.status
        assert urllib.parse.urlsplit(detail_response.location or "").path == \
            "/catalog/vault/episodes", detail_response.location


# Spec: | Invalid category on detail route | ... |
# Context: v1 rejects `episodes` on the detail route as on the listing route.
def test_v1_invalid_category_on_detail_route(serve, make_vault, legacy, detail):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    response = serve().client.get(detail.path("vault", "episodes", "e1"))
    assert response.status in REDIRECTS + (400, 404), response.status
    if response.status in REDIRECTS:
        assert urllib.parse.urlsplit(response.location or "").path == \
            "/catalog/vault/entries", response.location


# ---------------------------------------------------------------------------
# | Any HTTP error | Well-formed response; no raw stack trace or internal
#   detail exposure |
# ---------------------------------------------------------------------------

# Spec: | Any HTTP error | Well-formed response; no raw stack trace ... |
def test_static_errors_are_well_formed(serve, make_vault, catalogs, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    client = serve().client
    for path in (detail.media_url("vault", "missing.mp4"),
                 detail.preview_url("vault", "missing"),
                 "/vault/vault/media/../catalog.json",
                 "/vault/vault",
                 "/vault"):
        response = client.get(path)
        assert response.status in REFUSALS + REDIRECTS + (200,), \
            (path, response.status)
        assert "Traceback" not in response.body, path
        assert "File \"" not in response.body, path


# Spec: | Any HTTP error | ... no raw stack trace or internal detail exposure |
# Context: an error page never names a filesystem path from the server.
def test_static_errors_hide_internal_paths(serve, make_vault, catalogs,
                                           workdir, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get(detail.media_url("vault", "missing.mp4"))
    assert str(workdir) not in response.body, response.body


# Spec: | Any HTTP error | Well-formed response ... |
# Context: the server stays up after a refused static request.
def test_server_survives_refused_static_requests(serve, make_vault, catalogs,
                                                 detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    client = serve().client
    client.get("/vault/vault/media/../../catalog.json")
    client.get("/vault/ghost/preview/e1")
    client.get("/vault/vault/media/missing.mp4")
    assert client.get(detail.media_url("vault", "e1.mp4")).status == 200
    assert client.get("/catalog/vault/episodes").status == 200
