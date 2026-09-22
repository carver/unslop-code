"""Spec sections: `POST`, `PATCH` and `DELETE` Annotation Fields."""

from annotation_fixtures import created, delete, mark, patch, post, stored
from conftest import REDIRECT_STATUSES
from detail_fixtures import v3_vault


# Phrase: "| `title` | string | yes | none |" -- a create stores the title it is given.
def test_create_stores_the_title(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(title="first verse"))

    assert stored(vault)[0]["title"] == "first verse"


# Phrase: "| `timecode` | string | yes | none |" -- a create stores the parsed timecode.
def test_create_stores_the_parsed_timecode(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(timecode="2:05"))

    assert stored(vault)[0]["timecode"] == 125


# Phrase: "| `body` | string | no | `null` |" -- a supplied body is stored.
def test_create_stores_a_supplied_body(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(body="the key change"))

    assert stored(vault)[0]["body"] == "the key change"


# Phrase: "| `body` | string | no | `null` |" -- an omitted body defaults to null.
def test_create_defaults_an_omitted_body_to_null(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, {"title": "chorus", "timecode": "90"})

    assert stored(vault)[0]["body"] is None


# Phrase: "| `id` | string | yes | Annotation identifier inside current entry |"
def test_update_addresses_the_annotation_by_its_id(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    first = created(viewer, vault, mark(title="one"))
    created(viewer, vault, mark(title="two"))

    patch(viewer, {"id": first["id"], "title": "renamed"})

    assert [note["title"] for note in stored(vault)] == ["renamed", "two"]


# Phrase: "| `title` | string | no | Replace existing title when present |"
def test_update_replaces_the_title_when_present(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault, mark(title="old", body="kept"))

    patch(viewer, {"id": annotation["id"], "title": "new"})

    assert stored(vault)[0]["title"] == "new"


# Phrase: "| `body` | string | no | Replace existing body when present |"
def test_update_replaces_the_body_when_present(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault, mark(body="old note"))

    patch(viewer, {"id": annotation["id"], "body": "new note"})

    assert stored(vault)[0]["body"] == "new note"


# Phrase: "| omitted fields | n/a | allowed | Leave stored value unchanged |" --
# updating only the title leaves the body alone.
def test_update_leaves_the_omitted_body_unchanged(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault, mark(title="old", body="kept"))

    patch(viewer, {"id": annotation["id"], "title": "new"})

    assert stored(vault)[0]["body"] == "kept"


# Phrase: "| omitted fields | n/a | allowed | Leave stored value unchanged |" --
# updating only the body leaves the title alone.
def test_update_leaves_the_omitted_title_unchanged(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault, mark(title="kept"))

    patch(viewer, {"id": annotation["id"], "body": "added"})

    assert stored(vault)[0]["title"] == "kept"


# Phrase: "| omitted fields | n/a | allowed | Leave stored value unchanged |" --
# `timecode` is not an updatable field, so an update never moves the mark.
def test_update_leaves_the_stored_timecode_unchanged(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault, mark(timecode="1:30"))

    patch(viewer, {"id": annotation["id"], "title": "new", "timecode": "9:99"})

    assert stored(vault)[0]["timecode"] == 90


# Phrase: "| `id` | string | yes |" (DELETE) -- only the named annotation goes.
def test_delete_removes_only_the_named_annotation(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    first = created(viewer, vault, mark(title="one"))
    created(viewer, vault, mark(title="two"))

    assert delete(viewer, {"id": first["id"]}).status in REDIRECT_STATUSES

    assert [note["title"] for note in stored(vault)] == ["two"]
