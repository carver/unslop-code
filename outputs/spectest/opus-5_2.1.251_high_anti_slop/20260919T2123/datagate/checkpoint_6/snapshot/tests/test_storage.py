"""Tests for `STORAGE_DIR`: where datasets are kept and that they outlive the process."""

from app import create_app
from config import Settings
from conftest import FIXTURES
from helpers import upload


def restart(storage_dir):
    """A fresh application, and so a fresh dataset store, over the same storage directory."""
    return create_app(Settings(storage_dir=storage_dir)).test_client()


def test_a_missing_storage_directory_is_created(tmp_path):
    storage_dir = tmp_path / "missing" / "datasets"
    create_app(Settings(storage_dir=storage_dir))
    assert storage_dir.is_dir()


def test_an_uploaded_dataset_survives_a_restart(tmp_path):
    endpoint = upload(restart(tmp_path), FIXTURES["staff.csv"]).get_json()["endpoint"]

    payload = restart(tmp_path).get(endpoint).get_json()
    assert payload["columns"] == ["name", "role", "age", "rating"]
    assert payload["rows"][0] == ["Ada", "engineer", 36, 9.5]


def test_a_converted_dataset_survives_a_restart(tmp_path, base_url, changing_source):
    fixture = changing_source(b"city,population\nOslo,709000\n")
    client = restart(tmp_path)
    endpoint = client.get(
        "/convert", query_string={"source": f"{base_url}/{fixture}"}
    ).get_json()["endpoint"]

    assert restart(tmp_path).get(endpoint).get_json()["rows"] == [["Oslo", 709000]]


def test_a_dataset_is_not_shared_by_another_storage_directory(tmp_path):
    endpoint = upload(restart(tmp_path / "one"), FIXTURES["staff.csv"]).get_json()["endpoint"]
    assert restart(tmp_path / "two").get(endpoint).status_code == 404


def test_a_restart_still_answers_a_repeat_conversion_from_the_store(
    tmp_path, base_url, changing_source
):
    fixture = changing_source(b"name,age\nAda,36\n")
    source = {"source": f"{base_url}/{fixture}"}
    endpoint = restart(tmp_path).get("/convert", query_string=source).get_json()["endpoint"]

    changing_source(b"city,population\nOslo,709000\n")
    client = restart(tmp_path)
    assert client.get("/convert", query_string=source).get_json()["endpoint"] == endpoint
    assert client.get(endpoint).get_json()["columns"] == ["name", "age"]
