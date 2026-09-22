"""Spec section: Dataset Query: `GET /datasets/<id>`."""

import pytest

CSV = "name,age,start\nada,36,08:30\ngrace,45,9:15\n"


# Phrase: "Success (`HTTP 200`): {"ok": true, "columns": [...], "rows": [...], "query_ms": 3.2}"
def test_dataset_response_shape(converted):
    response = converted(CSV)

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert set(body) == {"ok", "columns", "rows", "query_ms"}
    assert body["columns"] == ["name", "age", "start"]
    assert isinstance(body["rows"], list)


# Phrase: "The endpoint returns stored rows and columns, in source order."
def test_rows_and_columns_keep_source_order(converted):
    body = converted("b,a,c\n2,1,3\n5,4,6\n").get_json()

    assert body["columns"] == ["b", "a", "c"]
    assert body["rows"] == [[2, 1, 3], [5, 4, 6]]


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
def test_row_cap_is_100(converted):
    csv = "n\tv\n" + "".join(f"row{i}\t{i}\n" for i in range(250))

    body = converted(csv).get_json()

    assert len(body["rows"]) == 100
    assert body["rows"][0] == ["row0", 0]
    assert body["rows"][99] == ["row99", 99]


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
def test_all_rows_returned_when_fewer_than_100(converted):
    body = converted(CSV).get_json()

    assert len(body["rows"]) == 2


# Phrase: "Strings remain text."
def test_strings_remain_text(converted):
    body = converted("name,note\nada,hello world\n").get_json()

    assert body["rows"] == [["ada", "hello world"]]


# Phrase: "Integers/decimals are JSON numbers."
def test_integers_and_decimals_are_numbers(converted):
    body = converted("i,d,neg,sci\n42,3.5,-7,1e3\n").get_json()

    row = body["rows"][0]
    assert row == [42, 3.5, -7, 1000.0]
    assert isinstance(row[0], int) and not isinstance(row[0], bool)
    assert isinstance(row[1], float)


# Phrase: "Time-like values (for example `08:30`, `9:15`, `12:00`) remain text."
def test_time_like_values_remain_text(converted):
    body = converted("a,b,c\n08:30,9:15,12:00\n").get_json()

    assert body["rows"] == [["08:30", "9:15", "12:00"]]


# Phrase: "Strings remain text." -- context: values that merely look numeric (AMBIGUITIES T10).
def test_near_numeric_values_remain_text(converted):
    body = converted("date,money,grouped,pct\n2026-09-19,$5,\"1,234\",20%\n").get_json()

    assert body["rows"] == [["2026-09-19", "$5", "1,234", "20%"]]


# Phrase: "Type inference is deterministic." -- context: non-JSON floats stay text (AMBIGUITIES T2).
def test_nan_and_infinity_remain_text(converted):
    body = converted("a;b;c\nnan;inf;-Infinity\n").get_json()

    assert body["rows"] == [["nan", "inf", "-Infinity"]]


# Phrase: "Integers/decimals are JSON numbers." -- context: blank cells stay text.
def test_empty_cells_remain_empty_text(converted):
    body = converted("a,b\n,5\n").get_json()

    assert body["rows"] == [["", 5]]


# Phrase: "`query_ms` is present and non-negative."
def test_query_ms_present_and_non_negative(converted):
    body = converted(CSV).get_json()

    assert isinstance(body["query_ms"], (int, float))
    assert body["query_ms"] >= 0


# Phrase: "If `<id>` is unknown, return `HTTP 404`."
def test_unknown_dataset_id_is_404(client):
    response = client.get("/datasets/deadbeefdeadbeef")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "Default row limit is 100." -- context: optional override (AMBIGUITIES T7).
@pytest.mark.parametrize("query,expected", [("?limit=1", 1), ("?limit=abc", 2), ("", 2)])
def test_limit_override(converted, query, expected):
    body = converted(CSV, query=query).get_json()

    assert len(body["rows"]) == expected
