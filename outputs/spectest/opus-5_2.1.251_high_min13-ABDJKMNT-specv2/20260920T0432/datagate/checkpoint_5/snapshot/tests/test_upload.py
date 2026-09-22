"""File upload: POST /upload."""

import io
import re

CSV = "name,age\nada,36\ngrace,45\n"


# Spec: "Success: {"ok": true, "endpoint": "/datasets/<id>"}"
# Context: a multipart POST carrying the file in the `file` field.
def test_upload_success_payload_shape(upload):
    response = upload(CSV)
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert re.fullmatch(r"/datasets/[A-Za-z0-9_.-]+", body["endpoint"])
    assert set(body) == {"ok", "endpoint"}


# Spec: "`POST /upload` accepts multipart form with field `file` or `attachment`"
# Context: either field name is accepted and ingests the same table.
def test_both_field_names_are_accepted(uploaded):
    for field in ("file", "attachment"):
        payload = uploaded(CSV, field=field)
        assert payload["columns"] == ["name", "age"], field
        assert payload["rows"] == [["ada", 36], ["grace", 45]], field


# Spec: "Success: {"ok": true, "endpoint": "/datasets/<id>"}"
# Context: the endpoint handed back serves the uploaded table.
def test_uploaded_dataset_is_readable(client, upload):
    endpoint = upload(CSV).get_json()["endpoint"]
    payload = client.get(endpoint).get_json()
    assert payload["ok"] is True
    assert payload["rows"] == [["ada", 36], ["grace", 45]]


# Spec: "Re-uploading the same file bytes yields the same dataset id."
# Context: repeated uploads of identical bytes, under different filenames and
# form fields (AMBIGUITIES T28).
def test_same_bytes_yield_the_same_id(upload):
    first = upload(CSV).get_json()["endpoint"]
    again = upload(CSV, field="attachment", filename="other.csv").get_json()["endpoint"]
    assert first == again


# Spec: "Re-uploading the same file bytes yields the same dataset id."
# Context: different bytes are a different dataset.
def test_different_bytes_yield_a_different_id(upload):
    first = upload(CSV).get_json()["endpoint"]
    other = upload("name,age\nalan,41\n").get_json()["endpoint"]
    assert first != other


# Spec: "non-multipart request: `HTTP 415`"
# Context: a body posted under any other content type (AMBIGUITIES T31).
def test_non_multipart_is_415(client):
    for content_type in ("text/csv", "application/json", "application/x-www-form-urlencoded"):
        response = client.post("/upload", data=CSV, content_type=content_type)
        assert response.status_code == 415, content_type
        assert response.get_json()["ok"] is False


# Spec: "non-multipart request: `HTTP 415`"
# Context: a POST that declares no content type at all.
def test_upload_without_content_type_is_415(client):
    response = client.post("/upload", data=CSV, content_type=None)
    assert response.status_code == 415


# Spec: "malformed multipart ...: `HTTP 400`"
# Context: the content type claims multipart but the body is not one.
def test_malformed_multipart_is_400(client):
    response = client.post(
        "/upload", data=b"not a multipart body", content_type="multipart/form-data; boundary=zz"
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "malformed multipart ...: `HTTP 400`"
# Context: multipart without a boundary parameter cannot be parsed.
def test_multipart_without_boundary_is_400(client):
    response = client.post("/upload", data=b"whatever", content_type="multipart/form-data")
    assert response.status_code == 400


# Spec: "missing both `file` and `attachment`: `HTTP 400`" / "missing file
# field: `HTTP 400`"
# Context: a well-formed multipart body carrying some other field.
def test_missing_file_field_is_400(client):
    response = client.post(
        "/upload",
        data={"payload": (io.BytesIO(CSV.encode()), "table.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "missing both `file` and `attachment`: `HTTP 400`"
# Context: a multipart body with no parts at all.
def test_empty_multipart_is_400(client):
    response = client.post("/upload", data={}, content_type="multipart/form-data")
    assert response.status_code == 400


# Spec: "`POST /upload` accepts ... `charset` query parameter."
# Context: the named charset decodes the uploaded CSV bytes.
def test_charset_decodes_uploaded_bytes(uploaded):
    payload = uploaded("name,town\ncafé,östersund\n".encode("cp1252"), params={"charset": "cp1252"})
    assert payload["rows"] == [["café", "östersund"]]


# Spec: "`charset` applies and validates only for text CSV sources."
# Context: an unusable charset on a CSV upload is a 400.
def test_bad_charset_on_csv_upload_is_400(upload):
    response = upload("name,town\ncafé,lund\n".encode("utf-8"), params={"charset": "nonsense-codec"})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "all errors use the standard JSON envelope"
# Context: every upload failure answers with the envelope and JSON content type.
def test_upload_errors_use_the_envelope(client, upload):
    responses = [
        client.post("/upload", data=CSV, content_type="text/csv"),
        client.post("/upload", data={}, content_type="multipart/form-data"),
        upload("not a table at all"),
    ]
    for response in responses:
        assert response.mimetype == "application/json"
        body = response.get_json()
        assert body["ok"] is False
        assert set(body) == {"ok", "error"}


# Spec: "`POST /upload`"
# Context: the route exists only for POST, and answers other methods in JSON.
def test_upload_rejects_other_methods(client):
    response = client.get("/upload")
    assert response.status_code == 405
    assert response.get_json()["ok"] is False


# Spec: "Include CORS headers for browser access." (carried forward)
# Context: uploads are made from browsers too, so the route is cross-origin.
def test_upload_carries_cors_headers(upload):
    assert upload(CSV).headers["Access-Control-Allow-Origin"] == "*"
