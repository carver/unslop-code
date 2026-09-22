"""Spec section: Storage Directory.

    Create `STORAGE_DIR` if missing.
    Persisted datasets must survive restart when the same directory is reused.
"""

import json
import os
from urllib.parse import quote

import datagate
from conftest import free_port as _free_port, http_get as _http_get

SIMPLE = "name,age\nalice,30\nbob,41\n"


# ---------------------------------------------------------------------------
# "Create `STORAGE_DIR` if missing."
# ---------------------------------------------------------------------------


# Phrase: "Create `STORAGE_DIR` if missing."
def test_storage_dir_is_created_when_missing(configure, tmp_path):
    target = tmp_path / "brand" / "new" / "store"
    assert not target.exists()
    assert configure(STORAGE_DIR=str(target)) is None
    assert target.is_dir()


# Phrase: "Create `STORAGE_DIR` if missing." -- an existing directory is reused
# untouched, with its contents intact.
def test_existing_storage_dir_is_reused(configure, tmp_path):
    target = tmp_path / "store"
    target.mkdir()
    (target / "keep.txt").write_text("hello", encoding="utf-8")
    assert configure(STORAGE_DIR=str(target)) is None
    assert (target / "keep.txt").read_text(encoding="utf-8") == "hello"


# Phrase: "Create `STORAGE_DIR` if missing." -- from the config file too.
def test_storage_dir_from_the_config_file(configure, config_file, tmp_path):
    target = tmp_path / "from-file"
    path = config_file("STORAGE_DIR={}\n".format(target))
    assert configure(DATAGATE_CONFIG=path, STORAGE_DIR=None) is None
    assert datagate.STORAGE_DIR == str(target)
    assert target.is_dir()


# Phrase: "Create `STORAGE_DIR` if missing." -- if it cannot be created, that
# is a startup error (AMBIGUITIES T79).
def test_uncreatable_storage_dir_is_a_config_error(configure, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory", encoding="utf-8")
    message = configure(STORAGE_DIR=str(blocker / "store"))
    assert isinstance(message, str) and message.strip()


# ---------------------------------------------------------------------------
# "Persisted datasets must survive restart when the same directory is reused."
# ---------------------------------------------------------------------------


# Phrase: "Persisted datasets ..." -- a dataset ingested via /convert leaves
# something behind in STORAGE_DIR (AMBIGUITIES T77).
def test_convert_writes_into_the_storage_dir(configure, client, origin, tmp_path):
    target = tmp_path / "store-convert"
    assert configure(STORAGE_DIR=str(target)) is None
    origin.add("/persist-convert.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/persist-convert.csv")})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert os.listdir(target)


# Phrase: "Persisted datasets ..." -- an /upload dataset is persisted as well.
def test_upload_writes_into_the_storage_dir(configure, client, upload, tmp_path):
    target = tmp_path / "store-upload"
    assert configure(STORAGE_DIR=str(target)) is None
    assert upload(SIMPLE).status_code == 200
    assert os.listdir(target)


# Phrase: "Persisted datasets must survive restart" -- simulated in-process:
# a fresh load of the same directory brings the dataset back.
def test_dataset_survives_a_reload_of_the_same_directory(configure, client, upload,
                                                         tmp_path):
    target = tmp_path / "store-reload"
    assert configure(STORAGE_DIR=str(target)) is None
    endpoint = upload(SIMPLE).get_json()["endpoint"]

    datagate._store.clear()  # simulate a process restart: memory gone, disk kept
    assert configure(STORAGE_DIR=str(target)) is None

    response = client.get(endpoint)
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "when the same directory is reused" -- a *different* directory shares
# nothing.
def test_a_different_directory_does_not_see_the_dataset(configure, client, upload,
                                                        tmp_path):
    assert configure(STORAGE_DIR=str(tmp_path / "store-a")) is None
    endpoint = upload(SIMPLE).get_json()["endpoint"]

    datagate._store.clear()
    assert configure(STORAGE_DIR=str(tmp_path / "store-b")) is None
    assert client.get(endpoint).status_code == 404


# Phrase: "Persisted datasets must survive restart" -- across a real process
# restart of the documented `start` command.
def test_dataset_survives_a_process_restart(server, origin, tmp_path):
    store = str(tmp_path / "restart-store")
    origin.add("/persist-restart.csv", SIMPLE)
    source = origin.url("/persist-restart.csv")

    port = _free_port()
    first = server("--port", str(port), name="persist-first",
                   env={"STORAGE_DIR": store})
    assert first.wait_until_listening("127.0.0.1", port), first.log()
    status, body = _http_get("127.0.0.1", port,
                             "/convert?source={}".format(quote(source, safe="")))
    assert status == 200, body
    endpoint = json.loads(body)["endpoint"]
    first.stop()

    port = _free_port()
    second = server("--port", str(port), name="persist-second",
                    env={"STORAGE_DIR": store})
    assert second.wait_until_listening("127.0.0.1", port), second.log()
    status, body = _http_get("127.0.0.1", port, endpoint)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["alice", 30], ["bob", 41]]


# Phrase: "Persisted datasets must survive restart" -- and the restarted
# server serves them without re-contacting the origin (AMBIGUITIES T78).
def test_restarted_server_does_not_refetch_a_cached_source(server, origin, tmp_path):
    store = str(tmp_path / "refetch-store")
    path = "/persist-cache.csv"
    origin.add(path, SIMPLE)
    source = origin.url(path)
    query = "/convert?source={}".format(quote(source, safe=""))

    port = _free_port()
    first = server("--port", str(port), name="refetch-first",
                   env={"STORAGE_DIR": store})
    assert first.wait_until_listening("127.0.0.1", port), first.log()
    assert _http_get("127.0.0.1", port, query)[0] == 200
    first.stop()

    hits = origin.hits.get(path, 0)
    port = _free_port()
    second = server("--port", str(port), name="refetch-second",
                    env={"STORAGE_DIR": store})
    assert second.wait_until_listening("127.0.0.1", port), second.log()
    assert _http_get("127.0.0.1", port, query)[0] == 200
    assert origin.hits.get(path, 0) == hits


# Phrase: "Persisted datasets must survive restart" -- the reloaded dataset
# keeps its typed cell values, not just their string forms.
def test_reloaded_dataset_keeps_cell_types(configure, client, upload, tmp_path):
    target = tmp_path / "store-types"
    assert configure(STORAGE_DIR=str(target)) is None
    body = "s,i,f,b,e\nx,3,1.5,true,\n"
    endpoint = upload(body).get_json()["endpoint"]
    before = client.get(endpoint).get_json()["rows"]

    datagate._store.clear()
    assert configure(STORAGE_DIR=str(target)) is None
    after = client.get(endpoint).get_json()["rows"]
    assert after == before
