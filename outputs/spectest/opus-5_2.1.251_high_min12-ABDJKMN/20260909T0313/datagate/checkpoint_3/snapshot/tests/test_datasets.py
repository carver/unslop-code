"""Spec section: Dataset Query: `GET /datasets/<id>`."""

import pytest

SIMPLE = "name,age\nalice,30\nbob,41\n"


# Phrase: 'Success (`HTTP 200`): {"ok": true, "columns": [...], "rows": [...], "query_ms": 3.2}'
def test_dataset_success_body_shape(dataset):
    response = dataset("/shape.csv", SIMPLE)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert set(payload) >= {"ok", "columns", "rows", "query_ms"}
    assert isinstance(payload["columns"], list)
    assert isinstance(payload["rows"], list)
    assert all(isinstance(row, list) for row in payload["rows"])
    assert isinstance(payload["query_ms"], (int, float))


# Phrase: "The endpoint returns stored rows and columns, in source order."
def test_columns_and_rows_in_source_order(dataset):
    csv_text = "zeta,alpha,middle\n1,2,3\n4,5,6\n7,8,9\n"
    payload = dataset("/order.csv", csv_text).get_json()
    assert payload["columns"] == ["zeta", "alpha", "middle"]
    assert payload["rows"] == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


# Phrase: "The endpoint returns stored rows and columns, in source order."
# Context: row order matches the file, not any sort.
def test_row_order_is_source_order(dataset):
    csv_text = "n,label\n3,c\n1,a\n2,b\n"
    payload = dataset("/rowsort.csv", csv_text).get_json()
    assert payload["rows"] == [[3, "c"], [1, "a"], [2, "b"]]


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
def test_rows_capped_at_100(dataset):
    csv_text = "i,v\n" + "".join("{},{}\n".format(i, i * 2) for i in range(250))
    payload = dataset("/big.csv", csv_text).get_json()
    assert len(payload["rows"]) == 100
    assert payload["rows"][0] == [0, 0]
    assert payload["rows"][-1] == [99, 198]


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
def test_all_rows_when_fewer_than_100(dataset):
    csv_text = "i,v\n" + "".join("{},{}\n".format(i, i) for i in range(7))
    payload = dataset("/small.csv", csv_text).get_json()
    assert len(payload["rows"]) == 7


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
# Context: exactly 100 rows is not truncated.
def test_exactly_100_rows(dataset):
    csv_text = "i,v\n" + "".join("{},{}\n".format(i, i) for i in range(100))
    payload = dataset("/exact.csv", csv_text).get_json()
    assert len(payload["rows"]) == 100


# Phrase: "Type handling: Strings remain text."
def test_strings_remain_text(dataset):
    csv_text = "word,mixed,blank\nalice,a1,\nbob,2b,\n"
    payload = dataset("/strings.csv", csv_text).get_json()
    assert payload["rows"] == [["alice", "a1", ""], ["bob", "2b", ""]]
    for row in payload["rows"]:
        for value in row:
            assert isinstance(value, str)


# Phrase: "Type handling: Integers/decimals are JSON numbers."
def test_integers_are_json_numbers(dataset):
    payload = dataset("/ints.csv", "a,b,c\n0,42,-7\n").get_json()
    row = payload["rows"][0]
    assert row == [0, 42, -7]
    assert all(isinstance(value, int) and not isinstance(value, bool) for value in row)


# Phrase: "Type handling: Integers/decimals are JSON numbers."
def test_decimals_are_json_numbers(dataset):
    payload = dataset("/decimals.csv", "a,b,c\n3.2,-0.5,10.0\n").get_json()
    row = payload["rows"][0]
    assert row == [3.2, -0.5, 10.0]
    assert all(isinstance(value, float) for value in row)


# Phrase: "Type handling: Integers/decimals are JSON numbers."
# Context: raw JSON text must carry bare numbers, not quoted strings.
def test_numbers_are_unquoted_in_raw_json(dataset):
    response = dataset("/raw.csv", "a,b\n42,3.5\n")
    body = response.get_data(as_text=True).replace(" ", "")
    assert '"42"' not in body and '"3.5"' not in body
    assert "42" in body and "3.5" in body


# Phrase: "Time-like values (for example `08:30`, `9:15`, `12:00`) remain text."
@pytest.mark.parametrize("value", ["08:30", "9:15", "12:00", "00:00", "23:59"])
def test_time_like_values_remain_text(dataset, value):
    payload = dataset(
        "/time-{}.csv".format(value.replace(":", "")),
        "when,who\n{},alice\n".format(value),
    ).get_json()
    assert payload["rows"][0][0] == value
    assert isinstance(payload["rows"][0][0], str)


# Phrase: "Time-like values ... remain text."
# Context: several time-like shapes in one file, alongside real numbers.
def test_time_like_column_alongside_numbers(dataset):
    csv_text = "start,end,minutes\n08:30,9:15,45\n12:00,12:30,30\n"
    payload = dataset("/times.csv", csv_text).get_json()
    assert payload["rows"] == [["08:30", "9:15", 45], ["12:00", "12:30", 30]]


# Phrase: "Type handling" -- context: date-like values are not numbers either.
def test_date_like_values_remain_text(dataset):
    payload = dataset("/dates.csv", "d,n\n2024-01-31,5\n").get_json()
    assert payload["rows"][0] == ["2024-01-31", 5]


# Phrase: "If `<id>` is unknown, return `HTTP 404`."
def test_unknown_dataset_id_is_404(client):
    response = client.get("/datasets/does-not-exist")
    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str)


# Phrase: "If `<id>` is unknown, return `HTTP 404`."
# Context: an id that is plausibly shaped but never ingested.
def test_plausible_but_unknown_id_is_404(client):
    response = client.get("/datasets/" + "a" * 16)
    assert response.status_code == 404


# Phrase: '"query_ms": 3.2' -- present and numeric on every dataset response.
def test_query_ms_present_and_non_negative(dataset):
    payload = dataset("/qms.csv", SIMPLE).get_json()
    assert "query_ms" in payload
    assert isinstance(payload["query_ms"], (int, float))
    assert not isinstance(payload["query_ms"], bool)
    assert payload["query_ms"] >= 0
