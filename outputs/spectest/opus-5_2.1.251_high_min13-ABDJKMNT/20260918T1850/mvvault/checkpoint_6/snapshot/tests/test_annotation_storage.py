"""Spec section: `annotations` Storage Location."""

import pytest

from conftest import (
    annotation_titles,
    create,
    entry_route,
    read_backup,
    read_catalog,
    rendered_annotations,
    stored_annotations,
    v3_catalog,
    v3_entry,
    write_vault,
)

ROUTE = entry_route("vault", "episodes", "e1")


@pytest.fixture
def entry(serve, tmp_path):
    """A viewer over a v3 vault holding one episode, plus the vault directory."""
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    return serve(), vault_dir


# Spec: Catalog location | Entry object key `annotations`
def test_annotations_live_on_the_entry_object(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Chorus", timecode="30")
    catalog = read_catalog(vault_dir)
    assert "annotations" in catalog["episodes"][0]
    assert "annotations" not in catalog


# Spec: Container type | Ordered list
def test_the_container_is_a_json_list(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Chorus", timecode="30")
    assert isinstance(stored_annotations(vault_dir, "episodes", "e1"), list)


# Spec: List order | Creation order
def test_the_list_is_in_creation_order_not_timecode_order(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Late", timecode="9:00")
    create(viewer, ROUTE, title="Early", timecode="0:05")
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Late", "Early"]


# Spec: Save behavior | `catalog.bak` written before persisting annotation changes
def test_a_backup_is_written_before_the_annotation_is_persisted(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Chorus", timecode="30")
    assert (vault_dir / "catalog.bak").is_file()


# Spec: Backup before annotation | If catalog was already v3, `catalog.bak`
# contains pre-annotation catalog
def test_the_backup_holds_the_catalog_from_before_the_annotation(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Chorus", timecode="30")
    assert read_backup(vault_dir)["episodes"][0]["annotations"] == []


# Spec: Save behavior | ... (each mutation backs up the state it started from)
def test_each_mutation_backs_up_the_state_it_started_from(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Chorus", timecode="30")
    create(viewer, ROUTE, title="Outro", timecode="200")
    assert [item["title"] for item in read_backup(vault_dir)["episodes"][0]["annotations"]] == [
        "Chorus"
    ]


# Spec: Read-after-write behavior | Later `GET` ... by visibly rendering stored annotations
def test_a_later_get_renders_a_created_annotation(entry):
    viewer, _ = entry
    create(viewer, ROUTE, title="Chorus", timecode="1:30", body="the good bit")
    body = viewer.get(ROUTE).text
    assert "Chorus" in body
    assert "the good bit" in body


# Spec: Read-after-write behavior | ... reflects update result
def test_a_later_get_renders_an_updated_annotation(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Chorus", timecode="1:30")
    annotation_id = stored_annotations(vault_dir, "episodes", "e1")[0]["id"]
    viewer.send("PATCH", ROUTE, {"id": annotation_id, "title": "Bridge"})
    body = viewer.get(ROUTE).text
    assert "Bridge" in body
    assert "Chorus" not in body


# Spec: Read-after-write behavior | ... reflects delete result
def test_a_later_get_no_longer_renders_a_deleted_annotation(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Chorus", timecode="1:30")
    annotation_id = stored_annotations(vault_dir, "episodes", "e1")[0]["id"]
    viewer.send("DELETE", ROUTE, {"id": annotation_id})
    assert "Chorus" not in viewer.get(ROUTE).text


# Spec: Annotation list order | Same order as stored in `catalog.json`
def test_the_page_renders_annotations_in_stored_order(entry):
    viewer, vault_dir = entry
    for title, timecode in (("Late", "9:00"), ("Early", "0:05"), ("Middle", "4:00")):
        create(viewer, ROUTE, title=title, timecode=timecode)
    stored = [item["id"] for item in stored_annotations(vault_dir, "episodes", "e1")]
    assert rendered_annotations(viewer.get(ROUTE).text) == stored


# Spec: Read-after-write behavior | ... (the redirect target is the page that reflects it)
def test_following_the_create_redirect_shows_the_annotation(entry):
    viewer, _ = entry
    response = viewer.send("POST", ROUTE, {"title": "Chorus", "timecode": "1:30"}, follow=True)
    assert response.status_code == 200
    assert "Chorus" in response.text
