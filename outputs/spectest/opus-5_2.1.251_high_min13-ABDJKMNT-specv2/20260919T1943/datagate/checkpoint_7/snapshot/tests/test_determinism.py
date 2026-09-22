"""Spec section: Determinism."""

from conftest import SIMPLE_CSV, SIMPLE_SHEET, SOURCE_URL, xlsx_bytes

from datagate_app.server import create_app
from datagate_app.store import dataset_id, upload_id


# Phrase: "Same `source` URL always maps to the same dataset id."
def test_dataset_id_depends_only_on_the_source_string():
    assert dataset_id(SOURCE_URL) == dataset_id(SOURCE_URL)
    assert dataset_id(SOURCE_URL) != dataset_id(SOURCE_URL + "?v=2")


# Phrase: "Same `source` URL always maps to the same dataset id." (context: across server restarts)
def test_same_url_maps_to_same_id_in_a_fresh_server(client, serve):
    source = serve(SIMPLE_CSV)
    first = client.get("/convert", query_string={"source": source}).get_json()["endpoint"]

    fresh = create_app().test_client()
    second = fresh.get("/convert", query_string={"source": source}).get_json()["endpoint"]

    assert first == second


# Phrase: "columns and each row follow source column order."
def test_column_order_is_stable_across_queries(dataset):
    body = dataset("z,y,x\n1,2,3\n")

    assert body["columns"] == ["z", "y", "x"]
    assert body["rows"] == [[1, 2, 3]]


# Phrase: "Type inference is deterministic."
def test_repeated_queries_return_identical_payloads(client, serve):
    endpoint = client.get("/convert", query_string={"source": serve(SIMPLE_CSV)}).get_json()["endpoint"]

    first = client.get(endpoint).get_json()
    second = client.get(endpoint).get_json()

    assert first["columns"] == second["columns"]
    assert first["rows"] == second["rows"]


# Phrase: "No dependence on clock/locale/timezone beyond `query_ms`."
def test_only_query_ms_varies_between_queries(client, serve):
    endpoint = client.get("/convert", query_string={"source": serve(SIMPLE_CSV)}).get_json()["endpoint"]

    first = client.get(endpoint).get_json()
    second = client.get(endpoint).get_json()

    assert {k: v for k, v in first.items() if k != "query_ms"} == {
        k: v for k, v in second.items() if k != "query_ms"
    }


# Phrase: "Type inference is deterministic." (context: a column may mix text and numbers per cell)
def test_mixed_column_infers_each_cell_independently(dataset):
    body = dataset("value\n1\nna\n2.5\n08:30\n")

    assert body["rows"] == [[1], ["na"], [2.5], ["08:30"]]


# Phrase: "export columns follow source column order." (context: across fresh servers)
def test_export_bytes_are_stable_across_servers(client, serve):
    source = serve(SIMPLE_CSV)
    path = client.get("/convert", query_string={"source": source}).get_json()["endpoint"] + "/export"

    fresh = create_app().test_client()
    fresh.get("/convert", query_string={"source": source})

    assert client.get(path).get_data() == fresh.get(path).get_data()


# Phrase: "Re-uploading the same file bytes yields the same dataset id." (context: across server restarts)
def test_upload_id_depends_only_on_the_file_bytes():
    assert upload_id(SIMPLE_CSV.encode()) == upload_id(SIMPLE_CSV.encode())
    assert upload_id(SIMPLE_CSV.encode()) != upload_id(SIMPLE_CSV.encode() + b"x")


# Phrase: "spreadsheet columns preserve source order." (context: repeated ingestion of one workbook)
def test_repeated_workbook_uploads_produce_identical_payloads(uploaded):
    data = xlsx_bytes(SIMPLE_SHEET)
    first, second = uploaded(data, filename="b.xlsx"), uploaded(data, filename="b.xlsx")

    assert (first["columns"], first["rows"]) == (second["columns"], second["rows"])
