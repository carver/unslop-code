"""Tests for STORAGE_DIR: its creation and datasets outliving the process that made them."""

from datagate.app import create_app

CSV = b"name,age\nada,36\n"


def test_the_storage_directory_is_created(configured_client, tmp_path):
    directory = tmp_path / "datasets" / "nested"

    configured_client(STORAGE_DIR=str(directory))

    assert directory.is_dir()


def test_a_converted_dataset_survives_a_restart(configured_client, serve, tmp_path):
    client = configured_client(STORAGE_DIR=str(tmp_path / "datasets"))
    source = serve("a.csv", CSV)
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]

    restarted = create_app().test_client()

    assert restarted.get(endpoint).json["rows"] == [["ada", 36]]


def test_a_restart_on_a_fresh_directory_forgets_datasets(
    configured_client, serve, tmp_path, monkeypatch
):
    client = configured_client(STORAGE_DIR=str(tmp_path / "datasets"))
    endpoint = client.get(
        "/convert", query_string={"source": serve("a.csv", CSV)}
    ).json["endpoint"]

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "elsewhere"))
    restarted = create_app().test_client()

    assert restarted.get(endpoint).status_code == 404


def test_a_stored_dataset_keeps_its_cell_types(configured_client, serve, tmp_path):
    client = configured_client(STORAGE_DIR=str(tmp_path / "datasets"))
    source = serve("a.csv", b"name,age,score\nada,36,1.5\n")
    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]

    restarted = create_app().test_client()

    assert restarted.get(endpoint).json["rows"] == [["ada", 36, 1.5]]
