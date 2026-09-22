"""Ingestion behaviour of ``POST /upload``."""

import io

import pytest

SIMPLE = b"name,age\nada,36\n"


def test_returns_dataset_endpoint(upload):
    body = upload(SIMPLE).get_json()
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")


def test_uploaded_rows_are_served(client, upload):
    endpoint = upload(SIMPLE).get_json()["endpoint"]
    body = client.get(endpoint).get_json()
    assert body["columns"] == ["name", "age"]
    assert body["rows"] == [["ada", 36]]


def test_same_bytes_map_to_the_same_endpoint(upload):
    first = upload(SIMPLE).get_json()["endpoint"]
    assert upload(SIMPLE, name="renamed.csv").get_json()["endpoint"] == first


def test_different_bytes_map_to_a_different_endpoint(upload):
    first = upload(SIMPLE).get_json()["endpoint"]
    assert upload(b"name,age\nlin,7\n").get_json()["endpoint"] != first


def test_attachment_field_is_accepted(upload):
    assert upload(SIMPLE, field="attachment").get_json()["ok"] is True


def test_non_multipart_request_is_unsupported(client):
    response = client.post("/upload", data=SIMPLE, content_type="text/csv")
    assert response.status_code == 415
    assert response.get_json()["ok"] is False


def test_request_without_a_body_is_unsupported(client):
    assert client.post("/upload").status_code == 415


def test_malformed_multipart_is_rejected(client):
    response = client.post(
        "/upload",
        data=b"--edge\r\nnot a part at all",
        content_type="multipart/form-data; boundary=edge",
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_missing_file_field_is_rejected(client):
    response = client.post(
        "/upload",
        data={"payload": (io.BytesIO(SIMPLE), "data.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_declared_charset_decodes_the_upload(client, upload):
    endpoint = upload("city\nMünchen\n".encode("cp1252"), charset="cp1252")
    body = client.get(endpoint.get_json()["endpoint"]).get_json()
    assert body["rows"] == [["München"]]


@pytest.mark.parametrize("payload", [b"name,age\n", b"<html><body>hi</body></html>"])
def test_non_tabular_upload_is_rejected(upload, payload):
    assert upload(payload).status_code == 400


def test_unknown_charset_is_rejected(upload):
    assert upload(SIMPLE, charset="klingon-8").status_code == 400
