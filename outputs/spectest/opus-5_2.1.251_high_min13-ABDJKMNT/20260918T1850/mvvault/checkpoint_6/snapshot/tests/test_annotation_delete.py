"""Spec sections: `/catalog/<name>/<category>/<id>` Annotation Methods (`DELETE`)
and `DELETE` Annotation Fields."""

import pytest

from conftest import (
    annotation_titles,
    create,
    entry_route,
    location,
    stored_annotations,
    v3_catalog,
    v3_entry,
    write_vault,
)

ROUTE = entry_route("vault", "episodes", "e1")


@pytest.fixture
def three(serve, tmp_path):
    """A viewer over a v3 vault whose episode carries three annotations."""
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    viewer = serve()
    for index, title in enumerate(("Intro", "Chorus", "Outro")):
        create(viewer, ROUTE, title=title, timecode=str(index * 30))
    ids = [item["id"] for item in stored_annotations(vault_dir, "episodes", "e1")]
    return viewer, vault_dir, ids


# Spec: `DELETE` | Delete annotation | JSON with `id`
def test_delete_removes_the_named_annotation(three):
    viewer, vault_dir, ids = three
    viewer.send("DELETE", ROUTE, {"id": ids[1]})
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Intro", "Outro"]


# Spec: `DELETE` | ... | Redirect to entry detail page
def test_delete_redirects_to_the_entry_detail_page(three):
    viewer, _, ids = three
    response = viewer.send("DELETE", ROUTE, {"id": ids[0]})
    assert response.status_code in (302, 303)
    assert location(response) == (ROUTE, {})


# Spec: List order | Creation order (a delete leaves the survivors in order)
def test_delete_keeps_the_remaining_order(three):
    viewer, vault_dir, ids = three
    viewer.send("DELETE", ROUTE, {"id": ids[0]})
    assert [item["id"] for item in stored_annotations(vault_dir, "episodes", "e1")] == ids[1:]


# Spec: Container type | Ordered list (deleting the last one leaves an empty list)
def test_deleting_every_annotation_leaves_an_empty_list(three):
    viewer, vault_dir, ids = three
    for annotation_id in ids:
        viewer.send("DELETE", ROUTE, {"id": annotation_id})
    assert stored_annotations(vault_dir, "episodes", "e1") == []


# Spec: `id` | string | yes (deleting twice is a miss the second time)
def test_deleting_the_same_annotation_twice_misses(three):
    viewer, _, ids = three
    assert viewer.send("DELETE", ROUTE, {"id": ids[0]}).status_code in (302, 303)
    assert viewer.send("DELETE", ROUTE, {"id": ids[0]}).status_code == 404


# Spec: `id` | Annotation identifier inside current entry (another entry's is a miss)
def test_an_id_only_deletes_inside_the_entry_that_holds_it(serve, tmp_path):
    vault_dir = write_vault(
        tmp_path, v3_catalog(episodes=[v3_entry("e1")], clips=[v3_entry("c1")])
    )
    viewer = serve()
    create(viewer, ROUTE, title="Chorus", timecode="30")
    annotation_id = stored_annotations(vault_dir, "episodes", "e1")[0]["id"]

    clip = entry_route("vault", "clips", "c1")
    assert viewer.send("DELETE", clip, {"id": annotation_id}).status_code == 404
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Chorus"]
