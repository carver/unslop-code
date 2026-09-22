"""Spec section: Export, Upload, and Multi-Format Support -> File Upload."""
import json

from conftest import upload, upload_ok, xls_bytes, xlsx_bytes

TABLE = "name,age\nAda,36\nGrace,45\n"


# ---------------------------------------------------------------------------
# Phrase: "`POST /upload` accepts multipart form with field `file`"
# Context: the documented happy path.
# ---------------------------------------------------------------------------
def test_upload_accepts_the_file_field(gate):
    resp = upload(gate, TABLE, filename="people.csv", field="file")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# Phrase: "... with field `file` or `attachment`"
# Context: the alternative field name is equally acceptable.
# ---------------------------------------------------------------------------
def test_upload_accepts_the_attachment_field(gate):
    resp = upload(gate, TABLE, filename="people.csv", field="attachment")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_both_field_names_reach_the_same_dataset(gate):
    a = upload_ok(gate, TABLE, field="file")
    b = upload_ok(gate, TABLE, field="attachment")
    assert a == b


# ---------------------------------------------------------------------------
# Phrase: "Success: {\"ok\": true, \"endpoint\": \"/datasets/<id>\"}"
# Context: the exact success envelope of /upload.
# ---------------------------------------------------------------------------
def test_upload_success_envelope(gate):
    resp = upload(gate, TABLE)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")
    assert body["endpoint"].count("/") == 2
    assert body["endpoint"].rsplit("/", 1)[-1]


def test_uploaded_endpoint_is_queryable(gate):
    endpoint = upload_ok(gate, TABLE)
    payload = gate.get(endpoint).json()
    assert payload["ok"] is True
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["Ada", 36], ["Grace", 45]]


def test_uploaded_dataset_supports_the_query_controls(gate):
    endpoint = upload_ok(gate, TABLE)
    payload = gate.get(endpoint, params={"_sort_desc": "age", "_size": "1"}).json()
    assert payload["rows"] == [["Grace", 45]]
    assert payload["total"] == 2


def test_uploaded_dataset_is_exportable(gate):
    endpoint = upload_ok(gate, TABLE)
    resp = gate.get(endpoint + "/export")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].split(";")[0].strip() == "text/csv"
    assert "name" in resp.text and "Ada" in resp.text


# ---------------------------------------------------------------------------
# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: upload identity is a function of the payload bytes.
# ---------------------------------------------------------------------------
def test_reuploading_the_same_bytes_yields_the_same_id(gate):
    first = upload_ok(gate, TABLE)
    second = upload_ok(gate, TABLE)
    assert first == second


def test_same_bytes_under_a_different_filename_yield_the_same_id(gate):
    a = upload_ok(gate, TABLE, filename="one.csv")
    b = upload_ok(gate, TABLE, filename="two.csv")
    assert a == b


def test_different_bytes_yield_different_ids(gate):
    a = upload_ok(gate, TABLE)
    b = upload_ok(gate, TABLE + "Linus,28\n")
    assert a != b


def test_reupload_is_stable_for_spreadsheets(gate):
    data = xlsx_bytes([("S1", [["name", "age"], ["Ada", 36]])])
    assert upload_ok(gate, data, filename="a.xlsx") == upload_ok(
        gate, data, filename="a.xlsx"
    )


# ---------------------------------------------------------------------------
# Phrase: "... and `charset` query parameter"
# Context: /upload honours charset the way /convert does, for CSV payloads.
# ---------------------------------------------------------------------------
def test_upload_charset_decodes_the_payload(gate):
    data = "city\nZürich\n".encode("latin-1")
    endpoint = upload_ok(gate, data, filename="c.csv", charset="latin-1")
    assert gate.get(endpoint).json()["rows"] == [["Zürich"]]


def test_upload_charset_changes_the_decoded_text(gate):
    data = "city\nZürich\n".encode("utf-8")
    endpoint = upload_ok(gate, data, filename="c2.csv", charset="latin-1")
    assert gate.get(endpoint).json()["rows"] == [["ZÃ¼rich"]]


def test_upload_rejects_an_unsupported_charset_for_csv(gate):
    resp = upload(gate, TABLE, filename="c3.csv", charset="not-a-charset")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "non-multipart request: HTTP 415"
# Context: also "non-multipart upload: HTTP 415" under Error Handling.
# ---------------------------------------------------------------------------
def test_raw_csv_body_is_415(gate):
    resp = gate.request(
        "POST", "/upload", data=TABLE.encode(), headers={"Content-Type": "text/csv"}
    )
    assert resp.status_code == 415
    assert resp.json()["ok"] is False


def test_json_body_is_415(gate):
    resp = gate.request("POST", "/upload", json={"file": TABLE})
    assert resp.status_code == 415
    assert resp.json()["ok"] is False


def test_urlencoded_body_is_415(gate):
    resp = gate.request("POST", "/upload", data={"file": TABLE})
    assert resp.status_code == 415
    assert resp.json()["ok"] is False


def test_no_body_and_no_content_type_is_415(gate):
    resp = gate.request("POST", "/upload")
    assert resp.status_code == 415
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "malformed multipart ...: HTTP 400"
# Context: the content type claims multipart but the body cannot be parsed.
# ---------------------------------------------------------------------------
def test_malformed_multipart_body_is_400(gate):
    resp = gate.request(
        "POST",
        "/upload",
        data=b"this is not a multipart body at all",
        headers={"Content-Type": "multipart/form-data; boundary=abc123"},
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_multipart_without_a_boundary_is_400(gate):
    resp = gate.request(
        "POST",
        "/upload",
        data=b"----\r\nnonsense\r\n",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_truncated_multipart_is_400(gate):
    body = (
        b"--abc123\r\n"
        b'Content-Disposition: form-data; name="file"; filename="t.csv"\r\n'
        b"\r\nname,age\r\nAda,36\r\n"
    )  # no closing boundary
    resp = gate.request(
        "POST",
        "/upload",
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=abc123"},
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "... or missing both `file` and `attachment`: HTTP 400"
# Context: also "missing file field: HTTP 400" under Error Handling.
# ---------------------------------------------------------------------------
def test_multipart_with_a_wrongly_named_field_is_400(gate):
    resp = upload(gate, TABLE, field="payload")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_multipart_with_no_parts_at_all_is_400(gate):
    body = b"--abc123--\r\n"
    resp = gate.request(
        "POST",
        "/upload",
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=abc123"},
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_multipart_with_only_text_fields_is_400(gate):
    resp = gate.request(
        "POST", "/upload", files={"note": (None, "hello"), "other": (None, "x")}
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "all errors use the standard JSON envelope"
# Context: /upload failures, including the 415 path.
# ---------------------------------------------------------------------------
def test_upload_errors_use_the_standard_envelope(gate):
    for resp in (
        gate.request("POST", "/upload", json={}),
        upload(gate, TABLE, field="payload"),
        upload(gate, b"%PDF-1.4 not a table", filename="x.pdf"),
    ):
        assert resp.status_code in (400, 415)
        body = resp.json()
        assert body["ok"] is False
        assert isinstance(body["error"], str) and body["error"]
        assert set(body) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: "`POST /upload`" (the method is part of the contract)
# Context: other methods on the route are not uploads.
# ---------------------------------------------------------------------------
def test_get_on_upload_is_405(gate):
    resp = gate.get("/upload")
    assert resp.status_code == 405
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "The first sheet must be tabular (header + at least one data row)"
# Context: applied to an uploaded CSV with no data rows.
# ---------------------------------------------------------------------------
def test_upload_of_a_header_only_csv_is_400(gate):
    resp = upload(gate, "name,age\n", filename="hdr.csv")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_upload_of_an_empty_file_is_400(gate):
    resp = upload(gate, b"", filename="empty.csv")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False
