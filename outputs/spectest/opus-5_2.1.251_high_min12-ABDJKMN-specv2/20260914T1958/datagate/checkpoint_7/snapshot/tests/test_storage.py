"""Spec section: Storage Directory."""
import os

from conftest import (
    convert_ok,
    free_port,
    port_is_closed,
    start_expecting_failure,
    start_gate,
    upload_ok,
    write_config,
)

A = "city,pop\nOslo,700000\nLima,9000000\n"
ROWS_A = [["Oslo", 700000], ["Lima", 9000000]]


def rows_of(gate, endpoint):
    resp = gate.get(endpoint)
    assert resp.status_code == 200, resp.text
    return resp.json()["rows"]


# ---------------------------------------------------------------------------
# Phrase: "Create `STORAGE_DIR` if missing."
# Context: the configured directory does not exist when the service starts.
# ---------------------------------------------------------------------------
def test_storage_dir_is_created_if_missing(fresh_gate, tmp_path):
    target = tmp_path / "storage"
    assert not target.exists()
    fresh_gate(port=free_port(), address="127.0.0.1",
               env={"STORAGE_DIR": str(target)})
    assert target.is_dir()


# ---------------------------------------------------------------------------
# Phrase: "Create `STORAGE_DIR` if missing."
# Context: a nested path whose parents are also missing.
# ---------------------------------------------------------------------------
def test_storage_dir_parents_are_created(fresh_gate, tmp_path):
    target = tmp_path / "a" / "b" / "c"
    fresh_gate(port=free_port(), address="127.0.0.1",
               env={"STORAGE_DIR": str(target)})
    assert target.is_dir()


# ---------------------------------------------------------------------------
# Phrase: "Create `STORAGE_DIR` if missing."
# Context: an existing directory is reused, not recreated or emptied.
# ---------------------------------------------------------------------------
def test_existing_storage_dir_is_reused(fresh_gate, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("hello")
    fresh_gate(port=free_port(), address="127.0.0.1",
               env={"STORAGE_DIR": str(target)})
    assert marker.read_text() == "hello"


# ---------------------------------------------------------------------------
# Phrase: "Persisted datasets must survive restart when the same directory
#          is reused."
# Context: /convert, stop, start again on the same STORAGE_DIR.
# ---------------------------------------------------------------------------
def test_converted_dataset_survives_restart(origin, tmp_path):
    storage = str(tmp_path / "store")
    env = {"STORAGE_DIR": storage}
    url = origin.add("/store-restart.csv", A)

    first = start_gate(port=free_port(), address="127.0.0.1", env=env)
    try:
        endpoint = convert_ok(first, url)
        assert rows_of(first, endpoint) == ROWS_A
    finally:
        first.stop()

    second = start_gate(port=free_port(), address="127.0.0.1", env=env)
    try:
        assert rows_of(second, endpoint) == ROWS_A
    finally:
        second.stop()


# ---------------------------------------------------------------------------
# Phrase: "Persisted datasets must survive restart ..."
# Context: an uploaded dataset has no source URL to re-fetch, so persistence
#          is the only way it can survive.
# ---------------------------------------------------------------------------
def test_uploaded_dataset_survives_restart(tmp_path):
    storage = str(tmp_path / "store")
    env = {"STORAGE_DIR": storage}

    first = start_gate(port=free_port(), address="127.0.0.1", env=env)
    try:
        endpoint = upload_ok(first, A)
        assert rows_of(first, endpoint) == ROWS_A
    finally:
        first.stop()

    second = start_gate(port=free_port(), address="127.0.0.1", env=env)
    try:
        body = second.get(endpoint).json()
        assert body["columns"] == ["city", "pop"]
        assert body["rows"] == ROWS_A
    finally:
        second.stop()


# ---------------------------------------------------------------------------
# Phrase: "... when the same directory is reused."
# Context: a different directory holds nothing, so the dataset is unknown.
# ---------------------------------------------------------------------------
def test_dataset_does_not_appear_in_a_different_storage_dir(origin, tmp_path):
    url = origin.add("/store-other-dir.csv", A)
    first = start_gate(port=free_port(), address="127.0.0.1",
                       env={"STORAGE_DIR": str(tmp_path / "one")})
    try:
        endpoint = convert_ok(first, url)
    finally:
        first.stop()

    second = start_gate(port=free_port(), address="127.0.0.1",
                        env={"STORAGE_DIR": str(tmp_path / "two")})
    try:
        assert second.get(endpoint).status_code == 404
    finally:
        second.stop()


# ---------------------------------------------------------------------------
# Phrase: "Persisted datasets must survive restart ..."
# Context: the persisted rows keep their inferred types, not just their text.
# ---------------------------------------------------------------------------
def test_persisted_rows_keep_their_inferred_types(tmp_path):
    storage = str(tmp_path / "store")
    env = {"STORAGE_DIR": storage}
    payload = "s,i,f,b,e\nx,1,2.5,true,\n"

    first = start_gate(port=free_port(), address="127.0.0.1", env=env)
    try:
        endpoint = upload_ok(first, payload)
        before = first.get(endpoint).json()
    finally:
        first.stop()

    second = start_gate(port=free_port(), address="127.0.0.1", env=env)
    try:
        after = second.get(endpoint).json()
    finally:
        second.stop()
    assert after["columns"] == before["columns"]
    assert after["rows"] == before["rows"]


# ---------------------------------------------------------------------------
# Phrase: "Persisted datasets must survive restart ..."
# Context: query controls work identically against a dataset loaded from disk.
# ---------------------------------------------------------------------------
def test_persisted_dataset_still_supports_queries(tmp_path):
    storage = str(tmp_path / "store")
    env = {"STORAGE_DIR": storage}

    first = start_gate(port=free_port(), address="127.0.0.1", env=env)
    try:
        endpoint = upload_ok(first, A)
    finally:
        first.stop()

    second = start_gate(port=free_port(), address="127.0.0.1", env=env)
    try:
        body = second.get(endpoint, params={"_size": 1, "_sort": "pop"}).json()
        assert body["rows"] == [["Oslo", 700000]]
        assert body["total"] == 2
        export = second.get(endpoint + "/export")
        assert export.status_code == 200
        assert "Oslo" in export.text
    finally:
        second.stop()


# ---------------------------------------------------------------------------
# Phrase: "`STORAGE_DIR` | path | implementation-defined"
# Context: the directory is configurable through DATAGATE_CONFIG too.
# ---------------------------------------------------------------------------
def test_storage_dir_from_the_config_file(fresh_gate, tmp_path):
    target = tmp_path / "from-config"
    cfg = write_config(tmp_path, f"STORAGE_DIR={target}\n")
    fresh_gate(port=free_port(), address="127.0.0.1",
               env={"DATAGATE_CONFIG": cfg})
    assert target.is_dir()


# ---------------------------------------------------------------------------
# Phrase: "3. Direct environment variables" applied to STORAGE_DIR
# Context: the environment wins over the config file for the path too.
# ---------------------------------------------------------------------------
def test_storage_dir_environment_overrides_config_file(fresh_gate, tmp_path):
    from_file = tmp_path / "file-dir"
    from_env = tmp_path / "env-dir"
    cfg = write_config(tmp_path, f"STORAGE_DIR={from_file}\n")
    fresh_gate(port=free_port(), address="127.0.0.1",
               env={"DATAGATE_CONFIG": cfg, "STORAGE_DIR": str(from_env)})
    assert from_env.is_dir()
    assert not from_file.exists()


# ---------------------------------------------------------------------------
# Phrase: "Create `STORAGE_DIR` if missing." / "Invalid config ... exits."
# Context: a path that cannot be created as a directory is a startup failure.
# ---------------------------------------------------------------------------
def test_uncreatable_storage_dir_is_a_startup_failure(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file")
    code, log, port = start_expecting_failure(env={"STORAGE_DIR": str(blocker)})
    assert code != 0
    assert "STORAGE_DIR" in log or str(blocker) in log
    assert port_is_closed(port)


# ---------------------------------------------------------------------------
# Phrase: "`STORAGE_DIR` | path | implementation-defined"
# Context: with no STORAGE_DIR configured the service still starts and stores.
# ---------------------------------------------------------------------------
def test_default_storage_dir_works_without_configuration(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1")
    url = origin.add("/store-default.csv", A)
    endpoint = convert_ok(gate, url)
    assert rows_of(gate, endpoint) == ROWS_A
    assert os.environ.get("STORAGE_DIR") is None
