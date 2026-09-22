"""Spec section: Export, Upload, and Multi-Format Support -> File Upload."""

import io

import pytest

CSV = "name,age\nada,36\ngrace,45\n"


# Phrase: "`POST /upload` accepts multipart form with field `file` or `attachment`."
@pytest.mark.parametrize("field", ["file", "attachment"])
def test_upload_accepts_either_field_name(upload, field):
    response = upload(CSV, field=field)

    assert response.status_code == 200


# Phrase: 'Success: {"ok": true, "endpoint": "/datasets/<id>"}'
def test_upload_success_envelope(upload):
    body = upload(CSV).get_json()

    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")
    assert body["endpoint"].removeprefix("/datasets/")


# Phrase: 'Success: {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: the endpoint handed back is immediately queryable.
def test_uploaded_dataset_is_queryable(client, upload):
    endpoint = upload(CSV).get_json()["endpoint"]

    dataset = client.get(endpoint)

    assert dataset.status_code == 200
    assert dataset.get_json()["columns"] == ["name", "age"]
    assert dataset.get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: 'Success: {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: an uploaded dataset supports the export route like any other.
def test_uploaded_dataset_exports(client, upload):
    endpoint = upload(CSV).get_json()["endpoint"]

    response = client.get(endpoint + "/export")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv"


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
def test_same_bytes_yield_the_same_id(upload):
    first = upload(CSV).get_json()["endpoint"]
    second = upload(CSV).get_json()["endpoint"]

    assert first == second


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: different bytes are a different dataset.
def test_different_bytes_yield_different_ids(upload):
    first = upload(CSV).get_json()["endpoint"]
    second = upload("city,pop\noslo,700000\n").get_json()["endpoint"]

    assert first != second


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: only the bytes decide the id -- not the filename or the field name
# (AMBIGUITIES T36).
def test_id_ignores_the_filename_and_the_field_name(upload):
    first = upload(CSV, field="file", filename="one.csv").get_json()["endpoint"]
    second = upload(CSV, field="attachment", filename="two.csv").get_json()["endpoint"]

    assert first == second


# Phrase: "Re-uploading the same file bytes yields the same dataset id."
# Context: the id survives a fresh application over a fresh store.
def test_id_is_stable_across_app_instances():
    from datagate_core.server import create_app

    endpoints = []
    for _ in range(2):
        client = create_app().test_client()
        response = client.post(
            "/upload",
            data={"file": (io.BytesIO(CSV.encode("utf-8")), "data.csv")},
            content_type="multipart/form-data",
        )
        endpoints.append(response.get_json()["endpoint"])

    assert endpoints[0] == endpoints[1]


# Phrase: "non-multipart request: `HTTP 415`"
def test_json_body_upload_is_415(client):
    response = client.post("/upload", json={"file": CSV})

    assert response.status_code == 415


# Phrase: "non-multipart request: `HTTP 415`"
# Context: a urlencoded form and a bare body are not multipart either.
@pytest.mark.parametrize(
    "kwargs",
    [
        {"data": {"file": CSV}},
        {"data": CSV, "content_type": "text/csv"},
        {"data": CSV.encode("utf-8"), "content_type": "application/octet-stream"},
    ],
)
def test_non_multipart_bodies_are_415(client, kwargs):
    assert client.post("/upload", **kwargs).status_code == 415


# Phrase: "non-multipart request: `HTTP 415`"
# Context: a request with no content type at all.
def test_upload_without_a_content_type_is_415(client):
    response = client.post("/upload", data=CSV.encode("utf-8"), content_type="")

    assert response.status_code == 415


# Phrase: "malformed multipart ... : `HTTP 400`"
# Context: the media type is multipart but no boundary is declared
# (AMBIGUITIES T38).
def test_multipart_without_a_boundary_is_400(client):
    response = client.post(
        "/upload", data=b"--x\r\nnot really multipart\r\n", content_type="multipart/form-data"
    )

    assert response.status_code == 400


# Phrase: "malformed multipart ... : `HTTP 400`"
# Context: a truncated body under a declared boundary.
def test_truncated_multipart_is_400(client):
    response = client.post(
        "/upload",
        data=b'--zz\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n',
        content_type="multipart/form-data; boundary=zz",
    )

    assert response.status_code == 400


# Phrase: "missing both `file` and `attachment`: `HTTP 400`"
def test_multipart_under_another_field_name_is_400(upload):
    response = upload(CSV, field="payload")

    assert response.status_code == 400


# Phrase: "missing both `file` and `attachment`: `HTTP 400`"
# Context: an empty multipart body carries neither field.
def test_multipart_with_no_parts_is_400(client):
    response = client.post("/upload", data={}, content_type="multipart/form-data")

    assert response.status_code == 400


# Phrase: "all errors use the standard JSON envelope"
@pytest.mark.parametrize(
    "call",
    [
        lambda client: client.post("/upload", json={"file": CSV}),
        lambda client: client.post("/upload", data={"other": "x"}, content_type="multipart/form-data"),
    ],
)
def test_upload_errors_use_the_envelope(client, call):
    body = call(client).get_json()

    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# Phrase: "`POST /upload` accepts multipart form with field `file` or `attachment`."
# Context: a body carrying both parts takes `file` (AMBIGUITIES T37).
def test_both_fields_present_prefers_file(client, upload):
    response = client.post(
        "/upload",
        data={
            "file": (io.BytesIO(CSV.encode("utf-8")), "one.csv"),
            "attachment": (io.BytesIO(b"city,pop\noslo,700000\n"), "two.csv"),
        },
        content_type="multipart/form-data",
    )

    assert response.get_json()["endpoint"] == upload(CSV).get_json()["endpoint"]


# Phrase: "The first sheet must be tabular (header + at least one data row) or `HTTP 400`."
# Context: the same tabular floor applies to uploaded CSV text.
def test_uploading_a_header_only_csv_is_400(upload):
    response = upload("name,age\n")

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
