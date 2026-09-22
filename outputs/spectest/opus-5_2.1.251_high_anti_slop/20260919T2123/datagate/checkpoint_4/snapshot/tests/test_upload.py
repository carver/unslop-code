"""Tests for the multipart upload endpoint."""

import io

import pytest

from conftest import FIXTURES


def upload(client, fixture, field="file"):
    data = {field: (io.BytesIO(FIXTURES[fixture]), fixture)}
    return client.post("/upload", data=data)


def test_upload_returns_a_dataset_endpoint(client):
    payload = upload(client, "staff.csv").get_json()
    assert payload["ok"] is True
    assert payload["endpoint"].startswith("/datasets/")


def test_uploaded_dataset_is_served_like_a_converted_one(client):
    endpoint = upload(client, "basic.csv").get_json()["endpoint"]
    payload = client.get(endpoint).get_json()
    assert payload["columns"] == ["name", "age", "score", "start"]
    assert payload["rows"][0] == ["Ada", 36, 9.5, "08:30"]


def test_the_same_bytes_map_to_the_same_endpoint(client):
    first = upload(client, "staff.csv").get_json()["endpoint"]
    second = upload(client, "staff.csv", field="attachment").get_json()["endpoint"]
    assert first == second


def test_different_bytes_map_to_different_endpoints(client):
    first = upload(client, "staff.csv").get_json()["endpoint"]
    second = upload(client, "basic.csv").get_json()["endpoint"]
    assert first != second


@pytest.mark.parametrize("field", ["file", "attachment"])
@pytest.mark.parametrize("fixture", ["staff.csv", "staff.xls", "staff.xlsx"])
def test_upload_accepts_both_fields_and_every_format(client, fixture, field):
    endpoint = upload(client, fixture, field=field).get_json()["endpoint"]
    payload = client.get(endpoint).get_json()
    assert payload["columns"] == ["name", "role", "age", "rating"]
    assert payload["total"] == 4


def test_a_non_multipart_upload_is_unsupported_media(client):
    response = client.post("/upload", data=FIXTURES["staff.csv"], content_type="text/csv")
    assert response.status_code == 415
    assert response.get_json()["ok"] is False


def test_an_upload_without_a_file_field_is_rejected(client):
    response = upload(client, "staff.csv", field="document")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_a_multipart_form_without_any_file_is_rejected(client):
    response = client.post(
        "/upload", data={"comment": "no file here"}, content_type="multipart/form-data"
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_a_malformed_multipart_body_is_rejected(client):
    response = client.post(
        "/upload",
        data=b"--boundary\r\nnot a part at all\r\n",
        content_type="multipart/form-data; boundary=boundary",
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize("fixture", ["page.html", "header_only.csv", "archive.xlsx"])
def test_an_unreadable_upload_is_rejected(client, fixture):
    response = upload(client, fixture)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_uploading_by_the_wrong_method_is_a_json_405(client):
    response = client.get("/upload")
    assert response.status_code == 405
    assert response.get_json()["ok"] is False
