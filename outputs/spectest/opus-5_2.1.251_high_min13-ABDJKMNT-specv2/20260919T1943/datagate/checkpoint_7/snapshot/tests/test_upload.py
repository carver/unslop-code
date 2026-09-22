"""Spec section: Export, Upload, and Multi-Format Support -- File Upload."""

import io

from conftest import SIMPLE_CSV, xlsx_bytes

CSV_BYTES = SIMPLE_CSV.encode("utf-8")


# Phrase: "`POST /upload` accepts multipart form with field `file`"
def test_upload_accepts_a_file_field(upload):
    response = upload(CSV_BYTES)

    assert response.status_code == 200
    assert response.get_json()["endpoint"].startswith("/datasets/")


# Phrase: "`POST /upload` accepts multipart form with field ... `attachment`"
def test_upload_accepts_an_attachment_field(upload):
    response = upload(CSV_BYTES, field="attachment")

    assert response.status_code == 200


# Phrase: "Success: `{"ok": true, "endpoint": "/datasets/<id>"}`"
def test_upload_success_envelope(upload):
    body = upload(CSV_BYTES).get_json()

    assert body["ok"] is True
    assert set(body) == {"ok", "endpoint"}


# Phrase: "Success: `{"ok": true, "endpoint": "/datasets/<id>"}`" (context: the endpoint serves the table)
def test_uploaded_endpoint_serves_the_table(uploaded):
    body = uploaded(CSV_BYTES)

    assert body["columns"] == ["name", "age"]
    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
def test_same_bytes_yield_the_same_id(upload):
    first = upload(CSV_BYTES).get_json()["endpoint"]
    second = upload(CSV_BYTES).get_json()["endpoint"]

    assert first == second


# Phrase: "Re-uploading the same file bytes yields the same dataset id." (context: different bytes differ)
def test_different_bytes_yield_a_different_id(upload):
    first = upload(CSV_BYTES).get_json()["endpoint"]
    second = upload(b"name,age\nada,37\n").get_json()["endpoint"]

    assert first != second


# Phrase: "Re-uploading the same file bytes yields the same dataset id." (context: filename is irrelevant, T38)
def test_the_filename_does_not_change_the_id(upload):
    first = upload(CSV_BYTES, filename="a.csv").get_json()["endpoint"]
    second = upload(CSV_BYTES, filename="renamed.csv").get_json()["endpoint"]

    assert first == second


# Phrase: "Re-uploading the same file bytes yields the same dataset id." (context: the field used is irrelevant)
def test_the_form_field_does_not_change_the_id(upload):
    first = upload(CSV_BYTES, field="file").get_json()["endpoint"]
    second = upload(CSV_BYTES, field="attachment").get_json()["endpoint"]

    assert first == second


# Phrase: "`POST /upload` accepts multipart form with field `file` or `attachment`" (context: both given, T39)
def test_file_wins_over_attachment(client):
    response = client.post(
        "/upload",
        data={
            "file": (io.BytesIO(b"who\nada\n"), "f.csv"),
            "attachment": (io.BytesIO(b"other\ngrace\n"), "a.csv"),
        },
        content_type="multipart/form-data",
    )
    endpoint = response.get_json()["endpoint"]

    assert client.get(endpoint).get_json()["columns"] == ["who"]


# Phrase: "non-multipart request: `HTTP 415`"
def test_json_body_is_415(client):
    response = client.post("/upload", json={"file": "name,age\nada,36\n"})

    assert response.status_code == 415


# Phrase: "non-multipart request: `HTTP 415`" (context: raw CSV body)
def test_raw_csv_body_is_415(client):
    response = client.post("/upload", data=CSV_BYTES, content_type="text/csv")

    assert response.status_code == 415


# Phrase: "non-multipart request: `HTTP 415`" (context: no content type at all)
def test_typeless_body_is_415(client):
    response = client.post("/upload", data=CSV_BYTES)

    assert response.status_code == 415


# Phrase: "malformed multipart ... `HTTP 400`"
def test_malformed_multipart_is_400(client):
    response = client.post("/upload", data=b"not a multipart body", content_type="multipart/form-data; boundary=zz")

    assert response.status_code == 400


# Phrase: "malformed multipart ... `HTTP 400`" (context: no boundary parameter, T48)
def test_multipart_without_a_boundary_is_400(client):
    response = client.post("/upload", data=b"junk", content_type="multipart/form-data")

    assert response.status_code == 400


# Phrase: "malformed multipart ... `HTTP 400`" (context: truncated body)
def test_truncated_multipart_is_400(client):
    body = b'--zz\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\nname,age\r\nada,36'

    response = client.post("/upload", data=body, content_type="multipart/form-data; boundary=zz")

    assert response.status_code == 400


# Phrase: "missing both `file` and `attachment`: `HTTP 400`"
def test_a_differently_named_field_is_400(upload):
    response = upload(CSV_BYTES, field="payload")

    assert response.status_code == 400


# Phrase: "missing file field: `HTTP 400`" (context: an empty multipart form)
def test_an_empty_multipart_form_is_400(client):
    response = client.post("/upload", data={}, content_type="multipart/form-data")

    assert response.status_code == 400


# Phrase: "missing file field: `HTTP 400`" (context: a text field named `file`, T40)
def test_a_text_field_named_file_is_400(client):
    response = client.post("/upload", data={"file": SIMPLE_CSV}, content_type="multipart/form-data")

    assert response.status_code == 400


# Phrase: "all errors use the standard JSON envelope" (context: upload failures)
def test_upload_errors_use_the_envelope(client, upload):
    for response in (client.post("/upload", json={}), upload(CSV_BYTES, field="payload")):
        body = response.get_json()
        assert body["ok"] is False
        assert isinstance(body["error"], str)


# Phrase: "`POST /upload` accepts ... `charset` query parameter"
def test_charset_decodes_the_uploaded_bytes(uploaded):
    body = uploaded("name\nlanglé\n".encode("latin-1"), query={"charset": "latin-1"})

    assert body["rows"] == [["langlé"]]


# Phrase: "`POST /upload` accepts ... `charset` query parameter" (context: unusable charset)
def test_an_unknown_charset_on_a_csv_upload_is_400(upload):
    response = upload(CSV_BYTES, query={"charset": "not-an-encoding"})

    assert response.status_code == 400


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
def test_a_header_only_upload_is_400(upload):
    response = upload(b"name,age\n")

    assert response.status_code == 400


# Phrase: "`POST /upload` accepts multipart form" (context: uploads feed the same query pipeline)
def test_uploaded_datasets_support_controls_and_filters(uploaded):
    body = uploaded(CSV_BYTES, dataset_query="?age__greater=40&_shape=objects")

    assert body["rows"] == [{"rowid": 3, "name": "grace", "age": 45}]
    assert body["total"] == 1


# Phrase: "`POST /upload` accepts multipart form" (context: uploads are exportable)
def test_uploaded_datasets_are_exportable(client, upload):
    endpoint = upload(xlsx_bytes({"s": [["a", "b"], [1, 2]]}), filename="s.xlsx").get_json()["endpoint"]

    response = client.get(endpoint + "/export")

    assert response.get_data(as_text=True).splitlines() == ["a,b", "1,2"]
