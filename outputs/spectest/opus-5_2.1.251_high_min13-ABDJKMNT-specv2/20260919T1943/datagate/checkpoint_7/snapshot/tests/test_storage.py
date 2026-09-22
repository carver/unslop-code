"""Spec section: Storage Directory."""

import io

from conftest import SIMPLE_CSV, SOURCE_URL

from datagate_app.store import upload_id


def convert(client, source=SOURCE_URL):
    return client.get("/convert", query_string={"source": source})


# Phrase: "Create `STORAGE_DIR` if missing."
def test_storage_directory_is_created_at_startup(configured, storage_dir):
    assert not storage_dir.exists()

    configured()

    assert storage_dir.is_dir()


# Phrase: "Create `STORAGE_DIR` if missing." (context: missing parent directories)
def test_missing_parent_directories_are_created(configured, tmp_path):
    nested = tmp_path / "var" / "lib" / "datagate"

    configured(STORAGE_DIR=str(nested))

    assert nested.is_dir()


# Phrase: "Create `STORAGE_DIR` if missing." (context: an existing directory is reused as-is)
def test_an_existing_directory_is_reused(configured, storage_dir, serve):
    serve(SIMPLE_CSV)
    convert(configured())

    configured()

    assert storage_dir.is_dir()


# Phrase: "Persisted datasets must survive restart when the same directory is reused."
def test_converted_dataset_survives_a_restart(configured, serve):
    serve(SIMPLE_CSV)
    endpoint = convert(configured()).get_json()["endpoint"]

    restarted = configured()

    assert restarted.get(endpoint).get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Persisted datasets must survive restart ..." (context: columns and totals come back too)
def test_restart_preserves_columns_and_total(configured, serve):
    serve(SIMPLE_CSV)
    endpoint = convert(configured()).get_json()["endpoint"]

    body = configured().get(endpoint).get_json()

    assert body["columns"] == ["name", "age"] and body["total"] == 2


# Phrase: "Persisted datasets must survive restart ..." (context: object rows keep their source row numbers)
def test_restart_preserves_rowids(configured, serve):
    serve("name\nada\n\ngrace\n")
    endpoint = convert(configured()).get_json()["endpoint"]

    body = configured().get(endpoint + "?_shape=objects").get_json()

    assert [row["rowid"] for row in body["rows"]] == [2, 4]


# Phrase: "Persisted datasets must survive restart ..." (context: uploads persist as well)
def test_uploaded_dataset_survives_a_restart(configured):
    payload = {"file": (io.BytesIO(SIMPLE_CSV.encode()), "data.csv")}
    configured().post("/upload", data=payload, content_type="multipart/form-data")

    restarted = configured()

    assert restarted.get(f"/datasets/{upload_id(SIMPLE_CSV.encode())}").status_code == 200


# Phrase: "... when the same directory is reused." (context: a different directory starts empty)
def test_a_different_directory_does_not_see_the_dataset(configured, serve, tmp_path):
    serve(SIMPLE_CSV)
    endpoint = convert(configured()).get_json()["endpoint"]

    elsewhere = configured(STORAGE_DIR=str(tmp_path / "other"))

    assert elsewhere.get(endpoint).status_code == 404


# Phrase: "Persisted datasets must survive restart ..." (context: the cache spans restarts as well)
def test_restart_answers_from_storage_without_re_downloading(configured, serve, remote):
    serve(SIMPLE_CSV)
    convert(configured())

    convert(configured())

    assert len(remote.calls) == 1
