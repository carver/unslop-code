"""Spec sections: `/catalog` Routes, Version-Aware Default Category Redirect
and Version-Aware Valid Categories."""

import pytest
from conftest import (
    EPOCH_KEY,
    ISO_KEY,
    REDIRECT_STATUSES,
    legacy_entry,
    v1_catalog,
    v2_catalog,
    v3_catalog,
    v3_entry,
    write_vault,
)


def v1_vault(tmp_path, name="demo"):
    return write_vault(tmp_path, name, v1_catalog(legacy_entry("e1", EPOCH_KEY)))


def v2_vault(tmp_path, name="demo"):
    catalog = v2_catalog(
        "https://example.test/feed",
        episodes=[legacy_entry("e1", ISO_KEY)],
        streams=[legacy_entry("s1", ISO_KEY)],
        clips=[legacy_entry("c1", ISO_KEY)],
    )
    return write_vault(tmp_path, name, catalog)


def v3_vault(tmp_path, name="demo"):
    catalog = v3_catalog(
        "https://example.test/feed",
        episodes=[v3_entry("e1")],
        streams=[v3_entry("s1")],
        clips=[v3_entry("c1")],
    )
    return write_vault(tmp_path, name, catalog)


# Phrase: "| `GET` | `/catalog/<name>` | Redirect to default category page for
# vault |" and "| Redirect status | HTTP `302` or `303` |".
def test_vault_root_redirects_to_the_default_category(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get("/catalog/demo")

    assert response.status in REDIRECT_STATUSES
    assert response.location == "/catalog/demo/episodes"


# Phrase: "| v1 | `/catalog/<name>/entries` |".
def test_v1_default_category_is_entries(viewer, tmp_path):
    v1_vault(tmp_path)

    assert viewer.client.get("/catalog/demo").location == "/catalog/demo/entries"


# Phrase: "| v2 | `/catalog/<name>/episodes` |".
def test_v2_default_category_is_episodes(viewer, tmp_path):
    v2_vault(tmp_path)

    assert viewer.client.get("/catalog/demo").location == "/catalog/demo/episodes"


# Phrase: "| v3 | `/catalog/<name>/episodes` |".
def test_v3_default_category_is_episodes(viewer, tmp_path):
    v3_vault(tmp_path)

    assert viewer.client.get("/catalog/demo").location == "/catalog/demo/episodes"


# Phrase: "| `GET` | `/catalog/<name>/<category>` | HTML listing for category |".
def test_category_route_returns_an_html_listing(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/episodes")

    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/html")
    assert "title-e1" in response.body


# Phrase: "| `GET` | `/catalog/<name>/<category>/<id>` | HTML response for that
# viewer link target; may reuse the category listing page with the entry
# highlighted or otherwise surfaced |".
def test_entry_route_returns_html_surfacing_the_entry(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/episodes/e1")

    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/html")
    assert "title-e1" in response.body


# Phrase: "| v1 | `entries` |" -- the one category a v1 vault serves.
def test_v1_serves_the_entries_category(viewer, tmp_path):
    v1_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/entries")

    assert response.status == 200
    assert "title-e1" in response.body


# Phrase: "| v2 | `episodes`, `streams`, `clips` |" and the same row for v3.
@pytest.mark.parametrize("category, entry_id", [("episodes", "e1"), ("streams", "s1"), ("clips", "c1")])
@pytest.mark.parametrize("build", [v2_vault, v3_vault])
def test_modern_vaults_serve_all_three_categories(viewer, tmp_path, build, category, entry_id):
    build(tmp_path)

    response = viewer.client.get(f"/catalog/demo/{category}")

    assert response.status == 200
    assert f"title-{entry_id}" in response.body


# Phrase: "| v1 | `entries` |" -- `episodes` is not a v1 category, so it is not
# served as a listing.
def test_v1_does_not_serve_episodes_as_a_listing(viewer, tmp_path):
    v1_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/episodes")

    assert response.status != 200


# Phrase: "| v2 | `episodes`, `streams`, `clips` |" -- `entries` is not one of
# them, so a v2 vault does not serve it as a listing.
def test_v2_does_not_serve_entries_as_a_listing(viewer, tmp_path):
    v2_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/entries")

    assert response.status != 200
