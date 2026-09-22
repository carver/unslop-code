"""Tests for ingestion via POST /upload."""

import io

CSV = b"name,age\nada,36\nalan,41\n"


def test_upload_returns_dataset_endpoint(client, upload):
    response = upload(CSV)

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert client.get(response.json["endpoint"]).json["rows"] == [
        ["ada", 36],
        ["alan", 41],
    ]


def test_attachment_field_is_accepted(upload):
    response = upload(CSV, field="attachment")

    assert response.status_code == 200
    assert response.json["endpoint"].startswith("/datasets/")


def test_same_bytes_map_to_the_same_endpoint(upload):
    first = upload(CSV, name="one.csv")
    second = upload(CSV, name="two.csv")

    assert first.json["endpoint"] == second.json["endpoint"]


def test_different_bytes_map_to_different_endpoints(upload):
    first = upload(CSV)
    second = upload(b"name,age\nada,37\n")

    assert first.json["endpoint"] != second.json["endpoint"]


def test_non_multipart_upload_is_unsupported_media_type(client):
    response = client.post("/upload", json={"rows": []})

    assert response.status_code == 415
    assert response.json["ok"] is False
    assert isinstance(response.json["error"], str)


def test_upload_without_a_body_is_unsupported_media_type(client):
    response = client.post("/upload")

    assert response.status_code == 415


def test_missing_file_field_is_rejected(client):
    response = client.post(
        "/upload",
        data={"document": (io.BytesIO(CSV), "a.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json["ok"] is False


def test_malformed_multipart_body_is_rejected(client):
    response = client.post(
        "/upload",
        data=b"not really a multipart body",
        content_type="multipart/form-data; boundary=abc123",
    )

    assert response.status_code == 400
    assert response.json["ok"] is False


def test_non_tabular_upload_is_rejected(upload):
    response = upload(b"<html><body><p>hello</p></body></html>", name="page.html")

    assert response.status_code == 400


def test_upload_honours_a_declared_charset(client):
    payload = "name;city\nada;münchen\n".encode("latin-1")

    response = client.post(
        "/upload",
        data={"file": (io.BytesIO(payload), "latin.csv")},
        content_type="multipart/form-data",
        query_string={"charset": "latin-1"},
    )

    assert client.get(response.json["endpoint"]).json["rows"] == [["ada", "münchen"]]


def test_uploads_carry_cors_headers(upload):
    assert upload(CSV).headers["Access-Control-Allow-Origin"] == "*"
