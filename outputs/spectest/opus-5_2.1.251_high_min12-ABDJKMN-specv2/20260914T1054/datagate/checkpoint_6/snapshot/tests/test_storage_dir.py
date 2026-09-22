"""Spec section: Storage Directory.

"Survive restart" is tested twice: cheaply, by building a second app object over the
same directory, and for real, by killing the server process and starting another one.
"""
import io
import json
import urllib.parse
import urllib.request

import datagate
from conftest import spawn_server, stop_server, unused_port, wait_for_server

CSV = "name,qty\nwidget,3\nbolt,7\n"
TYPED = "s,i,f,blank\ntext,42,3.5,\n"


def convert(client, url):
    query = "source=" + urllib.parse.quote(url, safe="")
    return client.get("/convert", query_string=query)


def upload(client, body=CSV):
    if isinstance(body, str):
        body = body.encode("utf-8")
    return client.post("/upload", data={"file": (io.BytesIO(body), "d.csv")},
                       content_type="multipart/form-data")


# =============================================================================
# Phrase: "Create `STORAGE_DIR` if missing."
# Context: the service makes the directory rather than requiring it to exist.
# =============================================================================

def test_missing_storage_dir_is_created(make_app, tmp_path):
    target = tmp_path / "store"
    assert not target.exists()
    make_app(STORAGE_DIR=str(target))
    assert target.is_dir()


def test_missing_parent_directories_are_created(make_app, tmp_path):
    target = tmp_path / "a" / "b" / "c"
    make_app(STORAGE_DIR=str(target))
    assert target.is_dir()


def test_an_existing_storage_dir_is_reused_not_emptied(make_app, tmp_path):
    target = tmp_path / "store"
    target.mkdir()
    (target / "keepme.txt").write_text("hello")
    make_app(STORAGE_DIR=str(target))
    assert (target / "keepme.txt").read_text() == "hello"


def test_unrelated_files_in_the_storage_dir_are_ignored(make_app, tmp_path):
    """Junk in the directory is not config, so it must not stop startup (T76)."""
    target = tmp_path / "store"
    target.mkdir()
    (target / "garbage.json").write_text("{ not json")
    (target / "notes.txt").write_text("hi")
    client = make_app(STORAGE_DIR=str(target)).test_client()
    assert client.get("/datasets/nope").status_code == 404


def test_storage_dir_is_created_by_the_real_server(tmp_path):
    target = tmp_path / "srv-store"
    port = unused_port()
    proc = spawn_server(["start", "--port", str(port)], {"STORAGE_DIR": str(target)})
    try:
        wait_for_server("http://127.0.0.1:%d/datasets/nope" % port, proc)
        assert target.is_dir()
    finally:
        stop_server(proc)


def test_storage_dir_that_cannot_be_created_fails_startup(tmp_path):
    """A plain file sitting at the path is invalid config (AMBIGUITIES T76)."""
    from conftest import assert_startup_failure
    blocker = tmp_path / "afile"
    blocker.write_text("not a directory")
    assert_startup_failure({"STORAGE_DIR": str(blocker)})


# =============================================================================
# Phrase: "Persisted datasets must survive restart when the same directory is
#          reused." - converted datasets.
# Context: a new process over the same directory still answers for the same id.
# =============================================================================

def test_converted_dataset_survives_a_restart(make_app, origin, tmp_path):
    store = str(tmp_path / "store")
    url = origin.add(CSV)
    first = make_app(STORAGE_DIR=store).test_client()
    endpoint = convert(first, url).get_json()["endpoint"]
    second = make_app(STORAGE_DIR=store).test_client()
    response = second.get(endpoint)
    assert response.status_code == 200
    assert response.get_json()["rows"] == [["widget", 3], ["bolt", 7]]


def test_restart_preserves_columns_and_value_types(make_app, origin, tmp_path):
    store = str(tmp_path / "store")
    first = make_app(STORAGE_DIR=store).test_client()
    endpoint = convert(first, origin.add(TYPED)).get_json()["endpoint"]
    before = first.get(endpoint).get_json()
    after = make_app(STORAGE_DIR=store).test_client().get(endpoint).get_json()
    assert after["columns"] == before["columns"] == ["s", "i", "f", "blank"]
    assert after["rows"] == before["rows"] == [["text", 42, 3.5, ""]]


def test_restart_preserves_query_behaviour(make_app, origin, tmp_path):
    store = str(tmp_path / "store")
    first = make_app(STORAGE_DIR=store).test_client()
    endpoint = convert(first, origin.add(CSV)).get_json()["endpoint"]
    second = make_app(STORAGE_DIR=store).test_client()
    payload = second.get(endpoint, query_string={"qty__greater": "5"}).get_json()
    assert payload["rows"] == [["bolt", 7]]
    assert payload["total"] == 1


def test_restart_preserves_export(make_app, origin, tmp_path):
    store = str(tmp_path / "store")
    first = make_app(STORAGE_DIR=store).test_client()
    endpoint = convert(first, origin.add(CSV)).get_json()["endpoint"]
    second = make_app(STORAGE_DIR=store).test_client()
    response = second.get(endpoint + "/export")
    assert response.status_code == 200
    assert response.get_data(as_text=True).splitlines()[0] == "name,qty"


# =============================================================================
# Phrase: "Persisted datasets must survive restart ..." - uploads.
# Context: an uploaded dataset has no source URL to re-fetch, so persistence is
#          the only way it can survive at all.
# =============================================================================

def test_uploaded_dataset_survives_a_restart(make_app, tmp_path):
    store = str(tmp_path / "store")
    first = make_app(STORAGE_DIR=store).test_client()
    endpoint = upload(first).get_json()["endpoint"]
    second = make_app(STORAGE_DIR=store).test_client()
    response = second.get(endpoint)
    assert response.status_code == 200
    assert response.get_json()["rows"] == [["widget", 3], ["bolt", 7]]


def test_several_datasets_all_survive(make_app, origin, tmp_path):
    store = str(tmp_path / "store")
    first = make_app(STORAGE_DIR=store).test_client()
    endpoints = [convert(first, origin.add(CSV)).get_json()["endpoint"],
                 convert(first, origin.add("a,b\n1,2\n")).get_json()["endpoint"],
                 upload(first, "x,y\n9,8\n").get_json()["endpoint"]]
    second = make_app(STORAGE_DIR=store).test_client()
    for endpoint in endpoints:
        assert second.get(endpoint).status_code == 200, endpoint


def test_something_written_after_the_second_app_started_is_also_persisted(
        make_app, tmp_path):
    store = str(tmp_path / "store")
    first = make_app(STORAGE_DIR=store).test_client()
    upload(first, "a,b\n1,2\n")
    second = make_app(STORAGE_DIR=store).test_client()
    endpoint = upload(second, "c,d\n3,4\n").get_json()["endpoint"]
    third = make_app(STORAGE_DIR=store).test_client()
    assert third.get(endpoint).status_code == 200


# =============================================================================
# Phrase: "... when the same directory is reused."
# Context: the guarantee is conditional - a different directory shares nothing.
# =============================================================================

def test_a_different_directory_does_not_see_the_dataset(make_app, origin, tmp_path):
    url = origin.add(CSV)
    first = make_app(STORAGE_DIR=str(tmp_path / "one")).test_client()
    endpoint = convert(first, url).get_json()["endpoint"]
    second = make_app(STORAGE_DIR=str(tmp_path / "two")).test_client()
    assert second.get(endpoint).status_code == 404


def test_default_storage_is_not_shared_between_apps(make_app, origin):
    """With STORAGE_DIR unset the store stays private to the process (T75)."""
    url = origin.add(CSV)
    first = make_app().test_client()
    endpoint = convert(first, url).get_json()["endpoint"]
    assert make_app().test_client().get(endpoint).status_code == 404


def test_unset_storage_dir_still_serves_normally(make_app, origin):
    client = make_app().test_client()
    endpoint = convert(client, origin.add(CSV)).get_json()["endpoint"]
    assert client.get(endpoint).status_code == 200


# =============================================================================
# Phrase: "Persisted datasets must survive restart" - across a real process.
# Context: the strongest form of the guarantee, with the server actually killed.
# =============================================================================

def test_dataset_survives_a_real_process_restart(origin, tmp_path):
    store = str(tmp_path / "store")
    url = origin.add(CSV)
    port = unused_port()
    proc = spawn_server(["start", "--port", str(port)], {"STORAGE_DIR": store})
    try:
        wait_for_server("http://127.0.0.1:%d/datasets/nope" % port, proc)
        query = "source=" + urllib.parse.quote(url, safe="")
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/convert?%s" % (port, query), timeout=10) as r:
            endpoint = json.loads(r.read().decode())["endpoint"]
    finally:
        stop_server(proc)

    port2 = unused_port()
    proc2 = spawn_server(["start", "--port", str(port2)], {"STORAGE_DIR": store})
    try:
        status, payload = wait_for_server(
            "http://127.0.0.1:%d%s" % (port2, endpoint), proc2)
        assert status == 200, payload
        assert payload["rows"] == [["widget", 3], ["bolt", 7]]
    finally:
        stop_server(proc2)


def test_upload_survives_a_real_process_restart(tmp_path):
    store = str(tmp_path / "store")
    body = b"name,qty\nwidget,3\nbolt,7\n"
    identifier = datagate.upload_id(body)
    port = unused_port()
    proc = spawn_server(["start", "--port", str(port)], {"STORAGE_DIR": store})
    try:
        wait_for_server("http://127.0.0.1:%d/datasets/nope" % port, proc)
        boundary = "----datagate"
        payload = (
            "--%s\r\nContent-Disposition: form-data; name=\"file\"; "
            "filename=\"d.csv\"\r\nContent-Type: text/csv\r\n\r\n" % boundary
        ).encode() + body + ("\r\n--%s--\r\n" % boundary).encode()
        request = urllib.request.Request(
            "http://127.0.0.1:%d/upload" % port, data=payload,
            headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
        with urllib.request.urlopen(request, timeout=10) as r:
            assert json.loads(r.read().decode())["endpoint"].endswith(identifier)
    finally:
        stop_server(proc)

    port2 = unused_port()
    proc2 = spawn_server(["start", "--port", str(port2)], {"STORAGE_DIR": store})
    try:
        status, payload = wait_for_server(
            "http://127.0.0.1:%d/datasets/%s" % (port2, identifier), proc2)
        assert status == 200, payload
        assert payload["rows"] == [["widget", 3], ["bolt", 7]]
    finally:
        stop_server(proc2)


# =============================================================================
# Phrase: "Persisted datasets must survive restart ..." - interaction with the
#          caching section (AMBIGUITIES T75).
# Context: the dataset store *is* the cache, so a reused directory also means
#          the source is not downloaded again.
# =============================================================================

def test_reused_directory_does_not_re_download(make_app, origin, tmp_path):
    store = str(tmp_path / "store")
    url = origin.add(CSV)
    first = make_app(STORAGE_DIR=store).test_client()
    convert(first, url)
    before = origin.hits(url)
    second = make_app(STORAGE_DIR=store).test_client()
    convert(second, url)
    assert origin.hits(url) - before == 0


def test_caching_off_still_re_downloads_over_a_reused_directory(
        make_app, origin, tmp_path):
    store = str(tmp_path / "store")
    url = origin.add(CSV)
    first = make_app(STORAGE_DIR=store, CACHE_ENABLED="0").test_client()
    convert(first, url)
    before = origin.hits(url)
    second = make_app(STORAGE_DIR=store, CACHE_ENABLED="0").test_client()
    convert(second, url)
    assert origin.hits(url) - before == 1
