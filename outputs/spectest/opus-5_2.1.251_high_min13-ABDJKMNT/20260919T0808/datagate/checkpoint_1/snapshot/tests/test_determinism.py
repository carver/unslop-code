"""Spec section: Determinism."""

from datagate_core.store import dataset_id
from tests.conftest import SIMPLE_CSV


# Phrase: "Same `source` URL always maps to the same dataset id."
def test_dataset_id_is_a_pure_function_of_the_source(origin):
    url = origin.url_for("/anything.csv")
    assert dataset_id(url) == dataset_id(url)
    assert dataset_id(url) != dataset_id(url + "?v=2")


# Phrase: "Same `source` URL always maps to the same dataset id." - across app instances.
def test_dataset_id_is_stable_across_app_instances(client, origin):
    from datagate_core.server import create_app

    url = origin.serve("/determinism.csv", SIMPLE_CSV)
    first = client.get(f"/convert?source={url}").get_json()["endpoint"]
    second = create_app().test_client().get(f"/convert?source={url}").get_json()["endpoint"]
    assert first == second == f"/datasets/{dataset_id(url)}"


# Phrase: "`columns` and each row follow source column order."
def test_column_order_is_preserved_for_many_columns(dataset):
    header = ",".join(f"col{i}" for i in range(12))
    row = ",".join(str(i) for i in range(12))
    payload = dataset(f"{header}\n{row}\n")
    assert payload["columns"] == [f"col{i}" for i in range(12)]
    assert payload["rows"] == [list(range(12))]


# Phrase: "`query_ms` is present and non-negative."
def test_query_ms_present_and_non_negative_on_repeat_queries(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    for _ in range(3):
        payload = client.get(endpoint).get_json()
        assert "query_ms" in payload and payload["query_ms"] >= 0


# Phrase: "Type inference is deterministic." / "No dependence on clock/locale/
# timezone beyond `query_ms`."
def test_repeated_queries_return_identical_payloads(client, convert):
    endpoint = convert("a,b,c\n1,08:30,x\n2.5,9:15,y\n").get_json()["endpoint"]
    payloads = [client.get(endpoint).get_json() for _ in range(3)]
    stripped = [{k: v for k, v in payload.items() if k != "query_ms"} for payload in payloads]
    assert stripped[0] == stripped[1] == stripped[2]


# Phrase: "Default row limit is 100." - the same dataset re-converted is unchanged.
def test_reconversion_returns_the_same_dataset(client, origin):
    url = origin.serve("/repeat.csv", "a,b\n1,2\n3,4\n")
    first = client.get(f"/convert?source={url}").get_json()["endpoint"]
    second = client.get(f"/convert?source={url}").get_json()["endpoint"]
    assert first == second
    assert client.get(first).get_json()["rows"] == [[1, 2], [3, 4]]
