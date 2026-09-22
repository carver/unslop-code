"""Spec: the `PATCH` and `DELETE` annotation methods and their field tables."""
import pytest

from annotation_helpers import (assert_clean, create, created_id, mutate,
                                only_annotation, redirect_path,
                                redirect_query, remove, stored_annotations,
                                update)
from digest_helpers import v3, v3_entry


@pytest.fixture
def vault3(make_vault):
    def _make(entries=None, **kwargs):
        return make_vault(v3(episodes=entries or [v3_entry(id="e1")]),
                          **kwargs)
    return _make


@pytest.fixture
def one(serve, tmp_path, vault3):
    """A served v3 vault whose entry already carries one annotation."""
    def _setup(title="Note", timecode="90", body="Original body"):
        vault3()
        server = serve()
        annotation_id = created_id(server, tmp_path, title=title,
                                   timecode=timecode, body=body)
        return server, annotation_id
    return _setup


# --------------------------------------------------------------------------
# `PATCH`
# --------------------------------------------------------------------------
# Spec: "| `PATCH` | Update annotation | JSON with `id` and at least one of
# `title` or `body` | Redirect to entry detail page |"
def test_patch_redirects_to_the_entry_detail_page(one):
    server, annotation_id = one()
    response = update(server, id=annotation_id, title="Renamed")
    assert response.is_redirect, response
    assert redirect_path(response) == "/catalog/vault/episodes/e1"


# Spec: "| `PATCH` | ... | Redirect to entry detail page |" -- no `?timecode`
# is required on an update; the create redirect is the one that carries it.
def test_patch_redirect_has_no_timecode_requirement(one):
    server, annotation_id = one()
    response = update(server, id=annotation_id, title="Renamed")
    values = redirect_query(response).get("timecode")
    assert values is None or values == ["90"]


# Spec: "| `title` | string | no | Replace existing title when present |"
def test_patch_replaces_the_title(one, tmp_path):
    server, annotation_id = one(title="Before")
    update(server, id=annotation_id, title="After")
    assert only_annotation(tmp_path)["title"] == "After"


# Spec: "| `body` | string | no | Replace existing body when present |"
def test_patch_replaces_the_body(one, tmp_path):
    server, annotation_id = one(body="Before")
    update(server, id=annotation_id, body="After")
    assert only_annotation(tmp_path)["body"] == "After"


# Spec: "| `title` | ... | Replace existing title ... | `body` | ... |" --
# both at once.
def test_patch_replaces_title_and_body_together(one, tmp_path):
    server, annotation_id = one(title="T0", body="B0")
    update(server, id=annotation_id, title="T1", body="B1")
    stored = only_annotation(tmp_path)
    assert (stored["title"], stored["body"]) == ("T1", "B1")


# Spec: "| omitted fields | n/a | allowed | Leave stored value unchanged |" --
# an omitted body survives a title-only update.
def test_omitted_body_is_left_unchanged(one, tmp_path):
    server, annotation_id = one(title="T0", body="Keep me")
    update(server, id=annotation_id, title="T1")
    assert only_annotation(tmp_path)["body"] == "Keep me"


# Spec: "| omitted fields | ... | Leave stored value unchanged |" -- an
# omitted title survives a body-only update.
def test_omitted_title_is_left_unchanged(one, tmp_path):
    server, annotation_id = one(title="Keep me", body="B0")
    update(server, id=annotation_id, body="B1")
    assert only_annotation(tmp_path)["title"] == "Keep me"


# Spec: "| omitted fields | ... | Leave stored value unchanged |" -- the
# timecode is not part of the update surface and never moves.
def test_patch_leaves_the_timecode_unchanged(one, tmp_path):
    server, annotation_id = one(timecode="1:30")
    update(server, id=annotation_id, title="Renamed")
    assert only_annotation(tmp_path)["timecode"] == 90


# Spec: "| `id` | string | yes | Annotation identifier inside current entry |"
# -- the id itself is not rewritten by an update.
def test_patch_keeps_the_annotation_id(one, tmp_path):
    server, annotation_id = one()
    update(server, id=annotation_id, title="Renamed")
    assert only_annotation(tmp_path)["id"] == annotation_id


# Spec: "| `id` | ... | Annotation identifier inside current entry |" -- only
# the addressed annotation changes.
def test_patch_touches_only_the_named_annotation(serve, tmp_path, vault3):
    vault3()
    server = serve()
    first = created_id(server, tmp_path, title="first", timecode="1")
    create(server, title="second", timecode="2")
    update(server, id=first, title="first updated")
    assert [item["title"] for item in stored_annotations(tmp_path)] == [
        "first updated", "second"]


# Spec: "| List order | Creation order |" -- an update does not reorder.
def test_patch_preserves_list_order(serve, tmp_path, vault3):
    vault3()
    server = serve()
    create(server, title="a", timecode="1")
    second = created_id(server, tmp_path, title="b", timecode="2")
    create(server, title="c", timecode="3")
    update(server, id=second, title="b2")
    assert [item["title"] for item in stored_annotations(tmp_path)] == [
        "a", "b2", "c"]


# Spec: "| `id` | string | yes | Annotation identifier inside current entry |"
# -- an id that belongs to another entry is not "inside current entry".
def test_patch_id_from_another_entry_is_not_found(serve, tmp_path, vault3):
    vault3([v3_entry(id="e1"), v3_entry(id="e2")])
    server = serve()
    other = created_id(server, tmp_path, title="other", timecode="5",
                       entry_id="e2")
    response = update(server, id=other, title="hijack", entry_id="e1")
    assert response.status == 404, response
    assert_clean(response)


# --------------------------------------------------------------------------
# `DELETE`
# --------------------------------------------------------------------------
# Spec: "| `DELETE` | Delete annotation | JSON with `id` | Redirect to entry
# detail page |"
def test_delete_redirects_to_the_entry_detail_page(one):
    server, annotation_id = one()
    response = remove(server, id=annotation_id)
    assert response.is_redirect, response
    assert redirect_path(response) == "/catalog/vault/episodes/e1"


# Spec: "| `DELETE` | Delete annotation | JSON with `id` | ... |"
def test_delete_removes_the_annotation(one, tmp_path):
    server, annotation_id = one()
    remove(server, id=annotation_id)
    assert stored_annotations(tmp_path) == []


# Spec: "| `DELETE` | ... |" -- only the named annotation goes.
def test_delete_removes_only_the_named_annotation(serve, tmp_path, vault3):
    vault3()
    server = serve()
    create(server, title="keep me", timecode="1")
    doomed = created_id(server, tmp_path, title="drop me", timecode="2")
    create(server, title="keep me too", timecode="3")
    remove(server, id=doomed)
    assert [item["title"] for item in stored_annotations(tmp_path)] == [
        "keep me", "keep me too"]


# Spec: "| List order | Creation order |" -- the survivors keep their order.
def test_delete_preserves_creation_order(serve, tmp_path, vault3):
    vault3()
    server = serve()
    first = created_id(server, tmp_path, title="a", timecode="1")
    create(server, title="b", timecode="2")
    create(server, title="c", timecode="3")
    remove(server, id=first)
    assert [item["title"] for item in stored_annotations(tmp_path)] == [
        "b", "c"]


# Spec: "| `id` | string | yes |" -- deleting the same id twice is a
# not-found on the second attempt.
def test_delete_twice_is_not_found_the_second_time(one):
    server, annotation_id = one()
    assert remove(server, id=annotation_id).is_redirect
    second = remove(server, id=annotation_id)
    assert second.status == 404, second


# Spec: "| `id` | string | yes |" -- the annotations key survives an empty
# list rather than disappearing.
def test_delete_leaves_an_empty_list(one, tmp_path):
    server, annotation_id = one()
    remove(server, id=annotation_id)
    stored = stored_annotations(tmp_path)
    assert isinstance(stored, list) and stored == []


# Spec: "| `DELETE` | ... JSON with `id` |" -- the request body is JSON.
def test_delete_body_is_read_as_json(one, tmp_path):
    server, annotation_id = one()
    response = mutate(server, "DELETE", raw='{"id": "%s"}' % annotation_id)
    assert response.is_redirect, response
    assert stored_annotations(tmp_path) == []


# --------------------------------------------------------------------------
# Read-after-write
# --------------------------------------------------------------------------
# Spec: "| Read-after-write behavior | Later `GET` to same entry detail page
# reflects create, update, or delete result by visibly rendering stored
# annotations |" -- create.
def test_get_after_create_shows_the_annotation(one):
    server, _ = one(title="Visible marker")
    body = server.get("/catalog/vault/episodes/e1").body
    assert "Visible marker" in body


# Spec: "| Read-after-write behavior | ... |" -- update.
def test_get_after_update_shows_the_new_text(one):
    server, annotation_id = one(title="Old title", body="Old body")
    update(server, id=annotation_id, title="New title", body="New body")
    body = server.get("/catalog/vault/episodes/e1").body
    assert "New title" in body
    assert "New body" in body
    assert "Old title" not in body


# Spec: "| Read-after-write behavior | ... |" -- delete.
def test_get_after_delete_drops_the_annotation(one):
    server, annotation_id = one(title="Doomed marker")
    remove(server, id=annotation_id)
    body = server.get("/catalog/vault/episodes/e1").body
    assert "Doomed marker" not in body


# Spec: "| Annotation list order | Same order as stored in `catalog.json` |"
def test_page_lists_annotations_in_stored_order(serve, tmp_path, vault3):
    vault3()
    server = serve()
    for title in ("alpha", "beta", "gamma"):
        create(server, title=title, timecode="1")
    body = server.get("/catalog/vault/episodes/e1").body
    positions = [body.index(title) for title in ("alpha", "beta", "gamma")]
    assert positions == sorted(positions)
    assert [item["title"] for item in stored_annotations(tmp_path)] == [
        "alpha", "beta", "gamma"]
