"""Spec section: Annotation Error Handling."""

import json

import pytest
from annotation_fixtures import V1_ENTRY, V3_ENTRY, annotate, created, delete, mark, patch, post, stored
from conftest import EPOCH_KEY, legacy_entry, write_vault
from detail_fixtures import v3_vault

#: Text a rendered stack trace would contain.
TRACEBACK_MARKER = "Traceback (most recent call last)"


def broken_v1_vault(tmp_path, **catalog):
    """A v1 vault whose version is readable but whose migration cannot finish."""
    return write_vault(tmp_path, "demo", {"version": 1, **catalog})


# Phrase: "| Missing `title` on create | HTTP `400` with message naming missing field |"
def test_create_without_a_title_names_the_field(viewer, tmp_path):
    v3_vault(tmp_path)

    response = post(viewer, {"timecode": "90"})

    assert response.status == 400
    assert "title" in response.body


# Phrase: "| Missing `timecode` on create | HTTP `400` with message naming missing field |"
def test_create_without_a_timecode_names_the_field(viewer, tmp_path):
    v3_vault(tmp_path)

    response = post(viewer, {"title": "chorus"})

    assert response.status == 400
    assert "timecode" in response.body


# Phrase: "| Invalid `timecode` format | HTTP `400` with format error message |"
def test_an_invalid_timecode_reports_a_format_error(viewer, tmp_path):
    v3_vault(tmp_path)

    response = post(viewer, mark(timecode="halfway"))

    assert response.status == 400
    assert "timecode" in response.body


# Phrase: "| Missing `id` on update | HTTP `400` with message naming missing field |"
def test_update_without_an_id_names_the_field(viewer, tmp_path):
    v3_vault(tmp_path)

    response = patch(viewer, {"title": "renamed"})

    assert response.status == 400
    assert "id" in response.body


# Phrase: "| Missing `id` on delete | HTTP `400` with message naming missing field |"
def test_delete_without_an_id_names_the_field(viewer, tmp_path):
    v3_vault(tmp_path)

    response = delete(viewer, {})

    assert response.status == 400
    assert "id" in response.body


# Phrase: "| Non-existent annotation `id` on update | HTTP `404` |"
def test_updating_an_unknown_annotation_is_not_found(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    created(viewer, vault)

    assert patch(viewer, {"id": "no-such-mark", "title": "x"}).status == 404


# Phrase: "| Non-existent annotation `id` on delete | HTTP `404` |"
def test_deleting_an_unknown_annotation_is_not_found(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    created(viewer, vault)

    assert delete(viewer, {"id": "no-such-mark"}).status == 404
    assert len(stored(vault)) == 1


# Phrase: "| Malformed JSON body | HTTP `400` |"
@pytest.mark.parametrize("raw", ["{not json", "", "[1, 2]", '{"title": "chorus",}'])
def test_a_malformed_json_body_is_rejected(viewer, tmp_path, raw):
    v3_vault(tmp_path)

    assert annotate(viewer, "POST", raw).status == 400


# Phrase: "| Migration failure during auto-migration | HTTP `500` with error message |"
def test_a_failed_auto_migration_reports_a_server_error(viewer, tmp_path):
    broken_v1_vault(tmp_path, entries=[legacy_entry("e1", EPOCH_KEY)])

    response = post(viewer, path=V1_ENTRY)

    assert response.status == 500
    assert response.body.strip() != ""


# Phrase: "| Migration failure during auto-migration | ... original catalog unchanged |"
def test_a_failed_auto_migration_leaves_the_catalog_alone(viewer, tmp_path):
    vault = broken_v1_vault(tmp_path, source_id="chan42", entries=[legacy_entry("e1", EPOCH_KEY, views="many")])
    before = (vault / "catalog.json").read_bytes()

    assert post(viewer, path=V1_ENTRY).status == 500

    assert (vault / "catalog.json").read_bytes() == before
    assert not (vault / "catalog.bak").exists()


# Phrase: "| Any error response | Well-formed HTTP response; no raw traceback or
# stack trace |"
@pytest.mark.parametrize(
    "method, payload, path",
    [
        ("POST", {"timecode": "90"}, V3_ENTRY),
        ("POST", "{not json", V3_ENTRY),
        ("PATCH", {"id": "nope", "title": "x"}, V3_ENTRY),
        ("DELETE", {}, V3_ENTRY),
        ("POST", {"title": "t", "timecode": "90"}, "/catalog/nowhere/episodes/e1"),
    ],
)
def test_no_error_response_carries_a_stack_trace(viewer, tmp_path, method, payload, path):
    v3_vault(tmp_path)

    response = annotate(viewer, method, payload, path)

    assert response.status >= 400
    assert TRACEBACK_MARKER not in response.body
    assert response.headers.get("Content-Type") is not None


# Phrase: "| Any error response | Well-formed HTTP response ... |" -- a failed
# migration is reported as a page, not as a dropped connection.
def test_a_failed_migration_response_is_well_formed(viewer, tmp_path):
    broken_v1_vault(tmp_path, entries=[legacy_entry("e1", EPOCH_KEY)])

    response = post(viewer, path=V1_ENTRY)

    assert TRACEBACK_MARKER not in response.body
    assert response.headers.get("Content-Type") is not None


# Phrase: "| Non-existent annotation `id` on update | HTTP `404` |" -- an entry
# the URL does not name is not searched for the id either.
def test_an_annotation_of_another_entry_is_not_found(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault)

    assert patch(viewer, {"id": annotation["id"], "title": "x"}, path="/catalog/demo/clips/c1").status == 404


# Phrase: "| Any error response |" -- an unknown vault, category or entry is
# answered rather than redirected as if the write had succeeded.
@pytest.mark.parametrize(
    "path",
    ["/catalog/nowhere/episodes/e1", "/catalog/demo/entries/e1", "/catalog/demo/episodes/missing"],
)
def test_a_mutation_target_that_does_not_exist_is_not_found(viewer, tmp_path, path):
    v3_vault(tmp_path)

    assert post(viewer, path=path).status == 404


# Phrase: "JSON with `id` and at least one of `title` or `body`" -- an update
# naming neither is a bad request.
def test_update_without_a_replacement_field_is_rejected(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault)

    assert patch(viewer, {"id": annotation["id"]}).status == 400


# Phrase: "| Malformed JSON body | HTTP `400` |" -- and nothing is persisted.
def test_a_rejected_request_persists_nothing(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    before = json.loads((vault / "catalog.json").read_text())

    annotate(viewer, "POST", "{not json")
    post(viewer, {"title": "no timecode"})

    assert json.loads((vault / "catalog.json").read_text()) == before
    assert not (vault / "catalog.bak").exists()
