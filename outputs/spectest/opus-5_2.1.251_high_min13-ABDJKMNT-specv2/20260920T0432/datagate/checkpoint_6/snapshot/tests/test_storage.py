"""`STORAGE_DIR`: creating the directory and surviving a restart."""

import io
import json

import pytest

from gateway.config import ConfigError, load_settings

BODY = "name,age\nada,36\n"
ROWS = [["ada", 36]]


def convert(client, origin, path):
    source = origin.serve(path, BODY)
    return client.get("/convert", query_string={"source": source})


def upload(client, body=BODY):
    return client.post(
        "/upload",
        data={"file": (io.BytesIO(body.encode()), "table.csv")},
        content_type="multipart/form-data",
    )


# Spec: "Create `STORAGE_DIR` if missing."
# Context: a configured directory that does not exist yet, nested under a parent
# that does not either.
def test_a_missing_storage_dir_is_created(configured_client, tmp_path):
    directory = tmp_path / "parent" / "datasets"
    configured_client(STORAGE_DIR=str(directory))
    assert directory.is_dir()


# Spec: "Create `STORAGE_DIR` if missing."
# Context: a directory that already holds datasets is reused, not replaced.
def test_an_existing_storage_dir_is_kept(configured_client, tmp_path, origin):
    storage = tmp_path / "kept"
    storage.mkdir()
    client = configured_client(STORAGE_DIR=str(storage))
    convert(client, origin, "/storage-kept.csv")
    configured_client(STORAGE_DIR=str(storage))
    assert any(storage.iterdir())


# Spec: "Persisted datasets must survive restart when the same directory is
# reused."
# Context: a dataset converted by one process, read back by the next one.
def test_a_converted_dataset_survives_a_restart(configured_client, tmp_path, origin):
    storage = str(tmp_path / "shared")
    first = configured_client(STORAGE_DIR=storage)
    endpoint = convert(first, origin, "/storage-restart.csv").get_json()["endpoint"]
    restarted = configured_client(STORAGE_DIR=storage)
    assert restarted.get(endpoint).get_json()["rows"] == ROWS


# Spec: "Persisted datasets must survive restart"
# Context: an uploaded dataset has no source to re-fetch, so it must be stored
# too (T67).
def test_an_uploaded_dataset_survives_a_restart(configured_client, tmp_path):
    storage = str(tmp_path / "shared")
    endpoint = upload(configured_client(STORAGE_DIR=storage)).get_json()["endpoint"]
    restarted = configured_client(STORAGE_DIR=storage)
    assert restarted.get(endpoint).get_json()["rows"] == ROWS


# Spec: "Persisted datasets must survive restart when the same directory is
# reused."
# Context: caching off governs re-downloading, not whether data is stored (T67).
def test_datasets_persist_with_caching_disabled(configured_client, tmp_path, origin):
    storage = str(tmp_path / "shared")
    first = configured_client("off", STORAGE_DIR=storage)
    endpoint = convert(first, origin, "/storage-nocache.csv").get_json()["endpoint"]
    restarted = configured_client("off", STORAGE_DIR=storage)
    assert restarted.get(endpoint).get_json()["rows"] == ROWS


# Spec: "when the same directory is reused"
# Context: a different directory is a different store, so nothing carries over.
def test_a_different_directory_starts_empty(configured_client, tmp_path, origin):
    first = configured_client(STORAGE_DIR=str(tmp_path / "one"))
    endpoint = convert(first, origin, "/storage-separate.csv").get_json()["endpoint"]
    other = configured_client(STORAGE_DIR=str(tmp_path / "two"))
    assert other.get(endpoint).status_code == 404


# Spec: "Persisted datasets must survive restart"
# Context: the restarted process serves the stored rows without re-fetching the
# source at all.
def test_a_restart_serves_without_the_origin(configured_client, tmp_path, origin):
    storage = str(tmp_path / "shared")
    first = configured_client(STORAGE_DIR=storage)
    endpoint = convert(first, origin, "/storage-offline.csv").get_json()["endpoint"]
    origin.responses.pop("/storage-offline.csv")
    restarted = configured_client(STORAGE_DIR=storage)
    assert restarted.get(endpoint).get_json()["rows"] == ROWS


# Spec: "Create `STORAGE_DIR` if missing." / "Invalid config ... at startup
# returns an error and exits."
# Context: a path that cannot be a directory because a file is already there
# (T68).
def test_an_uncreatable_storage_dir_fails_startup(tmp_path):
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("", encoding="utf-8")
    from gateway.app import create_app

    with pytest.raises(ConfigError):
        create_app({"STORAGE_DIR": str(occupied)})


# Spec: "| `STORAGE_DIR` | path | implementation-defined |"
# Context: the default is left to the implementation but must still be a usable
# path (T65).
def test_the_default_storage_dir_is_a_path():
    assert load_settings({}).storage_dir


# Spec: "Persisted datasets must survive restart"
# Context: a stored file that is no longer readable as a dataset names nothing,
# which is the answer an unknown id already gets (T69).
def test_a_damaged_stored_dataset_reads_as_missing(configured_client, tmp_path, origin):
    storage = tmp_path / "shared"
    client = configured_client(STORAGE_DIR=str(storage))
    endpoint = convert(client, origin, "/storage-damaged.csv").get_json()["endpoint"]
    stored = next(storage.iterdir())
    stored.write_text("{ not json", encoding="utf-8")
    restarted = configured_client(STORAGE_DIR=str(storage))
    assert restarted.get(endpoint).status_code == 404


# Spec: "Persisted datasets must survive restart when the same directory is
# reused."
# Context: what is stored is the dataset a read serves — its columns and typed
# rows (T66).
def test_the_stored_file_holds_the_dataset(configured_client, tmp_path, origin):
    storage = tmp_path / "shared"
    client = configured_client(STORAGE_DIR=str(storage))
    convert(client, origin, "/storage-contents.csv")
    stored = json.loads(next(storage.iterdir()).read_text(encoding="utf-8"))
    assert stored["columns"] == ["name", "age"]
    assert stored["rows"] == ROWS
