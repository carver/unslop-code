"""Spec section: Dataset Query: `GET /datasets/<id>`."""

from tests.conftest import SIMPLE_CSV


# Phrase: "Success (HTTP 200): {"ok": true, "columns": [...], "rows": [...], "query_ms": 3.2}"
def test_dataset_payload_shape(dataset):
    payload = dataset(SIMPLE_CSV)
    assert payload["ok"] is True
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["ada", 36], ["grace", 45]]
    assert isinstance(payload["query_ms"], float)
    assert set(payload) == {"ok", "columns", "rows", "query_ms"}


# Phrase: "The endpoint returns stored rows and columns, in source order."
def test_rows_and_columns_keep_source_order(dataset):
    payload = dataset("z,a,m\n3,1,2\n6,4,5\n")
    assert payload["columns"] == ["z", "a", "m"]
    assert payload["rows"] == [[3, 1, 2], [6, 4, 5]]


# Phrase: "The endpoint returns stored rows ... in source order." - row order too.
def test_row_order_matches_the_source(dataset):
    body = "n\ttag\n" + "".join(f"{i}\trow{i}\n" for i in range(20))
    assert [row[1] for row in dataset(body)["rows"]] == [f"row{i}" for i in range(20)]


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
def test_row_limit_caps_at_100(dataset):
    body = "n,tag\n" + "".join(f"{i},row{i}\n" for i in range(250))
    payload = dataset(body)
    assert len(payload["rows"]) == 100
    assert payload["rows"][0] == [0, "row0"] and payload["rows"][-1] == [99, "row99"]


# Phrase: "(or all rows if fewer)"
def test_fewer_rows_are_all_returned(dataset):
    body = "n,tag\n" + "".join(f"{i},row{i}\n" for i in range(7))
    assert len(dataset(body)["rows"]) == 7


# Phrase: "`rows` returns at most 100 items" - the column list is never truncated.
def test_columns_are_not_truncated(dataset):
    header = ",".join(f"c{i}" for i in range(120))
    values = ",".join(str(i) for i in range(120))
    assert len(dataset(f"{header}\n{values}\n")["columns"]) == 120


# Phrase: "If `<id>` is unknown, return `HTTP 404`."
def test_unknown_dataset_id_is_404(client):
    response = client.get("/datasets/deadbeefdeadbeef")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "query_ms": 3.2 - present and non-negative on every query.
def test_query_ms_is_non_negative(dataset):
    assert dataset(SIMPLE_CSV)["query_ms"] >= 0


# Phrase: "Default row limit is 100." - an explicit smaller limit is honoured (T11).
def test_explicit_limit_overrides_the_default(dataset):
    body = "n,tag\n" + "".join(f"{i},row{i}\n" for i in range(50))
    assert len(dataset(body, dataset_query="?limit=5")["rows"]) == 5


# Phrase: "Default row limit is 100." - a nonsensical limit is a client error (T11).
def test_invalid_limit_is_400(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    for limit in ["zero", "-3", "0"]:
        response = client.get(f"{endpoint}?limit={limit}")
        assert response.status_code == 400, limit
        assert response.get_json()["ok"] is False
