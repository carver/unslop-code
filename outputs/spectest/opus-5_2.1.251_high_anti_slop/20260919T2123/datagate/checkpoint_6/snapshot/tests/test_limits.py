"""Tests for `MAX_SOURCE_SIZE` on both ingestion endpoints."""

import pytest

from helpers import convert, upload
from store import dataset_id_for

SOURCE = b"name,age\nAda,36\nGrace,45\n"
SIZE = len(SOURCE)


@pytest.fixture
def source(changing_source):
    return changing_source(SOURCE)


def test_a_source_at_the_limit_is_accepted(make_client, base_url, source):
    response = convert(make_client(max_source_size=SIZE), base_url, source)
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_a_source_above_the_limit_is_rejected(make_client, base_url, source):
    response = convert(make_client(max_source_size=SIZE - 1), base_url, source)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"]


def test_an_oversized_source_is_not_stored(make_client, base_url, source):
    client = make_client(max_source_size=SIZE - 1)
    convert(client, base_url, source)
    dataset_id = dataset_id_for(f"{base_url}/{source}".encode())
    assert client.get(f"/datasets/{dataset_id}").status_code == 404


def test_an_unset_limit_accepts_any_source(client, base_url, source):
    assert convert(client, base_url, source).status_code == 200


def test_an_upload_at_the_limit_is_accepted(make_client):
    assert upload(make_client(max_source_size=SIZE), SOURCE).status_code == 200


def test_an_upload_above_the_limit_is_rejected(make_client):
    response = upload(make_client(max_source_size=SIZE - 1), SOURCE)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
