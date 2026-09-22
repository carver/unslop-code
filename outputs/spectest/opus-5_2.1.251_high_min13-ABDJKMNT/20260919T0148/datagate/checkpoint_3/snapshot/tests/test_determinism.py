"""Spec section: Determinism."""

from datagate_core.store import dataset_id

CSV = "name,age\nada,36\ngrace,45\n"


# Phrase: "Same `source` URL always maps to the same dataset id."
def test_dataset_id_is_a_pure_function_of_the_url():
    url = "http://example.com/data.csv"

    assert dataset_id(url) == dataset_id(url)
    assert dataset_id(url) != dataset_id(url + "?v=2")


# Phrase: "Same `source` URL always maps to the same dataset id."
# Context: the id is stable across server instances (AMBIGUITIES T1).
def test_endpoint_is_stable_across_app_instances(origin):
    from datagate_core.server import create_app

    source = origin.serve("/data.csv", CSV)
    endpoints = []
    for _ in range(2):
        client = create_app().test_client()
        endpoints.append(client.get("/convert", query_string={"source": source}).get_json())

    assert endpoints[0]["endpoint"] == endpoints[1]["endpoint"]


# Phrase: "Type inference is deterministic."
def test_repeated_queries_return_identical_payloads(converted):
    first = converted(CSV).get_json()
    second = converted(CSV).get_json()

    assert first["columns"] == second["columns"]
    assert first["rows"] == second["rows"]


# Phrase: "No dependence on clock/locale/timezone beyond `query_ms`."
def test_payload_is_unchanged_by_timezone(converted, monkeypatch):
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    baseline = converted(CSV).get_json()["rows"]

    monkeypatch.setenv("TZ", "UTC")

    assert converted(CSV).get_json()["rows"] == baseline


# Phrase: "`columns` and each row follow source column order."
def test_column_order_survives_the_round_trip(converted):
    body = converted("z,y,x\n1,2,3\n").get_json()

    assert body["columns"] == ["z", "y", "x"]
    assert body["rows"] == [[1, 2, 3]]
