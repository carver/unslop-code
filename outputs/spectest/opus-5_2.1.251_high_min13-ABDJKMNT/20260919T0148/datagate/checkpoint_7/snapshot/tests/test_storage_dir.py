"""Spec section: Storage Directory -- creating `STORAGE_DIR` and surviving a restart."""

import pytest
from helpers import post_upload

from datagate_core.config import ConfigurationError
from datagate_core.server import create_app

CSV = "name,age\nada,36\ngrace,45\n"


def convert(client, source):
    return client.get("/convert", query_string={"source": source})


# Phrase: "Create `STORAGE_DIR` if missing."
def test_the_storage_directory_is_created(monkeypatch, tmp_path):
    directory = tmp_path / "missing"
    monkeypatch.setenv("STORAGE_DIR", str(directory))

    create_app()

    assert directory.is_dir()


# Phrase: "Create `STORAGE_DIR` if missing."
# Context: missing parents are created too.
def test_missing_parent_directories_are_created(monkeypatch, tmp_path):
    directory = tmp_path / "a" / "b" / "c"
    monkeypatch.setenv("STORAGE_DIR", str(directory))

    create_app()

    assert directory.is_dir()


# Phrase: "Create `STORAGE_DIR` if missing."
# Context: an existing directory is reused, not emptied.
def test_an_existing_directory_is_reused(monkeypatch, tmp_path, origin):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(create_app().test_client(), source).get_json()["endpoint"]

    assert create_app().test_client().get(endpoint).status_code == 200


# Phrase: "Create `STORAGE_DIR` if missing."
# Context: a path that cannot become a directory fails startup (AMBIGUITIES T72).
def test_a_storage_path_that_is_a_file_fails_startup(monkeypatch, tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("", encoding="utf-8")
    monkeypatch.setenv("STORAGE_DIR", str(blocked))

    with pytest.raises(ConfigurationError):
        create_app()


# Phrase: "Persisted datasets must survive restart when the same directory is reused."
def test_a_converted_dataset_survives_a_restart(monkeypatch, tmp_path, origin):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(create_app().test_client(), source).get_json()["endpoint"]

    body = create_app().test_client().get(endpoint).get_json()

    assert body["rows"] == [["ada", 36], ["grace", 45]]
    assert body["columns"] == ["name", "age"]


# Phrase: "Persisted datasets must survive restart when the same directory is reused."
# Context: an uploaded dataset persists as well (AMBIGUITIES T71).
def test_an_uploaded_dataset_survives_a_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    endpoint = post_upload(create_app().test_client(), CSV).get_json()["endpoint"]

    assert create_app().test_client().get(endpoint).get_json()["rows"] == [
        ["ada", 36],
        ["grace", 45],
    ]


# Phrase: "Persisted datasets must survive restart when the same directory is reused."
# Context: a restarted process answers `/convert` from disk (AMBIGUITIES T71).
def test_a_restart_serves_convert_from_the_stored_dataset(monkeypatch, tmp_path, origin):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    source = origin.serve("/data.csv", CSV)
    convert(create_app().test_client(), source)

    convert(create_app().test_client(), source)

    assert origin.downloads("/data.csv") == 1


# Phrase: "when the same directory is reused"
# Context: a different directory starts empty.
def test_a_different_directory_does_not_see_the_dataset(monkeypatch, tmp_path, origin):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "first"))
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(create_app().test_client(), source).get_json()["endpoint"]

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "second"))

    assert create_app().test_client().get(endpoint).status_code == 404


# Phrase: "Persisted datasets must survive restart"
# Context: the export of a persisted dataset is byte-identical after a restart.
def test_export_of_a_persisted_dataset_survives_a_restart(monkeypatch, tmp_path, origin):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(create_app().test_client(), source).get_json()["endpoint"]

    first = create_app().test_client().get(endpoint + "/export").data
    second = create_app().test_client().get(endpoint + "/export").data

    assert first == second == b"name,age\r\nada,36\r\ngrace,45\r\n"


# Phrase: "Persisted datasets must survive restart"
# Context: replacing a dataset replaces what the next process reads.
def test_a_replacement_is_persisted(monkeypatch, tmp_path, origin):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("CACHE_ENABLED", "off")
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(create_app().test_client(), source).get_json()["endpoint"]

    origin.serve("/data.csv", "name,age\nalan,41\n")
    convert(create_app().test_client(), source)

    assert create_app().test_client().get(endpoint).get_json()["rows"] == [["alan", 41]]
