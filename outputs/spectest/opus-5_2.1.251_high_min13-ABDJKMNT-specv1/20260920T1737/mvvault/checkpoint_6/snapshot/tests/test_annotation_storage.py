"""Spec sections: `annotations` Storage and `annotations` Storage Location."""

import json

from annotation_fixtures import V3_ENTRY, created, delete, mark, patch, stored
from conftest import find_entry, read_catalog
from detail_fixtures import MODERN_SOURCE, v3_vault


# Phrase: "| `id` | string | Unique within entry |"
def test_each_annotation_has_a_distinct_string_id(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    for index in range(3):
        created(viewer, vault, mark(title=f"mark-{index}"))

    ids = [note["id"] for note in stored(vault)]

    assert all(isinstance(value, str) for value in ids)
    assert len(set(ids)) == 3


# Phrase: "| `timecode` | integer | Whole seconds |"
def test_the_stored_timecode_is_an_integer(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(timecode="1:01:30"))

    timecode = stored(vault)[0]["timecode"]
    assert isinstance(timecode, int) and not isinstance(timecode, bool)
    assert timecode == 3690


# Phrase: "| `title` | string | Stored as provided |" -- the text is kept verbatim.
def test_the_title_is_stored_verbatim(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    title = "  Refrain & <coda>  "

    created(viewer, vault, mark(title=title))

    assert stored(vault)[0]["title"] == title


# Phrase: "| `body` | string or `null` | Stored as provided or defaulted to `null` |"
def test_the_body_is_a_string_or_null(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(title="with", body="note text"))
    created(viewer, vault, mark(title="without"))

    assert [note["body"] for note in stored(vault)] == ["note text", None]


# Phrase: "| Catalog location | Entry object key `annotations` |"
def test_annotations_live_under_the_entry_key(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault)

    entry = find_entry(read_catalog(vault), "episodes", "e1")
    assert [note["title"] for note in entry["annotations"]] == ["chorus"]


# Phrase: "| Catalog location | Entry object key `annotations` |" -- only the
# annotated entry gains one.
def test_other_entries_are_left_alone(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault)

    catalog = read_catalog(vault)
    assert catalog["clips"][0]["annotations"] == []
    assert catalog["streams"][0]["annotations"] == []


# Phrase: "| Container type | Ordered list |"
def test_the_container_is_a_json_list(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault)

    assert isinstance(stored(vault), list)


# Phrase: "| List order | Creation order |" -- later creations append, whatever
# their timecodes are.
def test_annotations_are_held_in_creation_order(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    for title, timecode in [("third", "3:00"), ("first", "0:10"), ("second", "1:00")]:
        created(viewer, vault, mark(title=title, timecode=timecode))

    assert [note["title"] for note in stored(vault)] == ["third", "first", "second"]


# Phrase: "| List order | Creation order |" -- an update keeps the position.
def test_an_update_keeps_the_annotation_in_place(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    first = created(viewer, vault, mark(title="one"))
    created(viewer, vault, mark(title="two"))

    patch(viewer, {"id": first["id"], "title": "renamed"})

    assert [note["title"] for note in stored(vault)] == ["renamed", "two"]


# Phrase: "| List order | Creation order |" -- a delete keeps the survivors in order.
def test_a_delete_keeps_the_remaining_order(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    marks = [created(viewer, vault, mark(title=name)) for name in ("one", "two", "three")]

    delete(viewer, {"id": marks[1]["id"]})

    assert [note["title"] for note in stored(vault)] == ["one", "three"]


# Phrase: "| Save behavior | `catalog.bak` written before persisting annotation
# changes |"
def test_a_create_backs_up_the_pre_annotation_catalog(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    before = read_catalog(vault)

    created(viewer, vault)

    assert json.loads((vault / "catalog.bak").read_text()) == before


# Phrase: "| Save behavior | `catalog.bak` written before persisting annotation
# changes |" -- an update backs up the catalog the create left behind.
def test_an_update_backs_up_the_catalog_it_replaces(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault, mark(title="before"))
    between = read_catalog(vault)

    patch(viewer, {"id": annotation["id"], "title": "after"})

    assert json.loads((vault / "catalog.bak").read_text()) == between


# Phrase: "| Save behavior | `catalog.bak` written before persisting annotation
# changes |" -- a delete backs up too.
def test_a_delete_backs_up_the_catalog_it_replaces(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault)
    between = read_catalog(vault)

    delete(viewer, {"id": annotation["id"]})

    assert json.loads((vault / "catalog.bak").read_text()) == between


# Phrase: "| Read-after-write behavior | Later `GET` to same entry detail page
# reflects create ... by visibly rendering stored annotations |"
def test_a_later_get_shows_a_created_annotation(viewer, tmp_path):
    v3_vault(tmp_path)
    created(viewer, tmp_path / "demo", mark(title="the drop"))

    assert "the drop" in viewer.client.get(V3_ENTRY).body


# Phrase: "| Read-after-write behavior | ... reflects ... update ... |"
def test_a_later_get_shows_an_updated_annotation(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault, mark(title="working title"))

    patch(viewer, {"id": annotation["id"], "title": "final title"})

    body = viewer.client.get(V3_ENTRY).body
    assert "final title" in body
    assert "working title" not in body


# Phrase: "| Read-after-write behavior | ... reflects ... delete result |"
def test_a_later_get_no_longer_shows_a_deleted_annotation(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault, mark(title="mistake"))

    delete(viewer, {"id": annotation["id"]})

    assert "mistake" not in viewer.client.get(V3_ENTRY).body


# Phrase: "| Read-after-write behavior | ... each `timecode` as raw seconds |"
def test_the_rendered_timecode_is_raw_seconds(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    created(viewer, vault, mark(title="late mark", timecode="1:01:30"))

    body = viewer.client.get(V3_ENTRY).body

    assert "3690" in body
    assert "1:01:30" not in body


# Phrase: "| Read-after-write behavior | ... visibly rendering stored
# annotations |" -- the body text is rendered as well as the title.
def test_the_rendered_annotation_shows_its_body(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    created(viewer, vault, mark(body="a note worth keeping"))

    assert "a note worth keeping" in viewer.client.get(V3_ENTRY).body


# Phrase: "| Save behavior |" -- persisting an annotation leaves the rest of the
# catalog as it was.
def test_persisting_an_annotation_keeps_the_rest_of_the_catalog(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    before = read_catalog(vault)

    created(viewer, vault)

    after = read_catalog(vault)
    assert after["source"] == MODERN_SOURCE
    assert after["version"] == before["version"]
    assert find_entry(after, "episodes", "e1")["views"] == find_entry(before, "episodes", "e1")["views"]
