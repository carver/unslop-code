"""Spec section: Export, Upload, and Multi-Format Support - File Upload."""

import io

from tests.conftest import SIMPLE_CSV, TEAMS_SHEET, xlsx_bytes


# Phrase: "`POST /upload` accepts multipart form with field `file`"
def test_upload_accepts_the_file_field(upload):
    response = upload(SIMPLE_CSV, field="file")
    assert response.status_code == 200


# Phrase: "`POST /upload` accepts multipart form with field ... `attachment`"
def test_upload_accepts_the_attachment_field(upload):
    response = upload(SIMPLE_CSV, field="attachment")
    assert response.status_code == 200


# Phrase: 'Success: {"ok": true, "endpoint": "/datasets/<id>"}'
def test_upload_success_envelope(upload):
    payload = upload(SIMPLE_CSV).get_json()
    assert payload["ok"] is True
    assert payload["endpoint"].startswith("/datasets/")
    assert payload["endpoint"].removeprefix("/datasets/") != ""


# Phrase: '"endpoint": "/datasets/<id>"' - the endpoint serves the uploaded table.
def test_uploaded_endpoint_serves_the_file(uploaded):
    payload = uploaded(SIMPLE_CSV)().get_json()
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
def test_same_bytes_yield_the_same_dataset_id(upload):
    first = upload(SIMPLE_CSV).get_json()["endpoint"]
    second = upload(SIMPLE_CSV).get_json()["endpoint"]
    assert first == second


# Phrase: "the same file bytes" - the file name is not part of the identity (T34).
def test_dataset_id_ignores_the_uploaded_file_name(upload):
    first = upload(SIMPLE_CSV, filename="one.csv").get_json()["endpoint"]
    second = upload(SIMPLE_CSV, filename="two.csv", field="attachment").get_json()["endpoint"]
    assert first == second


# Phrase: "Re-uploading the same file bytes yields the same dataset id." - and
# different bytes do not.
def test_different_bytes_yield_different_dataset_ids(upload):
    first = upload(SIMPLE_CSV).get_json()["endpoint"]
    second = upload("name,age\nada,36\ngrace,46\n").get_json()["endpoint"]
    assert first != second


# Phrase: "non-multipart request: `HTTP 415`"
def test_non_multipart_upload_is_415(client):
    for data, content_type in [
        (b'{"file": "a,b"}', "application/json"),
        (b"name,age\nada,36\n", "text/csv"),
        (b"file=a", "application/x-www-form-urlencoded"),
    ]:
        response = client.post("/upload", data=data, content_type=content_type)
        assert response.status_code == 415, content_type
        assert response.get_json()["ok"] is False, content_type


# Phrase: "non-multipart request: `HTTP 415`" - no content type at all.
def test_upload_without_content_type_is_415(client):
    assert client.post("/upload").status_code == 415


# Phrase: "missing both `file` and `attachment`: `HTTP 400`"
def test_upload_with_another_field_name_is_400(client):
    response = client.post(
        "/upload",
        data={"payload": (io.BytesIO(SIMPLE_CSV.encode()), "data.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "missing both `file` and `attachment`: `HTTP 400`" - no parts at all.
def test_upload_with_no_parts_is_400(client):
    response = client.post("/upload", data={}, content_type="multipart/form-data")
    assert response.status_code == 400


# Phrase: "malformed multipart ... `HTTP 400`"
def test_malformed_multipart_is_400(client):
    response = client.post(
        "/upload",
        data=b"--frontier\r\nnot a part header at all\r\n",
        content_type="multipart/form-data; boundary=frontier",
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "malformed multipart ... `HTTP 400`" - no boundary to parse with (T47).
def test_multipart_without_boundary_is_400(client):
    response = client.post(
        "/upload", data=b"whatever", content_type="multipart/form-data"
    )
    assert response.status_code == 400


# Phrase: "`/convert` and `/upload` accept CSV, `.xls`, and `.xlsx`." - via upload.
def test_upload_accepts_a_workbook(uploaded):
    payload = uploaded(xlsx_bytes(TEAMS_SHEET), filename="teams.xlsx")().get_json()
    assert payload["columns"] == ["name", "team", "age"]
    assert payload["rows"][0] == ["ada", "blue", 36]


# Phrase: "The first sheet must be tabular (header + at least one data row) or
# `HTTP 400`." - via upload.
def test_upload_of_a_non_tabular_file_is_400(upload):
    response = upload("name,age\n")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Unrecognized format: `HTTP 400`." - via upload.
def test_upload_of_an_unrecognized_format_is_400(upload):
    response = upload(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 32, filename="x.png")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "all errors use the standard JSON envelope"
def test_upload_errors_use_the_json_envelope(client, upload):
    for response in [
        client.post("/upload", data=b"x", content_type="text/plain"),
        client.post("/upload", data={}, content_type="multipart/form-data"),
        upload("not a table at all"),
    ]:
        assert response.get_json()["ok"] is False
        assert isinstance(response.get_json()["error"], str)
