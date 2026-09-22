"""Spec: the `annotations` Storage Location table -- where annotations live,
how they are persisted and what the backup holds."""
import json
import os

import pytest

from annotation_helpers import (assert_clean, backup_file, catalog_file,
                                create, created_id, only_annotation, remove,
                                stored_annotations, stored_backup,
                                stored_catalog, update)
from digest_helpers import v3, v3_entry


@pytest.fixture
def vault3(make_vault):
    def _make(entries=None, **kwargs):
        return make_vault(v3(episodes=entries or [v3_entry(id="e1")]),
                          **kwargs)
    return _make


# --------------------------------------------------------------------------
# Catalog location / container type
# --------------------------------------------------------------------------
# Spec: "| Catalog location | Entry object key `annotations` |"
def test_annotations_live_under_the_entry_key(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    entry = stored_catalog(tmp_path)["episodes"][0]
    assert "annotations" in entry
    assert entry["annotations"][0]["title"] == "Note"


# Spec: "| Catalog location | Entry object key `annotations` |" -- not at the
# catalog root and not in a sidecar file.
def test_annotations_are_not_stored_at_the_catalog_root(serve, tmp_path,
                                                        vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    assert "annotations" not in stored_catalog(tmp_path)


# Spec: "| Container type | Ordered list |" -- a JSON array, keyed by nothing.
def test_container_is_a_json_array(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    raw = json.loads(open(catalog_file(tmp_path), encoding="utf-8").read())
    assert isinstance(raw["episodes"][0]["annotations"], list)


# Spec: "| List order | Creation order |" -- creation order survives a
# reload of the file, not just the in-memory state.
def test_creation_order_survives_a_restart(serve, tmp_path, vault3):
    vault3()
    first = serve()
    for title in ("one", "two", "three"):
        create(first, title=title, timecode="1")
    body = serve().get("/catalog/vault/episodes/e1").body
    positions = [body.index(title) for title in ("one", "two", "three")]
    assert positions == sorted(positions)


# --------------------------------------------------------------------------
# Save behavior
# --------------------------------------------------------------------------
# Spec: "| Save behavior | `catalog.bak` written before persisting annotation
# changes |"
def test_create_writes_a_backup(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    assert os.path.isfile(backup_file(tmp_path))


# Spec: "| Save behavior | `catalog.bak` written before persisting annotation
# changes |" -- and for updates.
def test_update_writes_a_backup(serve, tmp_path, vault3):
    vault3()
    server = serve()
    annotation_id = created_id(server, tmp_path)
    os.remove(backup_file(tmp_path))
    update(server, id=annotation_id, title="Renamed")
    assert os.path.isfile(backup_file(tmp_path))


# Spec: "| Save behavior | `catalog.bak` written before persisting annotation
# changes |" -- and for deletes.
def test_delete_writes_a_backup(serve, tmp_path, vault3):
    vault3()
    server = serve()
    annotation_id = created_id(server, tmp_path)
    os.remove(backup_file(tmp_path))
    remove(server, id=annotation_id)
    assert os.path.isfile(backup_file(tmp_path))


# Spec: "| Backup before annotation | If catalog was already v3,
# `catalog.bak` contains pre-annotation catalog |"
def test_backup_holds_the_pre_annotation_catalog(serve, tmp_path, vault3):
    vault3()
    before = stored_catalog(tmp_path)
    create(serve(), title="Note", timecode="90")
    assert stored_backup(tmp_path) == before
    assert stored_backup(tmp_path)["episodes"][0]["annotations"] == []


# Spec: "| Backup before annotation | ... pre-annotation catalog |" -- the
# backup tracks the immediately preceding state, so a second create backs up
# the catalog that already holds the first annotation.
def test_backup_tracks_the_previous_state(serve, tmp_path, vault3):
    vault3()
    server = serve()
    create(server, title="first", timecode="1")
    create(server, title="second", timecode="2")
    backup = stored_backup(tmp_path)
    titles = [item["title"] for item in backup["episodes"][0]["annotations"]]
    assert titles == ["first"]


# Spec: "| Backup before annotation | ... |" -- an update's backup still has
# the old text.
def test_update_backup_holds_the_old_text(serve, tmp_path, vault3):
    vault3()
    server = serve()
    annotation_id = created_id(server, tmp_path, title="Before")
    update(server, id=annotation_id, title="After")
    backup = stored_backup(tmp_path)
    assert backup["episodes"][0]["annotations"][0]["title"] == "Before"
    assert only_annotation(tmp_path)["title"] == "After"


# Spec: "| Backup before annotation | ... |" -- a delete's backup still has
# the annotation.
def test_delete_backup_holds_the_removed_annotation(serve, tmp_path, vault3):
    vault3()
    server = serve()
    annotation_id = created_id(server, tmp_path, title="Doomed")
    remove(server, id=annotation_id)
    backup = stored_backup(tmp_path)
    assert [item["title"]
            for item in backup["episodes"][0]["annotations"]] == ["Doomed"]
    assert stored_annotations(tmp_path) == []


# --------------------------------------------------------------------------
# Read-after-write
# --------------------------------------------------------------------------
# Spec: "| Read-after-write behavior | Later `GET` to same entry detail page
# reflects create, update, or delete result by visibly rendering stored
# annotations |" -- "visibly": the text is in the rendered document, not only
# in an embedded script payload.
def test_annotation_is_visibly_rendered(serve, vault3):
    from viewer_helpers import text_of
    vault3()
    server = serve()
    create(server, title="Seen title", timecode="90", body="Seen body")
    visible = text_of(server.get("/catalog/vault/episodes/e1").body)
    assert "Seen title" in visible
    assert "Seen body" in visible


# Spec: "| Read-after-write behavior | Later `GET` ... |" -- a second reader
# (a fresh server process, so nothing is cached in memory) sees it too.
def test_a_fresh_server_sees_the_stored_annotation(serve, vault3):
    vault3()
    create(serve(), title="Persisted marker", timecode="90")
    assert "Persisted marker" in serve().get(
        "/catalog/vault/episodes/e1").body


# Spec: "| Read-after-write behavior | ... |" -- the entry listing page still
# works after a write.
def test_listing_still_renders_after_a_write(serve, vault3):
    vault3([v3_entry(id="e1", title="Ep One")])
    server = serve()
    create(server, title="Note", timecode="90")
    listing = server.get("/catalog/vault/episodes")
    assert listing.status == 200, listing
    assert "Ep One" in listing.body


# Spec: "Entry detail pages support user-managed annotations." -- the written
# catalog is still a valid vault for the rest of the CLI.
def test_written_catalog_is_still_readable_by_the_cli(serve, run, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    result = run("digest", "vault")
    assert result.returncode == 0, result
