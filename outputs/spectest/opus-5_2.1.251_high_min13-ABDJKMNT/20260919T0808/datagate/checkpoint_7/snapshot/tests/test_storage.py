"""Spec section: Storage Directory."""

import io
from pathlib import Path

import pytest

SIMPLE_CSV = "name,age\nada,36\n"
OTHER_CSV = "city,country\nlyon,france\n"


def upload(client, body):
    return client.post(
        "/upload",
        data={"file": (io.BytesIO(body.encode()), "data.csv")},
        content_type="multipart/form-data",
    )


@pytest.fixture
def storage(configured_client, tmp_path):
    """Start an app on a chosen directory; call again to restart on the same one."""

    def _storage(directory):
        return configured_client(STORAGE_DIR=str(directory))

    return _storage


# Phrase: "Create `STORAGE_DIR` if missing."
def test_a_missing_storage_directory_is_created(storage, tmp_path):
    directory = tmp_path / "fresh"
    storage(directory)

    assert directory.is_dir()


# Phrase: "Create `STORAGE_DIR` if missing." - including missing parents.
def test_missing_parents_are_created(storage, tmp_path):
    directory = tmp_path / "a" / "b" / "c"
    storage(directory)

    assert directory.is_dir()


# Phrase: "Create `STORAGE_DIR` if missing." - an existing directory and the
# datasets already in it are left alone.
def test_an_existing_directory_is_reused(storage, tmp_path):
    directory = tmp_path / "reused"
    directory.mkdir()
    endpoint = upload(storage(directory), SIMPLE_CSV).get_json()["endpoint"]

    assert storage(directory).get(endpoint).status_code == 200


# Phrase: "| `STORAGE_DIR` | path | implementation-defined |" - the default is
# whatever the implementation picks, but it must be a usable directory (T70).
def test_the_default_storage_directory_is_usable(configured_client, monkeypatch, tmp_path):
    monkeypatch.delenv("STORAGE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    client = configured_client()

    endpoint = upload(client, SIMPLE_CSV).get_json()["endpoint"]

    assert client.get(endpoint).status_code == 200
    assert any(path.is_dir() for path in Path(tmp_path).iterdir())


# Phrase: "Persisted datasets must survive restart when the same directory is
# reused." - an uploaded dataset is still served after a restart (T71).
def test_an_uploaded_dataset_survives_restart(storage, tmp_path):
    directory = tmp_path / "keep"
    endpoint = upload(storage(directory), SIMPLE_CSV).get_json()["endpoint"]

    payload = storage(directory).get(endpoint).get_json()

    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["ada", 36]]


# Phrase: "Persisted datasets must survive restart" - a converted dataset too.
def test_a_converted_dataset_survives_restart(storage, origin, tmp_path):
    directory = tmp_path / "keep-convert"
    url = origin.serve("/persist-convert.csv", SIMPLE_CSV)
    endpoint = storage(directory).get(f"/convert?source={url}").get_json()["endpoint"]

    assert storage(directory).get(endpoint).get_json()["columns"] == ["name", "age"]


# Phrase: "Persisted datasets must survive restart" - the id is stable, so the
# restarted process mints the same endpoint for the same source.
def test_the_endpoint_is_the_same_after_restart(storage, origin, tmp_path):
    directory = tmp_path / "stable"
    url = origin.serve("/persist-stable.csv", SIMPLE_CSV)

    first = storage(directory).get(f"/convert?source={url}").get_json()["endpoint"]
    second = storage(directory).get(f"/convert?source={url}").get_json()["endpoint"]

    assert first == second


# Phrase: "Persisted datasets must survive restart" - and the `/convert` cache
# survives with them, so a restarted process answers without re-downloading (T71).
def test_the_convert_cache_survives_restart(storage, origin, tmp_path):
    directory = tmp_path / "cached"
    url = origin.serve("/persist-cache.csv", SIMPLE_CSV)
    storage(directory).get(f"/convert?source={url}")

    downloads = origin.hits("/persist-cache.csv")
    assert storage(directory).get(f"/convert?source={url}").status_code == 200
    assert origin.hits("/persist-cache.csv") == downloads


# Phrase: "when the same directory is reused" - a different directory is a
# different store, and knows nothing of the first.
def test_a_different_directory_starts_empty(storage, tmp_path):
    endpoint = upload(storage(tmp_path / "one"), SIMPLE_CSV).get_json()["endpoint"]

    assert storage(tmp_path / "two").get(endpoint).status_code == 404


# Phrase: "Persisted datasets ..." - a value replaced in one run is the value
# the next run reads back.
def test_a_replaced_dataset_persists_its_replacement(storage, origin, tmp_path):
    directory = tmp_path / "replaced"
    url = origin.serve("/persist-replace.csv", SIMPLE_CSV)
    client = storage(directory)
    endpoint = client.get(f"/convert?source={url}").get_json()["endpoint"]

    origin.serve("/persist-replace.csv", OTHER_CSV)
    client.get(f"/convert?source={url}&force")

    assert storage(directory).get(endpoint).get_json()["columns"] == ["city", "country"]


# Phrase: "Persisted datasets ..." - inferred cell types survive the round trip,
# so a reloaded dataset filters and sorts exactly as the original did.
def test_cell_types_survive_the_round_trip(storage, tmp_path):
    directory = tmp_path / "types"
    body = "name,age,score\nada,36,1.5\ngrace,45,2.5\n"
    endpoint = upload(storage(directory), body).get_json()["endpoint"]

    reloaded = storage(directory).get(f"{endpoint}?age__greater=40")

    assert reloaded.get_json()["rows"] == [["grace", 45, 2.5]]
