"""Annotation Error Handling: the status, the message and the untouched catalog."""

import pytest

from conftest import SOURCE_URL, read_catalog, stored_annotations, v1_catalog, v1_entry, v3_catalog, v3_entry

ENTRY = "/catalog/v/episodes/a"


def entry_vault(served, catalog=None):
    """A served vault holding one episode `a`, v3 unless another catalog is given."""
    return served(catalog or v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]))


def create(client, **fields):
    """`POST` one annotation whose fields default to a valid create body."""
    return client.send_json("POST", ENTRY, {"title": "note", "timecode": "90", **fields})


def create_at(served, path):
    """A well-formed create body sent to `path` of the standard v3 vault."""
    return entry_vault(served).send_json("POST", path, {"title": "note", "timecode": "90"})


def stored_id(vault):
    return stored_annotations(vault)[0]["id"]


# Spec: Missing `title` on create | HTTP `400` with message naming missing field
def test_create_without_a_title_names_the_missing_field(served):
    response = entry_vault(served).send_json("POST", ENTRY, {"timecode": "90"})
    assert response.status_code == 400
    assert "title" in response.text


# Spec: Missing `timecode` on create | HTTP `400` with message naming missing field
def test_create_without_a_timecode_names_the_missing_field(served):
    response = entry_vault(served).send_json("POST", ENTRY, {"title": "note"})
    assert response.status_code == 400
    assert "timecode" in response.text


# Spec: Invalid `timecode` format | HTTP `400` with format error message
@pytest.mark.parametrize("text", ["", "abc", "-5", "1.5", "1:2:3:4", "1:", ":30", "90 ", "1:3a", "+5"])
def test_an_invalid_timecode_is_rejected_with_a_format_message(served, text):
    response = create(entry_vault(served), timecode=text)
    assert response.status_code == 400
    assert "timecode" in response.text


# Spec: Invalid `timecode` format | HTTP `400` (a non-string field is not a
# timecode either)
def test_a_non_string_timecode_is_rejected(served):
    assert create(entry_vault(served), timecode=90).status_code == 400


# Spec: `POST` Annotation Fields | `title` | string (a non-string title is rejected)
def test_a_non_string_title_is_rejected(served):
    assert create(entry_vault(served), title=7).status_code == 400


# Spec: Missing `id` on update | HTTP `400` with message naming missing field
def test_update_without_an_id_names_the_missing_field(served):
    response = entry_vault(served).send_json("PATCH", ENTRY, {"title": "renamed"})
    assert response.status_code == 400
    assert "id" in response.text


# Spec: Missing `id` on delete | HTTP `400` with message naming missing field
def test_delete_without_an_id_names_the_missing_field(served):
    response = entry_vault(served).send_json("DELETE", ENTRY, {})
    assert response.status_code == 400
    assert "id" in response.text


# Spec: `PATCH` | JSON with `id` and at least one of `title` or `body`
def test_update_without_a_title_or_body_is_rejected(served, tmp_path):
    client = entry_vault(served)
    create(client)
    response = client.send_json("PATCH", ENTRY, {"id": stored_id(tmp_path / "v")})
    assert response.status_code == 400


# Spec: Non-existent annotation `id` on update | HTTP `404`
def test_update_of_an_unknown_annotation_is_not_found(served):
    assert entry_vault(served).send_json("PATCH", ENTRY, {"id": "ghost", "title": "x"}).status_code == 404


# Spec: Non-existent annotation `id` on delete | HTTP `404`
def test_delete_of_an_unknown_annotation_is_not_found(served):
    assert entry_vault(served).send_json("DELETE", ENTRY, {"id": "ghost"}).status_code == 404


# Spec: Malformed JSON body | HTTP `400`
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_a_malformed_json_body_is_rejected(served, method):
    assert entry_vault(served).send_json(method, ENTRY, raw="{'title': ").status_code == 400


# Spec: Malformed JSON body | HTTP `400` (an empty body carries no JSON object)
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_an_empty_body_is_rejected(served, method):
    assert entry_vault(served).send_json(method, ENTRY, raw="").status_code == 400


# Spec: Malformed JSON body | HTTP `400` (valid JSON that is not an object)
def test_a_json_body_that_is_not_an_object_is_rejected(served):
    assert entry_vault(served).send_json("POST", ENTRY, raw="[1, 2]").status_code == 400


# Spec: Annotation Methods | `/catalog/<name>/<category>/<id>` (an entry the
# category does not hold)
def test_an_unknown_entry_is_not_found(served):
    assert create_at(served, "/catalog/v/episodes/ghost").status_code == 404


# Spec: Annotation Methods | `/catalog/<name>/<category>/<id>` (a category the
# vault's version does not have)
def test_an_unknown_category_is_not_found(served):
    assert create_at(served, "/catalog/v/entries/a").status_code == 404


# Spec: Annotation Methods | `/catalog/<name>/<category>/<id>` (a vault that is
# not there)
def test_an_unknown_vault_is_not_found(served):
    assert create_at(served, "/catalog/ghost/episodes/a").status_code == 404


# Spec: Annotation Methods | `/catalog/<name>/<category>/<id>` (shorter routes
# take no annotation methods)
@pytest.mark.parametrize("path", ["/", "/catalog/v", "/catalog/v/episodes"])
def test_routes_that_are_not_an_entry_take_no_annotation_methods(served, path):
    client = entry_vault(served)
    assert client.send_json("PATCH", path, {"id": "1", "title": "x"}).status_code == 404
    assert client.send_json("DELETE", path, {"id": "1"}).status_code == 404


# Spec: Migration failure during auto-migration | HTTP `500` with error message;
# original catalog unchanged
def test_a_failing_auto_migration_answers_with_a_server_error(served):
    broken = v1_catalog([dict(v1_entry("a"), width="wide")])
    response = entry_vault(served, broken).send_json("POST", "/catalog/v/entries/a", {"title": "n", "timecode": "1"})
    assert response.status_code == 500
    assert response.text.strip()


# Spec: Migration failure during auto-migration | ... original catalog unchanged
def test_a_failing_auto_migration_leaves_the_catalog_alone(served, tmp_path):
    client = entry_vault(served, v1_catalog([dict(v1_entry("a"), width="wide")]))
    before = (tmp_path / "v" / "catalog.json").read_text()
    client.send_json("POST", "/catalog/v/entries/a", {"title": "n", "timecode": "1"})
    assert (tmp_path / "v" / "catalog.json").read_text() == before
    assert not (tmp_path / "v" / "catalog.bak").exists()


# Spec: Annotation Error Handling | a rejected request persists nothing
def test_a_rejected_request_persists_nothing(served, tmp_path):
    client = entry_vault(served)
    before = (tmp_path / "v" / "catalog.json").read_text()
    create(client, timecode="later")
    assert (tmp_path / "v" / "catalog.json").read_text() == before
    assert not (tmp_path / "v" / "catalog.bak").exists()


# Spec: Any error response | Well-formed HTTP response; no raw traceback or
# stack trace
@pytest.mark.parametrize(
    ("method", "payload"),
    [("POST", {}), ("PATCH", {"id": "ghost", "title": "x"}), ("DELETE", {"id": "ghost"})],
)
def test_error_responses_are_well_formed_and_carry_no_traceback(served, method, payload):
    response = entry_vault(served).send_json(method, ENTRY, payload)
    assert response.status_code in (400, 404)
    assert "Content-Type" in response.headers
    assert int(response.headers["Content-Length"]) == len(response.content)
    assert "Traceback" not in response.text
    assert "File \"" not in response.text


# Spec: Any error response | Well-formed HTTP response (the connection stays
# usable for the next request)
def test_the_viewer_keeps_answering_after_an_error(served, tmp_path):
    client = entry_vault(served)
    assert client.send_json("POST", ENTRY, {"title": "note"}).status_code == 400
    assert create(client).status_code in (302, 303)
    assert len(stored_annotations(tmp_path / "v")) == 1


# Spec: Migration failure during auto-migration | HTTP `500` ... (no traceback
# reaches the browser)
def test_a_server_error_carries_no_traceback(served):
    broken = v1_catalog([dict(v1_entry("a"), title="not-a-history")])
    response = entry_vault(served, broken).send_json("POST", "/catalog/v/entries/a", {"title": "n", "timecode": "1"})
    assert response.status_code == 500
    assert "Traceback" not in response.text


# Spec: Annotation Error Handling | an unreadable catalog is not annotated
def test_an_unreadable_catalog_is_not_annotated(served, make_vault, tmp_path):
    client = entry_vault(served)
    make_vault("{ not json", "broken")
    assert client.send_json("POST", "/catalog/broken/episodes/a", {"title": "n", "timecode": "1"}).status_code in (
        404,
        500,
    )
    assert read_catalog(tmp_path / "v")["episodes"][0]["annotations"] == []
