"""Spec section: HTTP Error Handling for the detail and static routes."""

import pytest
from conftest import REDIRECT_STATUSES, write_media, write_previews, write_vault
from detail_fixtures import v1_vault, v3_vault

MISSING_ENTRY_STATUSES = (404,) + REDIRECT_STATUSES
INVALID_CATEGORY_STATUSES = (400, 404) + REDIRECT_STATUSES


def assert_clean(response):
    """A response the spec calls well-formed: no exception text in the body."""
    assert response.status != 500
    assert "Traceback" not in response.body
    assert "most recent call last" not in response.body


# Phrase: "| Missing entry in specified category | HTTP `404`, or redirect to
# category listing with error indication |".
def test_missing_entry_is_reported(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/episodes/ghost")

    assert_clean(response)
    assert response.status in MISSING_ENTRY_STATUSES
    if response.status in REDIRECT_STATUSES:
        assert response.location.startswith("/catalog/demo/episodes")


# Phrase: "| Non-existent vault on detail or static route | Redirect to landing
# page with vault-not-found indication |".
@pytest.mark.parametrize(
    "path",
    ["/catalog/ghost/episodes/e1", "/vault/ghost/media/e1.mp4", "/vault/ghost/preview/e1"],
)
def test_non_existent_vault_redirects_to_the_landing_page(viewer, path):
    response = viewer.client.get(path)

    assert_clean(response)
    assert response.status in REDIRECT_STATUSES
    assert response.location == "/"


# Phrase: "| Non-existent vault ... | Redirect to landing page with
# vault-not-found indication |".
def test_landing_page_reports_a_vault_missed_on_a_static_route(viewer):
    viewer.client.get("/vault/phantom/media/e1.mp4")

    body = viewer.client.get("/").body

    assert "phantom" in body
    assert "not found" in body.lower()


# Phrase: "| Invalid category on detail route | Same handling allowed for
# invalid category listing route |" -- a v1 vault has no `episodes`.
def test_invalid_category_on_a_v1_detail_route(viewer, tmp_path):
    v1_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/episodes/e1")

    assert_clean(response)
    if response.status in REDIRECT_STATUSES:
        assert response.location == "/catalog/demo/entries"
    else:
        assert response.status in INVALID_CATEGORY_STATUSES


# Phrase: "| Invalid category on detail route | ... |" -- a v3 vault has no
# `entries` category.
def test_invalid_category_on_a_v3_detail_route(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/entries/e1")

    assert_clean(response)
    if response.status in REDIRECT_STATUSES:
        assert response.location == "/catalog/demo/episodes"
    else:
        assert response.status in INVALID_CATEGORY_STATUSES


# Phrase: "| Non-existent media file | HTTP `404` |".
def test_non_existent_media_file_is_404(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get("/vault/demo/media/missing.mp4")

    assert response.status == 404
    assert_clean(response)


# Phrase: "| Non-existent media file | HTTP `404` |" -- also when the vault has
# no `media/` directory at all.
def test_media_request_without_a_media_directory_is_404(viewer, tmp_path):
    v3_vault(tmp_path)

    assert viewer.client.get("/vault/demo/media/e1.mp4").status == 404


# Phrase: "| Non-existent preview image | HTTP `404` |".
def test_non_existent_preview_is_404(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_previews(vault, "e1.jpg")

    response = viewer.client.get("/vault/demo/preview/ghost")

    assert response.status == 404
    assert_clean(response)


# Phrase: "| Non-existent preview image | HTTP `404` |" -- also when the vault
# has no `previews/` directory at all.
def test_preview_request_without_a_previews_directory_is_404(viewer, tmp_path):
    v3_vault(tmp_path)

    assert viewer.client.get("/vault/demo/preview/e1").status == 404


# Phrase: "| Any HTTP error | Well-formed response; no raw stack trace or
# internal detail exposure |" -- a directory is not served as a media file.
def test_media_path_naming_a_directory_is_not_served(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_media(vault, "e1.mp4")
    (vault / "media" / "nested").mkdir()

    response = viewer.client.get("/vault/demo/media/nested")

    assert response.status in (403, 404)
    assert_clean(response)


# Phrase: "| Any HTTP error | Well-formed response ... |" -- an unreadable
# catalog behind a detail route is answered, not crashed.
def test_unreadable_catalog_on_a_detail_route_is_clean(viewer, tmp_path):
    write_vault(tmp_path, "broken", "{not json")

    assert_clean(viewer.client.get("/catalog/broken/episodes/e1"))


# Phrase: "| Any HTTP error | Well-formed response ... |" -- a `/vault` path
# with no asset kind is a plain error rather than a crash.
@pytest.mark.parametrize("path", ["/vault", "/vault/demo", "/vault/demo/media", "/vault/demo/other/x"])
def test_incomplete_vault_paths_are_clean_errors(viewer, tmp_path, path):
    v3_vault(tmp_path)

    response = viewer.client.get(path)

    assert_clean(response)
    assert response.status != 200
