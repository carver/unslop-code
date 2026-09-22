"""Spec tests for "Storage Directory". Each section quotes its phrase."""
import os
import urllib.parse

import pytest

from conftest import assert_startup_failure, running

SIMPLE = "name,age\nada,36\ngrace,45\n"


def hits(origin, url):
    return origin.hits.get(urllib.parse.urlsplit(url).path, 0)


def rows_at(client, endpoint):
    status, _, payload = client.get(endpoint)
    assert status == 200, payload
    return payload["rows"]


@pytest.fixture
def store(tmp_path):
    """An unused STORAGE_DIR path (the server is expected to create it)."""
    counter = {"n": 0}

    def make(name=None, create=False):
        counter["n"] += 1
        path = tmp_path / (name or "store-%d" % counter["n"])
        if create:
            path.mkdir(parents=True)
        return str(path)
    return make


def env_for(path, **extra):
    env = {"STORAGE_DIR": path, "DATAGATE_CONFIG": None}
    env.update(extra)
    return env


# ==========================================================================
# Spec: "Create `STORAGE_DIR` if missing."
# ==========================================================================
def test_storage_dir_is_created(store):
    path = store()
    assert not os.path.exists(path)
    with running(env_for(path), "store_new") as client:
        assert client.get("/datasets/unknown")[0] == 404
        assert os.path.isdir(path)


def test_nested_storage_dir_is_created(store):
    path = os.path.join(store(), "a", "b", "c")
    with running(env_for(path), "store_new") as client:
        assert client.get("/datasets/unknown")[0] == 404
    assert os.path.isdir(path)


def test_existing_storage_dir_is_reused(store):
    path = store(create=True)
    with running(env_for(path), "store_new") as client:
        assert client.upload(SIMPLE.encode("utf-8"))[0] == 200
    assert os.path.isdir(path)
    assert os.listdir(path), "a stored dataset should leave something behind"


# A `STORAGE_DIR` that cannot be created is invalid configuration
# (AMBIGUITIES T98).
def test_storage_dir_that_is_a_file_fails_startup(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    assert_startup_failure(env_for(str(blocker)), "store_bad")


# ==========================================================================
# Spec: "Persisted datasets must survive restart when the same directory is
#        reused."
# ==========================================================================
def test_converted_dataset_survives_restart(store, csv_url):
    path = store()
    url = csv_url(SIMPLE, name="persist-convert")
    with running(env_for(path), "store_a") as first:
        endpoint = first.convert(url)[2]["endpoint"]
        assert rows_at(first, endpoint) == [["ada", 36], ["grace", 45]]
    with running(env_for(path), "store_b") as second:
        status, _, payload = second.get(endpoint)
        assert status == 200, payload
        assert payload["columns"] == ["name", "age"]
        assert payload["rows"] == [["ada", 36], ["grace", 45]]


def test_uploaded_dataset_survives_restart(store):
    path = store()
    with running(env_for(path), "store_a") as first:
        status, _, data = first.upload(SIMPLE.encode("utf-8"))
        assert status == 200, data
        endpoint = data["endpoint"]
    with running(env_for(path), "store_b") as second:
        assert rows_at(second, endpoint) == [["ada", 36], ["grace", 45]]


def test_restored_dataset_supports_queries_and_export(store):
    path = store()
    body = "name,age\nada,36\ngrace,45\nlin,29\n"
    with running(env_for(path), "store_a") as first:
        endpoint = first.upload(body.encode("utf-8"))[2]["endpoint"]
    with running(env_for(path), "store_b") as second:
        status, _, payload = second.get(endpoint + "?_size=1&_sort=age")
        assert status == 200, payload
        assert payload["rows"] == [["lin", 29]]
        assert payload["total"] == 3
        status, _, raw = second.raw(endpoint + "/export")
        assert status == 200
        assert b"grace" in raw


# Spec: "survive restart" — a restart with caching on serves the stored dataset
# without re-downloading the source.
def test_restart_keeps_the_convert_cache(store, origin, csv_url):
    path = store()
    url = csv_url(SIMPLE, name="persist-cache")
    with running(env_for(path), "store_a") as first:
        endpoint = first.convert(url)[2]["endpoint"]
    baseline = hits(origin, url)
    with running(env_for(path), "store_b") as second:
        assert second.convert(url)[2]["endpoint"] == endpoint
        assert hits(origin, url) == baseline


# Spec: "... when the same directory is reused." — a different directory is a
# different store.
def test_a_different_directory_does_not_see_the_data(store):
    first_path, second_path = store(), store()
    with running(env_for(first_path), "store_a") as first:
        endpoint = first.upload(SIMPLE.encode("utf-8"))[2]["endpoint"]
    with running(env_for(second_path), "store_b") as second:
        status, _, data = second.get(endpoint)
        assert status == 404, data
        assert data["ok"] is False


# Several datasets persist together.
def test_multiple_datasets_survive_restart(store):
    path = store()
    payloads = ["a,b\n1,2\n", "c,d\n3,4\n", "e,f\n5,6\n"]
    with running(env_for(path), "store_a") as first:
        endpoints = [first.upload(p.encode("utf-8"))[2]["endpoint"]
                     for p in payloads]
    with running(env_for(path), "store_b") as second:
        for endpoint, expected in zip(endpoints, [[[1, 2]], [[3, 4]], [[5, 6]]]):
            assert rows_at(second, endpoint) == expected


# Persistence is independent of `CACHE_ENABLED` (AMBIGUITIES T96).
def test_datasets_persist_with_caching_disabled(store):
    path = store()
    with running(env_for(path, CACHE_ENABLED="false"), "store_a") as first:
        endpoint = first.upload(SIMPLE.encode("utf-8"))[2]["endpoint"]
    with running(env_for(path, CACHE_ENABLED="false"), "store_b") as second:
        assert rows_at(second, endpoint) == [["ada", 36], ["grace", 45]]


# A dataset replaced in one run stays replaced after a restart.
def test_replaced_dataset_persists_in_its_new_form(store, origin, csv_url):
    path = store()
    url = csv_url(SIMPLE, name="persist-replace")
    env = env_for(path, CACHE_ENABLED="false")
    with running(env, "store_a") as first:
        endpoint = first.convert(url)[2]["endpoint"]
        origin.add(urllib.parse.urlsplit(url).path, "name,age\nlin,29\n")
        first.convert(url)
        assert rows_at(first, endpoint) == [["lin", 29]]
    with running(env, "store_b") as second:
        assert rows_at(second, endpoint) == [["lin", 29]]


# Unrelated junk in the directory does not stop startup (AMBIGUITIES T97).
def test_unreadable_entries_in_the_store_are_ignored(store):
    path = store(create=True)
    with open(os.path.join(path, "notes.txt"), "w") as handle:
        handle.write("not a dataset")
    with open(os.path.join(path, "broken.json"), "w") as handle:
        handle.write("{not json")
    with running(env_for(path), "store_new") as client:
        status, _, data = client.upload(SIMPLE.encode("utf-8"))
        assert status == 200, data
        assert rows_at(client, data["endpoint"]) == [["ada", 36], ["grace", 45]]


# Spec: "| `STORAGE_DIR` | path | implementation-defined |" — with nothing
# configured the service still starts and stores datasets (AMBIGUITIES T94).
def test_default_storage_dir_works():
    with running({"STORAGE_DIR": None, "DATAGATE_CONFIG": None},
                 "store_default") as client:
        status, _, data = client.upload("h,i\ndefault-store,1\n".encode("utf-8"))
        assert status == 200, data
        assert rows_at(client, data["endpoint"]) == [["default-store", 1]]
