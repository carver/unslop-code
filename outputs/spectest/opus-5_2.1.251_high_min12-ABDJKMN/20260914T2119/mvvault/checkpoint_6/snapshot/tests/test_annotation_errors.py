"""Spec: the Annotation Error Handling table."""
import json
import os
import stat

import pytest

from annotation_helpers import (assert_clean, create, created_id, mutate,
                                remove, stored_annotations, stored_catalog,
                                update)
from digest_helpers import legacy_entry, v1, v1_entry, v2, v3, v3_entry


@pytest.fixture
def vault3(make_vault):
    def _make(entries=None, **kwargs):
        return make_vault(v3(episodes=entries or [v3_entry(id="e1")]),
                          **kwargs)
    return _make


def message_of(response):
    from viewer_helpers import text_of
    return text_of(response.body)


# --------------------------------------------------------------------------
# Create errors
# --------------------------------------------------------------------------
# Spec: "| Missing `title` on create | HTTP `400` with message naming missing
# field |"
def test_missing_title_is_400_naming_the_field(serve, vault3):
    vault3()
    response = create(serve(), timecode="90")
    assert response.status == 400, response
    assert "title" in message_of(response).lower()
    assert_clean(response)


# Spec: "| Missing `timecode` on create | HTTP `400` with message naming
# missing field |"
def test_missing_timecode_is_400_naming_the_field(serve, vault3):
    vault3()
    response = create(serve(), title="Note")
    assert response.status == 400, response
    assert "timecode" in message_of(response).lower()
    assert_clean(response)


# Spec: "| Missing `title` ... | Missing `timecode` ... |" -- an empty body
# object is missing both.
def test_empty_object_is_400(serve, vault3):
    vault3()
    response = mutate(serve(), "POST", raw="{}")
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| Invalid `timecode` format | HTTP `400` with format error message |"
def test_invalid_timecode_is_400_with_a_format_message(serve, vault3):
    vault3()
    response = create(serve(), title="Note", timecode="half past two")
    assert response.status == 400, response
    assert "timecode" in message_of(response).lower()
    assert_clean(response)


# Spec: "| Missing `title` ... |" -- a rejected create stores nothing.
@pytest.mark.parametrize("payload", [{"timecode": "90"}, {"title": "Note"},
                                     {"title": "Note", "timecode": "bad"}])
def test_rejected_create_stores_nothing(serve, tmp_path, vault3, payload):
    vault3()
    mutate(serve(), "POST", payload)
    assert stored_annotations(tmp_path) == []


# Spec: "| Missing `title` ... |" -- a rejected create writes no backup, so
# the vault is untouched.
def test_rejected_create_does_not_write(serve, tmp_path, vault3):
    vault3()
    before = stored_catalog(tmp_path)
    create(serve(), timecode="90")
    assert stored_catalog(tmp_path) == before
    assert not os.path.isfile(os.path.join(str(tmp_path), "vault",
                                           "catalog.bak"))


# --------------------------------------------------------------------------
# Update / delete errors
# --------------------------------------------------------------------------
# Spec: "| Missing `id` on update | HTTP `400` with message naming missing
# field |"
def test_missing_id_on_update_is_400_naming_the_field(serve, vault3):
    vault3()
    response = update(serve(), title="Renamed")
    assert response.status == 400, response
    assert "id" in message_of(response).lower()
    assert_clean(response)


# Spec: "| Missing `id` on delete | HTTP `400` with message naming missing
# field |"
def test_missing_id_on_delete_is_400_naming_the_field(serve, vault3):
    vault3()
    response = mutate(serve(), "DELETE", {})
    assert response.status == 400, response
    assert "id" in message_of(response).lower()
    assert_clean(response)


# Spec: "| `PATCH` | ... | JSON with `id` and at least one of `title` or
# `body` |" -- neither field present is a bad request (see AMBIGUITIES T66).
def test_update_without_title_or_body_is_400(serve, tmp_path, vault3):
    vault3()
    server = serve()
    annotation_id = created_id(server, tmp_path, title="Untouched")
    response = update(server, id=annotation_id)
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| Non-existent annotation `id` on update | HTTP `404` |"
def test_unknown_id_on_update_is_404(serve, tmp_path, vault3):
    vault3()
    server = serve()
    created_id(server, tmp_path)
    response = update(server, id="no-such-annotation", title="x")
    assert response.status == 404, response
    assert_clean(response)


# Spec: "| Non-existent annotation `id` on delete | HTTP `404` |"
def test_unknown_id_on_delete_is_404(serve, tmp_path, vault3):
    vault3()
    server = serve()
    created_id(server, tmp_path)
    response = remove(server, id="no-such-annotation")
    assert response.status == 404, response
    assert_clean(response)


# Spec: "| Non-existent annotation `id` on update | HTTP `404` |" -- the
# stored annotations are left exactly as they were.
def test_unknown_id_leaves_annotations_untouched(serve, tmp_path, vault3):
    vault3()
    server = serve()
    created_id(server, tmp_path, title="Kept")
    update(server, id="ghost", title="x")
    remove(server, id="ghost")
    assert [item["title"] for item in stored_annotations(tmp_path)] == ["Kept"]


# Spec: "| Missing entry in specified category | HTTP `404` ... |" (viewer
# error table) -- an annotation aimed at an entry that is not there.
@pytest.mark.parametrize("method,payload", [
    ("POST", {"title": "Note", "timecode": "90"}),
    ("PATCH", {"id": "a", "title": "x"}),
    ("DELETE", {"id": "a"}),
])
def test_unknown_entry_id_is_404(serve, vault3, method, payload):
    vault3()
    response = mutate(serve(), method, payload, entry_id="nosuch")
    assert response.status == 404, response
    assert_clean(response)


# --------------------------------------------------------------------------
# Malformed bodies
# --------------------------------------------------------------------------
# Spec: "| Malformed JSON body | HTTP `400` |"
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
@pytest.mark.parametrize("raw", ["{", "not json at all", "{'title': 'x'}",
                                 '{"title": "x",}', ""])
def test_malformed_json_body_is_400(serve, vault3, method, raw):
    vault3()
    response = mutate(serve(), method, raw=raw)
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| Malformed JSON body | HTTP `400` |" -- valid JSON that is not an
# object cannot carry the documented fields either.
@pytest.mark.parametrize("raw", ["[]", '"title"', "42", "null", "true"])
def test_non_object_json_body_is_400(serve, vault3, raw):
    vault3()
    response = mutate(serve(), "POST", raw=raw)
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| Malformed JSON body | HTTP `400` |" -- a form-encoded body is not
# the documented JSON body.
def test_form_encoded_body_is_400(serve, vault3):
    vault3()
    response = mutate(serve(), "POST", raw="title=Note&timecode=90",
                      headers={"Content-Type":
                               "application/x-www-form-urlencoded"})
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| Malformed JSON body | HTTP `400` |" -- nothing is stored.
def test_malformed_json_stores_nothing(serve, tmp_path, vault3):
    vault3()
    mutate(serve(), "POST", raw="{oops")
    assert stored_annotations(tmp_path) == []


# --------------------------------------------------------------------------
# Field types
# --------------------------------------------------------------------------
# Spec: "| `title` | string | yes |" -- a non-string title is not a title.
@pytest.mark.parametrize("value", [None, 5, [], {}, True])
def test_non_string_title_is_400(serve, vault3, value):
    vault3()
    response = mutate(serve(), "POST", {"title": value, "timecode": "90"})
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| `body` | string | no | `null` |" -- a non-string, non-null body is
# rejected rather than stored as-is.
@pytest.mark.parametrize("value", [5, [], {"a": 1}])
def test_non_string_body_is_400(serve, vault3, value):
    vault3()
    response = mutate(serve(), "POST",
                      {"title": "Note", "timecode": "90", "body": value})
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| `body` | string | no | `null` |" -- an explicit null body is the
# documented default value, not an error.
def test_explicit_null_body_is_accepted(serve, tmp_path, vault3):
    vault3()
    response = mutate(serve(), "POST",
                      {"title": "Note", "timecode": "90", "body": None})
    assert response.is_redirect, response
    assert stored_annotations(tmp_path)[0]["body"] is None


# Spec: "| `id` | string | yes |" -- a non-string id cannot name an
# annotation.
@pytest.mark.parametrize("value", [None, 5, [], {}])
def test_non_string_id_is_rejected(serve, vault3, value):
    vault3()
    response = mutate(serve(), "PATCH", {"id": value, "title": "x"})
    assert response.status in (400, 404), response
    assert_clean(response)


# --------------------------------------------------------------------------
# Migration failure
# --------------------------------------------------------------------------
# Spec: "| Migration failure during auto-migration | HTTP `500` with error
# message; original catalog unchanged |"
@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_migration_failure_is_500_and_leaves_the_catalog(serve, tmp_path,
                                                         make_vault):
    original = v1(entries=[v1_entry(id="e1")])
    directory = make_vault(original)
    server = serve()
    mode = os.stat(str(directory)).st_mode
    os.chmod(str(directory), stat.S_IRUSR | stat.S_IXUSR)
    try:
        response = create(server, title="Note", timecode="90",
                          category="entries")
        assert response.status == 500, response
        assert_clean(response)
        assert message_of(response).strip() != ""
    finally:
        os.chmod(str(directory), mode)
    assert stored_catalog(tmp_path) == original


# Spec: "| Migration failure during auto-migration | ... original catalog
# unchanged |" -- a v3 write failure is handled the same way.
@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_write_failure_is_500_and_leaves_the_catalog(serve, tmp_path,
                                                     make_vault):
    original = v3(episodes=[v3_entry(id="e1")])
    directory = make_vault(original)
    server = serve()
    mode = os.stat(str(directory)).st_mode
    os.chmod(str(directory), stat.S_IRUSR | stat.S_IXUSR)
    try:
        response = create(server, title="Note", timecode="90")
        assert response.status == 500, response
        assert_clean(response)
    finally:
        os.chmod(str(directory), mode)
    assert stored_catalog(tmp_path) == original


# --------------------------------------------------------------------------
# Well-formed responses
# --------------------------------------------------------------------------
# Spec: "| Any error response | Well-formed HTTP response; no raw traceback or
# stack trace |"
@pytest.mark.parametrize("method,payload,entry_id", [
    ("POST", {}, "e1"),
    ("POST", {"title": "x", "timecode": "??"}, "e1"),
    ("PATCH", {}, "e1"),
    ("DELETE", {}, "e1"),
    ("POST", {"title": "x", "timecode": "1"}, "ghost"),
])
def test_error_responses_are_well_formed(serve, vault3, method, payload,
                                         entry_id):
    vault3()
    response = mutate(serve(), method, payload, entry_id=entry_id)
    assert 400 <= response.status < 500, response
    assert "<html" in response.body.lower()
    assert_clean(response)


# Spec: "| Any error response | Well-formed HTTP response ... |" -- the server
# keeps serving afterwards.
def test_server_survives_annotation_errors(serve, vault3):
    vault3([v3_entry(id="e1", title="Fine")])
    server = serve()
    mutate(server, "POST", raw="{{{")
    mutate(server, "PATCH", {})
    mutate(server, "DELETE", {"id": "ghost"})
    assert "Fine" in server.get("/catalog/vault/episodes/e1").body


# Spec: "| Non-existent vault on *any* `/catalog/<name>` route | Redirect to
# `/` ... |" (viewer error table) -- annotation methods included.
def test_annotation_on_a_missing_vault(serve):
    response = create(serve(), title="Note", timecode="90", name="ghost")
    assert response.status in (302, 303, 404), response
    assert_clean(response)


# Spec: "| Invalid category ... | Redirect ... or return HTTP `400`/`404` |"
# -- a category the vault's version does not have.
def test_annotation_on_an_invalid_category(serve, vault3):
    vault3()
    response = create(serve(), title="Note", timecode="90",
                      category="entries")
    assert response.status in (302, 303, 400, 404), response
    assert_clean(response)
