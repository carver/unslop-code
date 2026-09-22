"""Spec section: `/` Recent Vaults."""

from conftest import (
    EPOCH_KEY,
    free_port,
    legacy_entry,
    v1_catalog,
    v3_catalog,
    v3_entry,
    write_vault,
)


def make_vault(tmp_path, name):
    write_vault(tmp_path, name, v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")]))


# Spec: "| Trigger | Navigation to any vault through viewer |" and
# "| Display location | Landing page |".
def test_visited_vault_appears_on_the_landing_page(viewer, tmp_path):
    make_vault(tmp_path, "demo")
    viewer.client.get("/catalog/demo/episodes")

    assert "demo" in viewer.client.get("/").body


# Spec: "| Trigger | Navigation to any vault through viewer |" -- the bare
# vault route is a navigation too, even though it only redirects.
def test_vault_root_navigation_is_recorded(viewer, tmp_path):
    make_vault(tmp_path, "demo")
    viewer.client.get("/catalog/demo")

    assert "demo" in viewer.client.get("/").body


# Spec: "| Persistence | Later browser session from same browser must still
# show visited vault |" -- a fresh client of a restarted server still sees it.
def test_visited_vault_survives_a_later_session(viewer, serve_viewer, tmp_path):
    make_vault(tmp_path, "demo")
    viewer.client.get("/catalog/demo/episodes")
    viewer.stop()

    port = free_port()
    later = serve_viewer(f"--port={port}", port=port)

    assert "demo" in later.client.get("/").body


# Spec: "| Ordering | Most recently visited first |" and "| Recent-vault order
# | Most recently visited first |".
def test_recent_vaults_are_listed_newest_first(viewer, tmp_path):
    make_vault(tmp_path, "first")
    make_vault(tmp_path, "second")
    viewer.client.get("/catalog/first/episodes")
    viewer.client.get("/catalog/second/episodes")

    body = viewer.client.get("/").body

    assert body.index("second") < body.index("first")


# Spec: "| Ordering | Most recently visited first |" -- revisiting a vault moves
# it back to the front rather than listing it twice.
def test_revisiting_a_vault_moves_it_to_the_front(viewer, tmp_path):
    make_vault(tmp_path, "first")
    make_vault(tmp_path, "second")
    viewer.client.get("/catalog/first/episodes")
    viewer.client.get("/catalog/second/episodes")
    viewer.client.get("/catalog/first/episodes")

    body = viewer.client.get("/").body

    assert body.index("first") < body.index("second")
    assert body.count('href="/catalog/first/episodes"') == 1


# Spec: "| Link target | Each recent-vault link points directly to that vault's
# resolved default category page |" and "| Recent-vault links on `/` | Use the
# same resolved default-category route as `/catalog/<name>` would redirect to |".
def test_recent_link_points_at_the_resolved_default_category(viewer, tmp_path):
    make_vault(tmp_path, "modern")
    write_vault(tmp_path, "legacy", v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    viewer.client.get("/catalog/modern/episodes")
    viewer.client.get("/catalog/legacy/entries")

    body = viewer.client.get("/").body

    assert 'href="/catalog/modern/episodes"' in body
    assert 'href="/catalog/legacy/entries"' in body


# Spec: "| Empty state | Area may be empty or absent |".
def test_landing_page_without_visits_still_renders(viewer):
    response = viewer.client.get("/")

    assert response.status == 200
    assert "<form" in response.body
