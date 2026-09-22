"""Spec section: Annotation Error Handling."""

import pytest

from conftest import (
    assert_clean,
    create,
    entry_route,
    is_redirect,
    read_catalog,
    stored_annotations,
    v1_catalog,
    v1_entry,
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


# Spec: Missing `title` on create | HTTP `400` with message naming missing field
def test_create_without_a_title_names_the_field(entry):
    viewer, _ = entry
    response = viewer.send("POST", ROUTE, {"timecode": "90"})
    assert response.status_code == 400
    assert "title" in response.text


# Spec: Missing `timecode` on create | HTTP `400` with message naming missing field
def test_create_without_a_timecode_names_the_field(entry):
    viewer, _ = entry
    response = viewer.send("POST", ROUTE, {"title": "Chorus"})
    assert response.status_code == 400
    assert "timecode" in response.text


# Spec: Missing `title` on create | ... (nothing is stored)
def test_a_rejected_create_stores_nothing(entry):
    viewer, vault_dir = entry
    viewer.send("POST", ROUTE, {"timecode": "90"})
    assert stored_annotations(vault_dir, "episodes", "e1") == []


# Spec: Invalid `timecode` format | HTTP `400` with format error message
def test_an_invalid_timecode_reports_the_format(entry):
    viewer, _ = entry
    response = viewer.send("POST", ROUTE, {"title": "Chorus", "timecode": "half past"})
    assert response.status_code == 400
    assert "timecode" in response.text
    assert "HH:MM:SS" in response.text


# Spec: Missing `id` on update | HTTP `400` with message naming missing field
def test_update_without_an_id_names_the_field(entry):
    viewer, _ = entry
    response = viewer.send("PATCH", ROUTE, {"title": "Bridge"})
    assert response.status_code == 400
    assert "id" in response.text


# Spec: Missing `id` on delete | HTTP `400` with message naming missing field
def test_delete_without_an_id_names_the_field(entry):
    viewer, _ = entry
    response = viewer.send("DELETE", ROUTE, {})
    assert response.status_code == 400
    assert "id" in response.text


# Spec: Non-existent annotation `id` on update | HTTP `404`
def test_update_of_an_unknown_annotation_is_not_found(entry):
    viewer, _ = entry
    assert viewer.send("PATCH", ROUTE, {"id": "nope", "title": "Bridge"}).status_code == 404


# Spec: Non-existent annotation `id` on delete | HTTP `404`
def test_delete_of_an_unknown_annotation_is_not_found(entry):
    viewer, _ = entry
    assert viewer.send("DELETE", ROUTE, {"id": "nope"}).status_code == 404


# Spec: Non-existent annotation `id` on update | ... (the stored list is untouched)
def test_a_missed_update_leaves_the_list_alone(entry):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Chorus", timecode="90")
    viewer.send("PATCH", ROUTE, {"id": "nope", "title": "Bridge"})
    assert stored_annotations(vault_dir, "episodes", "e1")[0]["title"] == "Chorus"


# Spec: Malformed JSON body | HTTP `400`
def test_a_malformed_json_body_is_refused(entry):
    viewer, _ = entry
    assert viewer.send("POST", ROUTE, '{"title": "Chorus",').status_code == 400


# Spec: Malformed JSON body | ... (an empty body is not JSON either)
def test_an_empty_body_is_refused(entry):
    viewer, _ = entry
    assert viewer.send("POST", ROUTE, "").status_code == 400


# Spec: Malformed JSON body | ... (T77: valid JSON that is not an object)
@pytest.mark.parametrize("body", ['["title"]', '"Chorus"', "42", "null"])
def test_a_json_body_that_is_not_an_object_is_refused(entry, body):
    viewer, _ = entry
    assert viewer.send("POST", ROUTE, body).status_code == 400


# Spec: Malformed JSON body | ... on every annotation method
def test_a_malformed_body_is_refused_on_update_and_delete(entry):
    viewer, _ = entry
    assert viewer.send("PATCH", ROUTE, "{oops").status_code == 400
    assert viewer.send("DELETE", ROUTE, "{oops").status_code == 400


# Spec: Migration failure during auto-migration | HTTP `500` with error message
def test_a_migration_failure_is_a_server_error(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")], source_id=None))
    response = serve().send("POST", entry_route("vault", "entries", "e1"),
                            {"title": "Chorus", "timecode": "90"})
    assert response.status_code == 500
    assert response.text.strip()


# Spec: Migration failure during auto-migration | ... original catalog unchanged
def test_a_migration_failure_leaves_the_catalog_alone(serve, tmp_path):
    catalog = v1_catalog(entries=[v1_entry("e1", title="not a history")])
    vault_dir = write_vault(tmp_path, catalog)
    serve().send("POST", entry_route("vault", "entries", "e1"),
                 {"title": "Chorus", "timecode": "90"})
    assert read_catalog(vault_dir) == catalog
    assert not (vault_dir / "catalog.bak").exists()


# Spec: Any error response | Well-formed HTTP response; no raw traceback or stack trace
def test_every_rejected_annotation_stays_well_formed(entry):
    viewer, _ = entry
    for method, body in (
        ("POST", {"timecode": "90"}),
        ("POST", {"title": "Chorus", "timecode": "??"}),
        ("POST", "{oops"),
        ("PATCH", {"title": "Bridge"}),
        ("PATCH", {"id": "nope", "title": "Bridge"}),
        ("DELETE", {}),
        ("DELETE", {"id": "nope"}),
    ):
        assert_clean(viewer.send(method, ROUTE, body))


# Spec: Any error response | ... (a migration failure is a 500 without a traceback)
def test_a_migration_failure_leaks_nothing(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")], source_id=None))
    response = serve().send("POST", entry_route("vault", "entries", "e1"),
                            {"title": "Chorus", "timecode": "90"})
    assert "Content-Type" in response.headers
    assert "Traceback" not in response.text


# Spec: Non-existent annotation `id` ... (an entry the category does not hold)
def test_an_annotation_on_a_missing_entry_is_not_found(entry):
    viewer, _ = entry
    response = viewer.send("POST", entry_route("vault", "episodes", "ghost"),
                           {"title": "Chorus", "timecode": "90"})
    assert response.status_code == 404
    assert_clean(response)


# Spec: Annotation Error Handling (T71: a category this vault cannot hold)
def test_an_annotation_on_an_invalid_category_is_not_found(entry):
    viewer, _ = entry
    response = viewer.send("POST", entry_route("vault", "entries", "e1"),
                           {"title": "Chorus", "timecode": "90"})
    assert response.status_code == 404
    assert_clean(response)


# Spec: Any error response | ... (T76: an unknown vault answers like a GET does)
def test_an_annotation_on_an_unknown_vault_redirects_to_the_landing_page(serve, tmp_path):
    response = serve().send("POST", entry_route("ghost", "episodes", "e1"),
                            {"title": "Chorus", "timecode": "90"})
    assert is_redirect(response, "/")


# Spec: Any error response | ... (an annotation method on a non-entry route)
def test_an_annotation_method_off_the_entry_route_is_refused(entry):
    viewer, _ = entry
    for path in ("/catalog/vault/episodes", "/catalog/vault", "/nowhere"):
        assert viewer.send("PATCH", path, {"id": "a1", "title": "x"}).status_code == 404
