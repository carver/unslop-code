"""The storage directory: created on startup, and outliving the process."""

import io
from dataclasses import replace

import pytest

from gateway.app import create_app

TABLE = b"name,age\nada,36\n"


@pytest.fixture
def serve(settings):
    """Start a fresh service on a storage directory, as a restart would."""

    def start(directory=None):
        return create_app(
            settings if directory is None else replace(settings, storage_dir=directory)
        ).test_client()

    return start


def upload(client):
    return client.post(
        "/upload",
        data={"file": (io.BytesIO(TABLE), "data.csv")},
        content_type="multipart/form-data",
    )


def test_a_missing_storage_directory_is_created(serve, tmp_path):
    directory = tmp_path / "deep" / "storage"
    serve(directory)
    assert directory.is_dir()


def test_a_dataset_survives_a_restart(serve):
    endpoint = upload(serve()).get_json()["endpoint"]

    restarted = serve()
    assert restarted.get(endpoint).get_json()["rows"] == [["ada", 36]]


def test_a_restart_elsewhere_starts_empty(serve, tmp_path):
    endpoint = upload(serve()).get_json()["endpoint"]

    moved = serve(tmp_path / "other")
    assert moved.get(endpoint).status_code == 404
