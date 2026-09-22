"""Spec section: File Upload - `POST /upload`."""
import io

import pytest

CSV = b"name,qty\nwidget,3\ngadget,10\n"


# Phrase: "`POST /upload` accepts multipart form with field `file`"
# Context: the happy path with the primary field name.
def test_upload_file_field(upload):
    status, payload = upload(body=CSV, field="file")
    assert status == 200, payload


# Phrase: "accepts multipart form with field ... `attachment`"
# Context: the alternate field name is equally accepted.
def test_upload_attachment_field(upload):
    status, payload = upload(body=CSV, field="attachment")
    assert status == 200, payload


# Phrase: 'Success: {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: exact success envelope for /upload.
def test_upload_success_envelope(upload):
    status, payload = upload(body=CSV)
    assert status == 200
    assert payload["ok"] is True
    assert payload["endpoint"].startswith("/datasets/")
    assert len(payload["endpoint"][len("/datasets/"):]) > 0


# Phrase: '"endpoint": "/datasets/<id>"'
# Context: the returned endpoint serves the uploaded table.
def test_uploaded_endpoint_is_queryable(client, upload):
    _, payload = upload(body=CSV)
    resp = client.get(payload["endpoint"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["columns"] == ["name", "qty"]
    assert body["rows"] == [["widget", 3], ["gadget", 10]]


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: two identical uploads land on one dataset.
def test_same_bytes_same_id(upload):
    _, first = upload(body=CSV)
    _, second = upload(body=CSV)
    assert first["endpoint"] == second["endpoint"]


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: different bytes must not collide.
def test_different_bytes_different_id(upload):
    _, first = upload(body=CSV)
    _, second = upload(body=b"name,qty\nwidget,4\n")
    assert first["endpoint"] != second["endpoint"]


# Phrase: "the same file bytes" (see AMBIGUITIES T43)
# Context: identity is the bytes, not the filename or the field used.
def test_id_ignores_filename_and_field(upload):
    _, a = upload(body=CSV, field="file", filename="one.csv")
    _, b = upload(body=CSV, field="attachment", filename="other-name.csv")
    assert a["endpoint"] == b["endpoint"]


# Phrase: "`POST /upload` accepts multipart form ... and `charset` query parameter."
# Context: the charset decodes the uploaded CSV bytes.
def test_upload_charset_is_used(client, upload):
    body = "name,note\nwidget,café\n".encode("cp1252")
    status, payload = upload(body=body, charset="cp1252")
    assert status == 200, payload
    rows = client.get(payload["endpoint"]).get_json()["rows"]
    assert rows == [["widget", "café"]]


# Phrase: "`charset` query parameter" + "charset applies and validates ... for text CSV"
# Context: an unknown codec name on a CSV upload is a 400.
@pytest.mark.parametrize("bad", ["klingon", "utf-99"])
def test_upload_bad_charset_is_400(upload, bad):
    status, payload = upload(body=CSV, charset=bad)
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "`charset` query parameter"
# Context: omitting charset falls back to detection, as on /convert.
def test_upload_without_charset_detects(client, upload):
    status, payload = upload(body="a,b\nnaïve,2\n".encode("utf-8"))
    assert status == 200
    assert client.get(payload["endpoint"]).get_json()["rows"] == [["naïve", 2]]


# Phrase: "non-multipart request: `HTTP 415`"
# Context: a JSON body is not a multipart form.
def test_non_multipart_json_is_415(client):
    resp = client.post("/upload", data=b'{"a": 1}', content_type="application/json")
    assert resp.status_code == 415
    assert resp.get_json()["ok"] is False


# Phrase: "non-multipart request: `HTTP 415`"
# Context: a raw CSV body posted directly is still not multipart.
def test_non_multipart_raw_csv_is_415(client):
    resp = client.post("/upload", data=CSV, content_type="text/csv")
    assert resp.status_code == 415


# Phrase: "non-multipart request: `HTTP 415`"
# Context: urlencoded forms are forms, but not multipart forms.
def test_urlencoded_form_is_415(client):
    resp = client.post(
        "/upload", data={"file": "a,b\n1,2\n"},
        content_type="application/x-www-form-urlencoded",
    )
    assert resp.status_code == 415


# Phrase: "non-multipart request: `HTTP 415`"
# Context: no Content-Type at all is not a multipart request.
def test_missing_content_type_is_415(client):
    resp = client.post("/upload", data=CSV, content_type=None)
    assert resp.status_code == 415


# Phrase: "missing both `file` and `attachment`: `HTTP 400`"
# Context: a well-formed multipart body carrying some other field name.
def test_wrong_field_name_is_400(upload):
    status, payload = upload(body=CSV, field="document")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "missing file field: `HTTP 400`"
# Context: a multipart body with no file parts at all.
def test_no_parts_is_400(client):
    resp = client.post("/upload", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# Phrase: "malformed multipart ...: `HTTP 400`"
# Context: the declared boundary does not match the body.
def test_malformed_multipart_is_400(client):
    resp = client.post(
        "/upload", data=b"--nope\r\nnot really a part\r\n",
        content_type="multipart/form-data; boundary=zzz",
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# Phrase: "malformed multipart ...: `HTTP 400`"
# Context: multipart with no boundary parameter cannot be parsed.
def test_multipart_without_boundary_is_400(client):
    resp = client.post(
        "/upload", data=CSV, content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# Phrase: "field `file` or `attachment`" (see AMBIGUITIES T44)
# Context: when both are present the request is still accepted.
def test_both_fields_present_is_accepted(client, upload):
    status, payload = upload(
        body=CSV, field="file",
        extra={"attachment": (io.BytesIO(b"x,y\n1,2\n"), "other.csv")},
    )
    assert status == 200, payload
    columns = client.get(payload["endpoint"]).get_json()["columns"]
    assert columns == ["name", "qty"]


# Phrase: "all errors use the standard JSON envelope"
# Context: upload errors carry ok/error keys like every other endpoint.
@pytest.mark.parametrize("kwargs,expected", [
    ({"field": "document"}, 400),
    ({"field": None}, 400),
])
def test_upload_error_envelope(upload, kwargs, expected):
    status, payload = upload(body=CSV, **kwargs)
    assert status == expected
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# Phrase: "The first sheet must be tabular (header + at least one data row)"
# Context: a header-only CSV upload has no data rows.
def test_upload_header_only_is_400(upload):
    status, payload = upload(body=b"name,qty\n")
    assert status == 400, payload
    assert payload["ok"] is False


# Phrase: "Unrecognized format: `HTTP 400`."
# Context: an empty upload is not a recognisable table.
def test_upload_empty_file_is_400(upload):
    status, payload = upload(body=b"")
    assert status == 400, payload


# Phrase: "`POST /upload`"
# Context: the endpoint is POST-only.
def test_upload_get_is_405(client):
    resp = client.get("/upload")
    assert resp.status_code == 405
    assert resp.get_json()["ok"] is False


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: the uploaded dataset also exports, like any other dataset.
def test_uploaded_dataset_exports(client, upload):
    _, payload = upload(body=CSV)
    resp = client.get(payload["endpoint"] + "/export")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True).splitlines()[0].strip() == "name,qty"
