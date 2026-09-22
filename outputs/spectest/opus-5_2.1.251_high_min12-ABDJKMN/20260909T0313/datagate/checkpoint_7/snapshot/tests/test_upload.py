"""Spec section: Export, Upload, and Multi-Format Support -> File Upload."""

import io
import json

import pytest

SIMPLE = b"name,age\nalice,30\nbob,41\n"


# Phrase: "`POST /upload` accepts multipart form with field `file` ..."
def test_upload_accepts_file_field(upload):
    response = upload(SIMPLE)
    assert response.status_code == 200


# Phrase: "`POST /upload` accepts multipart form with field ... or `attachment`."
def test_upload_accepts_attachment_field(upload):
    response = upload(SIMPLE, field="attachment")
    assert response.status_code == 200


# Phrase: 'Success: {"ok": true, "endpoint": "/datasets/<id>"}'
def test_upload_success_body_shape(upload):
    payload = upload(SIMPLE).get_json()
    assert payload["ok"] is True
    assert set(payload) == {"ok", "endpoint"}
    assert payload["endpoint"].startswith("/datasets/")
    assert payload["endpoint"] != "/datasets/"


# Phrase: 'Success: {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: `attachment` yields the same envelope as `file`.
def test_attachment_success_body_shape(upload):
    payload = upload(SIMPLE, field="attachment").get_json()
    assert payload["ok"] is True and payload["endpoint"].startswith("/datasets/")


# Context: the returned endpoint serves the uploaded rows.
def test_upload_endpoint_is_usable(upload, client):
    endpoint = upload(SIMPLE).get_json()["endpoint"]
    response = client.get(endpoint)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
def test_same_bytes_same_id(upload):
    first = upload(SIMPLE).get_json()["endpoint"]
    second = upload(SIMPLE).get_json()["endpoint"]
    assert first == second


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: the id is over the bytes, so a different file name is still the same id.
def test_same_bytes_different_filename_same_id(upload):
    first = upload(SIMPLE, filename="a.csv").get_json()["endpoint"]
    second = upload(SIMPLE, filename="totally-different.csv").get_json()["endpoint"]
    assert first == second


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: the id is over the bytes, so it does not depend on the field used.
def test_same_bytes_via_either_field_same_id(upload):
    first = upload(SIMPLE, field="file").get_json()["endpoint"]
    second = upload(SIMPLE, field="attachment").get_json()["endpoint"]
    assert first == second


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: different bytes must not collide onto one id.
def test_different_bytes_different_id(upload):
    first = upload(SIMPLE).get_json()["endpoint"]
    second = upload(b"x,y\n1,2\n").get_json()["endpoint"]
    assert first != second


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: stable across a store reset, i.e. derived from bytes not a counter.
def test_upload_id_survives_store_reset(upload):
    import datagate

    first = upload(SIMPLE).get_json()["endpoint"]
    datagate.reset_store()
    assert upload(SIMPLE).get_json()["endpoint"] == first


# Phrase: "- non-multipart request: `HTTP 415`"
def test_non_multipart_json_is_415(client):
    response = client.post("/upload", data=json.dumps({"a": 1}),
                           content_type="application/json")
    assert response.status_code == 415


# Phrase: "- non-multipart request: `HTTP 415`"
def test_non_multipart_urlencoded_is_415(client):
    response = client.post("/upload", data={"file": "name,age\nalice,30\n"},
                           content_type="application/x-www-form-urlencoded")
    assert response.status_code == 415


# Phrase: "- non-multipart request: `HTTP 415`"
def test_non_multipart_raw_csv_body_is_415(client):
    response = client.post("/upload", data=SIMPLE, content_type="text/csv")
    assert response.status_code == 415


# Phrase: "- non-multipart request: `HTTP 415`"
# Context: a request with no declared content type is not multipart either.
def test_missing_content_type_is_415(client):
    response = client.post("/upload", data=b"")
    assert response.status_code == 415


# Phrase: "- non-multipart upload: `HTTP 415`" (Error Handling)
# Context: 415 responses still carry the standard JSON envelope.
def test_415_uses_the_standard_envelope(client):
    response = client.post("/upload", data=b"{}", content_type="application/json")
    payload = response.get_json()
    assert payload["ok"] is False and isinstance(payload["error"], str)
    assert set(payload) == {"ok", "error"}


# Phrase: "- ... missing both `file` and `attachment`: `HTTP 400`"
def test_multipart_without_either_field_is_400(client):
    response = client.post("/upload", data={"other": "value"},
                           content_type="multipart/form-data")
    assert response.status_code == 400


# Phrase: "- missing file field: `HTTP 400`" (Error Handling)
# Context: a file part under a third field name is not `file`/`attachment`.
def test_file_under_a_wrong_field_name_is_400(upload):
    response = upload(SIMPLE, field="upload")
    assert response.status_code == 400


# Phrase: "- ... missing both `file` and `attachment`: `HTTP 400`"
# Context: an empty multipart body has neither field.
def test_empty_multipart_body_is_400(client):
    response = client.post("/upload", data={}, content_type="multipart/form-data")
    assert response.status_code == 400


# Phrase: "- malformed multipart ...: `HTTP 400`"
def test_malformed_multipart_is_400(client):
    response = client.post(
        "/upload",
        data=b"------bogus\r\nthis is not a valid multipart body",
        content_type="multipart/form-data; boundary=----bogus",
    )
    assert response.status_code == 400


# Phrase: "- malformed multipart ...: `HTTP 400`"
# Context: a multipart content type with no boundary parameter is malformed.
def test_multipart_without_boundary_is_400(client):
    response = client.post("/upload", data=b"whatever",
                           content_type="multipart/form-data")
    assert response.status_code == 400


# Phrase: "- malformed multipart or missing both ...: `HTTP 400`"
# Context: 400 responses still carry the standard JSON envelope.
def test_400_uses_the_standard_envelope(client):
    response = client.post("/upload", data={"other": "v"},
                           content_type="multipart/form-data")
    payload = response.get_json()
    assert payload["ok"] is False and isinstance(payload["error"], str)
    assert set(payload) == {"ok", "error"}


# Phrase: "`POST /upload` accepts multipart form"
# Context: only POST is defined for /upload.
def test_get_upload_is_not_allowed(client):
    response = client.get("/upload")
    assert response.status_code == 405
    assert response.get_json()["ok"] is False


# Phrase: "all errors use the standard JSON envelope"
# Context: a non-tabular upload body is a 400 like a non-tabular /convert source.
def test_non_tabular_upload_is_400(upload):
    response = upload(b"<html><body>nope</body></html>", filename="page.html")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "The first sheet must be tabular (header + at least one data row)"
# Context: applied to plain CSV uploads too -- a header with no data row.
def test_header_only_csv_upload_is_400(upload):
    response = upload(b"name,age\n")
    assert response.status_code == 400


# Context: uploaded datasets support the full /datasets query surface.
def test_uploaded_dataset_supports_filters_and_sort(uploaded):
    body = b"name,age\nalice,30\nbob,41\ncarol,25\n"
    response = uploaded(body, query={"age__greater": "26", "_sort_desc": "age"})
    assert [row[0] for row in response.get_json()["rows"]] == ["bob", "alice"]


# Context: uploaded datasets export like converted ones.
def test_uploaded_dataset_is_exportable(upload, client):
    endpoint = upload(SIMPLE).get_json()["endpoint"]
    response = client.get(endpoint + "/export")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv"
    assert endpoint.rsplit("/", 1)[-1] + ".csv" in response.headers[
        "Content-Disposition"
    ]


# Phrase: "`POST /upload` accepts multipart form with field `file` or `attachment`."
# Context: when both are present the request is still a success.
def test_both_fields_present_succeeds(client):
    data = {
        "file": (io.BytesIO(SIMPLE), "a.csv"),
        "attachment": (io.BytesIO(b"x,y\n1,2\n"), "b.csv"),
    }
    response = client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert response.get_json()["endpoint"].startswith("/datasets/")
