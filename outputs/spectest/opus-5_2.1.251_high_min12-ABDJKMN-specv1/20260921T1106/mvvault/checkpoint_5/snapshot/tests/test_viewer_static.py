"""Spec sections: `/vault` Static File Endpoints / `/vault` Static File Safety
Rules / HTTP Error Handling / Determinism (preview lookup)."""
import os

import pytest
from conftest import make_vault, place_file, v1_entry, v3_entry

REDIRECTS = (302, 303)


def v1_vault(tmp_path, entries=(), name="v", source_id="chan42"):
    return make_vault(tmp_path, name, {"version": 1, "source_id": source_id,
                                       "entries": list(entries)})


def v3_vault(tmp_path, episodes=(), streams=(), clips=(), name="v"):
    return make_vault(tmp_path, name,
                      {"version": 3, "source": "http://example.invalid/f.json",
                       "episodes": list(episodes), "streams": list(streams),
                       "clips": list(clips)})


def raw_get(view, path):
    """GET a path verbatim, without any client-side normalization."""
    import http.client
    conn = http.client.HTTPConnection(view.host, view.port, timeout=15)
    try:
        conn.putrequest("GET", path, skip_host=False, skip_accept_encoding=True)
        conn.endheaders()
        response = conn.getresponse()
        body = response.read()
        return response.status, dict(response.getheaders()), body
    finally:
        conn.close()


def content_type(page):
    return (page.header("Content-Type") or "").lower()


# --------------------------------------------------------------------------
# `/vault/<name>/media/<file>`
# --------------------------------------------------------------------------

# Phrase: "`GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>`
#          with an appropriate media MIME type"
def test_media_endpoint_serves_the_stored_file(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", "e1.mp4", b"MEDIA-BYTES")
    view = viewer()
    page = view.browser().get("/vault/v/media/e1.mp4")
    assert page.status == 200, (page.status, page.body[:200])
    status, headers, body = raw_get(view, "/vault/v/media/e1.mp4")
    assert body == b"MEDIA-BYTES", body


# Phrase: "with an appropriate media MIME type"
@pytest.mark.parametrize("filename,expected", [("e1.mp4", "video/mp4"),
                                               ("e1.webm", "video/webm"),
                                               ("e1.mp3", "audio/mpeg")])
def test_media_mime_types(viewer, tmp_path, filename, expected):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", filename, b"DATA")
    page = viewer().browser().get("/vault/v/media/%s" % filename)
    assert page.status == 200
    assert expected in content_type(page), content_type(page)


# Phrase: "Serve `<vault>/media/<file>`"
# Context: the file name is taken verbatim, including extra dots.
def test_media_endpoint_serves_unusual_filenames(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", "e1.part2.mp4", b"DATA")
    page = viewer().browser().get("/vault/v/media/e1.part2.mp4")
    assert page.status == 200


# Phrase: "Serve `<vault>/media/<file>`"
# Context: v1 vaults expose the same media directory.
def test_v1_media_endpoint(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    place_file(vault, "media", "e1.mp4", b"DATA")
    page = viewer().browser().get("/vault/v/media/e1.mp4")
    assert page.status == 200


# --------------------------------------------------------------------------
# `/vault/<name>/preview/<id>`
# --------------------------------------------------------------------------

# Phrase: "`GET` | `/vault/<name>/preview/<id>` | Serve the matching preview
#          image from `<vault>/previews/` whose saved filename contains `<id>`"
def test_preview_endpoint_serves_the_matching_image(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "previews", "e1.png", b"PNG-BYTES")
    view = viewer()
    page = view.browser().get("/vault/v/preview/e1")
    assert page.status == 200, (page.status, page.body[:200])
    status, headers, body = raw_get(view, "/vault/v/preview/e1")
    assert body == b"PNG-BYTES", body


# Phrase: "whose saved filename contains `<id>`"
# Context: the request names the id, not the file name.
def test_preview_matches_a_filename_containing_the_id(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "previews", "prefix-e1-suffix.jpg", b"JPG")
    page = viewer().browser().get("/vault/v/preview/e1")
    assert page.status == 200
    assert content_type(page).startswith("image/"), content_type(page)


# Phrase: "with an appropriate image MIME type"
@pytest.mark.parametrize("filename,expected", [("e1.png", "image/png"),
                                               ("e1.jpg", "image/jpeg"),
                                               ("e1.webp", "image/webp")])
def test_preview_mime_types(viewer, tmp_path, filename, expected):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "previews", filename, b"DATA")
    page = viewer().browser().get("/vault/v/preview/e1")
    assert page.status == 200
    assert expected in content_type(page), content_type(page)


# Phrase: "Preview lookup | `/vault/<name>/preview/<id>` resolves the saved
#          preview asset whose filename contains the requested `id`"
# Context: determinism — two ids in one directory resolve to their own files.
def test_preview_lookup_picks_the_right_asset(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])
    place_file(vault, "previews", "e1.png", b"ONE")
    place_file(vault, "previews", "e2.png", b"TWO")
    view = viewer()
    assert raw_get(view, "/vault/v/preview/e1")[2] == b"ONE"
    assert raw_get(view, "/vault/v/preview/e2")[2] == b"TWO"


# Phrase: "Preview lookup ... resolves the saved preview asset"
# Context: repeated requests resolve to the same asset.
def test_preview_lookup_is_deterministic(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "previews", "e1.png", b"ONE")
    view = viewer()
    first = raw_get(view, "/vault/v/preview/e1")
    second = raw_get(view, "/vault/v/preview/e1")
    assert first[2] == second[2]


# Phrase: "Serve the matching preview image from `<vault>/previews/`"
# Context: media files are not preview assets.
def test_preview_does_not_serve_from_media(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", "e1.mp4", b"DATA")
    page = viewer().browser().get("/vault/v/preview/e1")
    assert page.status == 404, page.status


# --------------------------------------------------------------------------
# `/vault` Static File Safety Rules
# --------------------------------------------------------------------------

# Phrase: "Path traversal | Requests containing traversal sequences must not
#          escape `media/` or `previews/`"
@pytest.mark.parametrize("path", [
    "/vault/v/media/../../secret.txt",
    "/vault/v/media/..%2f..%2fsecret.txt",
    "/vault/v/media/%2e%2e%2fsecret.txt",
    "/vault/v/media/..",
    "/vault/v/preview/../../secret.txt",
    "/vault/v/preview/..%2f..%2fsecret.txt",
])
def test_traversal_does_not_escape(viewer, tmp_path, path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    with open(os.path.join(str(tmp_path), "secret.txt"), "wb") as handle:
        handle.write(b"TOP-SECRET")
    view = viewer()
    status, headers, body = raw_get(view, path)
    assert b"TOP-SECRET" not in body, path
    assert status in (403, 404), (path, status)


# Phrase: "Path traversal attempt | HTTP `403` or HTTP `404`"
def test_traversal_into_the_catalog_is_refused(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    status, headers, body = raw_get(viewer(), "/vault/v/media/../catalog.json")
    assert status in (403, 404), status
    assert b"episodes" not in body


# Phrase: "Requests containing traversal sequences must not escape `media/`"
# Context: an absolute-looking path is not an escape hatch either.
def test_absolute_path_is_refused(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    status, headers, body = raw_get(viewer(), "/vault/v/media//etc/passwd")
    assert status in (403, 404), status
    assert b"root:" not in body


# Phrase: "Path traversal | ... must not escape `media/` or `previews/`"
# Context: a traversal in the vault name segment is refused too.
def test_traversal_in_the_vault_name_is_refused(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    status, headers, body = raw_get(viewer(), "/vault/..%2fv/media/e1.mp4")
    assert status in (403, 404) + REDIRECTS, status
    assert b"Traceback" not in body


# --------------------------------------------------------------------------
# HTTP Error Handling (static routes)
# --------------------------------------------------------------------------

# Phrase: "Non-existent media file | HTTP `404`"
def test_missing_media_file_is_404(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get("/vault/v/media/nope.mp4")
    assert page.status == 404, (page.status, page.body[:200])


# Phrase: "Non-existent media file | HTTP `404`"
# Context: an absent media directory is the same 404, not a crash.
def test_missing_media_directory_is_404(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get("/vault/v/media/e1.mp4")
    assert page.status == 404


# Phrase: "Non-existent preview image | HTTP `404`"
def test_missing_preview_is_404(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "previews", "e1.png", b"ONE")
    page = viewer().browser().get("/vault/v/preview/ghost")
    assert page.status == 404, (page.status, page.body[:200])


# Phrase: "Non-existent preview image | HTTP `404`"
# Context: an absent previews directory is the same 404.
def test_missing_previews_directory_is_404(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get("/vault/v/preview/e1")
    assert page.status == 404


# Phrase: "Non-existent vault on detail or static route | Redirect to landing
#          page with vault-not-found indication"
@pytest.mark.parametrize("path", ["/vault/ghost/media/e1.mp4",
                                  "/vault/ghost/preview/e1"])
def test_missing_vault_on_static_route_redirects_to_landing(viewer, tmp_path,
                                                            path):
    browser = viewer().browser()
    page = browser.get(path)
    assert page.status in REDIRECTS, (page.status, page.body[:200])
    landing = page.location.split("?")[0]
    assert landing.count("/") <= 3, page.location
    _, final = browser.follow(path)
    assert final.status == 200
    import re
    assert re.search(r"not\s*found", final.body, re.IGNORECASE), final.body


# Phrase: "Any HTTP error | Well-formed response; no raw stack trace or
#          internal detail exposure"
@pytest.mark.parametrize("path", ["/vault", "/vault/", "/vault/v",
                                  "/vault/v/media", "/vault/v/bogus/x",
                                  "/vault/v/media/a/b"])
def test_odd_static_paths_are_well_formed(viewer, tmp_path, path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get(path)
    assert page.status < 500, (path, page.status)
    assert "Traceback" not in page.body
    assert 'File "' not in page.body


# Phrase: "Well-formed response"
# Context: the server keeps serving after static-route errors.
def test_server_survives_static_errors(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", "e1.mp4", b"DATA")
    browser = viewer().browser()
    browser.get("/vault/v/media/../../secret.txt")
    browser.get("/vault/ghost/preview/e1")
    assert browser.get("/vault/v/media/e1.mp4").status == 200
