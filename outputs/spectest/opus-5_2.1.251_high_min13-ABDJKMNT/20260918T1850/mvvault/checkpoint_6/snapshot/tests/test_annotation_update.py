"""Spec sections: `/catalog/<name>/<category>/<id>` Annotation Methods (`PATCH`)
and `PATCH` Annotation Fields."""

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
def annotated(serve, tmp_path):
    """A viewer over a v3 vault whose episode already carries one annotation."""
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    viewer = serve()
    create(viewer, ROUTE, title="Chorus", timecode="1:30", body="the good bit")
    return viewer, vault_dir, stored_annotations(vault_dir, "episodes", "e1")[0]["id"]


def only(vault_dir):
    """The single annotation stored on `e1`."""
    stored = stored_annotations(vault_dir, "episodes", "e1")
    assert len(stored) == 1
    return stored[0]


# Spec: `PATCH` | Update annotation | JSON with `id` and at least one of `title` or `body`
def test_update_replaces_the_title(annotated):
    viewer, vault_dir, annotation_id = annotated
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge"})
    assert only(vault_dir)["title"] == "Bridge"


# Spec: `body` | string | no | Replace existing body when present
def test_update_replaces_the_body(annotated):
    viewer, vault_dir, annotation_id = annotated
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "body": "rewritten"})
    assert only(vault_dir)["body"] == "rewritten"


# Spec: JSON with `id` and at least one of `title` or `body` (both at once)
def test_update_can_replace_both_fields_at_once(annotated):
    viewer, vault_dir, annotation_id = annotated
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge", "body": "rewritten"})
    assert (only(vault_dir)["title"], only(vault_dir)["body"]) == ("Bridge", "rewritten")


# Spec: omitted fields | allowed | Leave stored value unchanged
def test_an_omitted_field_keeps_its_stored_value(annotated):
    viewer, vault_dir, annotation_id = annotated
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge"})
    assert only(vault_dir)["body"] == "the good bit"


# Spec: omitted fields | ... (neither `id` nor `timecode` is disturbed)
def test_update_leaves_the_id_and_timecode_alone(annotated):
    viewer, vault_dir, annotation_id = annotated
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge"})
    assert only(vault_dir)["id"] == annotation_id
    assert only(vault_dir)["timecode"] == 90


# Spec: `PATCH` | ... | Redirect to entry detail page
def test_update_redirects_to_the_entry_detail_page(annotated):
    viewer, _, annotation_id = annotated
    response = viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge"})
    assert response.status_code in (302, 303)
    assert location(response) == (ROUTE, {})


# Spec: `id` | string | yes | Annotation identifier inside current entry
def test_update_touches_only_the_named_annotation(annotated):
    viewer, vault_dir, annotation_id = annotated
    create(viewer, ROUTE, title="Outro", timecode="200")
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge"})
    assert [item["title"] for item in stored_annotations(vault_dir, "episodes", "e1")] == [
        "Bridge",
        "Outro",
    ]


# Spec: `body` | string or `null` | Stored as provided (T72: an explicit null clears it)
def test_an_explicit_null_body_clears_the_stored_body(annotated):
    viewer, vault_dir, annotation_id = annotated
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "body": None})
    assert only(vault_dir)["body"] is None


# Spec: `PATCH` Annotation Fields (T73: `timecode` is not an updatable field)
def test_a_timecode_in_an_update_body_is_ignored(annotated):
    viewer, vault_dir, annotation_id = annotated
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge", "timecode": "9:00"})
    assert only(vault_dir)["timecode"] == 90


# Spec: JSON with `id` and at least one of `title` or `body` (T66: neither is a 400)
def test_an_update_naming_no_field_to_change_is_refused(annotated):
    viewer, vault_dir, annotation_id = annotated
    assert viewer.send("PATCH", ROUTE, {"id": annotation_id}).status_code == 400
    assert only(vault_dir)["title"] == "Chorus"


# Spec: List order | Creation order (an update does not reorder)
def test_update_does_not_reorder_the_list(annotated):
    viewer, vault_dir, annotation_id = annotated
    create(viewer, ROUTE, title="Outro", timecode="200")
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge"})
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Bridge", "Outro"]
