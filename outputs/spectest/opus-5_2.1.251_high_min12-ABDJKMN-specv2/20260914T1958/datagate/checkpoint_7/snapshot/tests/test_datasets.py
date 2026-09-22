"""Spec section: Dataset Query: `GET /datasets/<id>`."""
from conftest import convert_ok, dataset

SIMPLE = "name,age\nAlice,30\nBob,41\n"


# ---------------------------------------------------------------------------
# Phrase: 'Success (`HTTP 200`): {"ok": true, "columns": [...], "rows": [...],
#          "query_ms": 3.2}'
# Context: dataset query success envelope.
# ---------------------------------------------------------------------------
def test_success_payload_shape(gate, origin):
    url = origin.add("/ds-shape.csv", SIMPLE)
    endpoint = convert_ok(gate, url)
    resp = gate.get(endpoint)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert set(body) >= {"ok", "columns", "rows", "query_ms"}
    assert isinstance(body["columns"], list)
    assert isinstance(body["rows"], list)
    assert all(isinstance(row, list) for row in body["rows"])
    assert isinstance(body["query_ms"], (int, float))


# ---------------------------------------------------------------------------
# Phrase: "The endpoint returns stored rows and columns, in source order."
# Context: dataset query content.
# ---------------------------------------------------------------------------
def test_returns_stored_rows_and_columns_in_source_order(gate, origin):
    url = origin.add("/ds-order.csv", "zeta,alpha,mid\n1,2,3\n4,5,6\n")
    body = dataset(gate, url)
    assert body["columns"] == ["zeta", "alpha", "mid"]
    assert body["rows"] == [[1, 2, 3], [4, 5, 6]]


# ---------------------------------------------------------------------------
# Phrase: "`rows` returns at most 100 items"
# Context: dataset query row cap.
# ---------------------------------------------------------------------------
def test_rows_capped_at_100(gate, origin):
    csv_text = "n\n" + "".join(f"{i}\n" for i in range(250))
    url = origin.add("/ds-250.csv", csv_text)
    body = dataset(gate, url)
    assert len(body["rows"]) == 100
    assert body["rows"][0] == [0]
    assert body["rows"][99] == [99]


# ---------------------------------------------------------------------------
# Phrase: "(or all rows if fewer)"
# Context: dataset query row cap with a small file.
# ---------------------------------------------------------------------------
def test_all_rows_when_fewer_than_100(gate, origin):
    url = origin.add("/ds-few.csv", SIMPLE)
    body = dataset(gate, url)
    assert body["rows"] == [["Alice", 30], ["Bob", 41]]


# ---------------------------------------------------------------------------
# Phrase: "(or all rows if fewer)"
# Context: exactly 100 data rows is not truncated.
# ---------------------------------------------------------------------------
def test_exactly_100_rows_returned_whole(gate, origin):
    csv_text = "n\n" + "".join(f"{i}\n" for i in range(100))
    url = origin.add("/ds-100.csv", csv_text)
    assert len(dataset(gate, url)["rows"]) == 100


# ---------------------------------------------------------------------------
# Phrase: "Type handling: - Strings remain text."
# Context: dataset query type inference.
# ---------------------------------------------------------------------------
def test_strings_remain_text(gate, origin):
    url = origin.add("/ds-strings.csv", "a,b,c\nAlice,N/A,x1\n")
    assert dataset(gate, url)["rows"] == [["Alice", "N/A", "x1"]]


# ---------------------------------------------------------------------------
# Phrase: "- Integers/decimals are JSON numbers."
# Context: dataset query type inference.
# ---------------------------------------------------------------------------
def test_integers_and_decimals_are_json_numbers(gate, origin):
    url = origin.add("/ds-numbers.csv", "i,neg,d,negd\n42,-7,3.5,-0.25\n")
    row = dataset(gate, url)["rows"][0]
    assert row == [42, -7, 3.5, -0.25]
    assert isinstance(row[0], int) and not isinstance(row[0], bool)
    assert isinstance(row[2], float)


# ---------------------------------------------------------------------------
# Phrase: "- Integers/decimals are JSON numbers."
# Context: raw JSON text must carry bare numbers, not quoted strings.
# ---------------------------------------------------------------------------
def test_numbers_are_unquoted_in_raw_json(gate, origin):
    url = origin.add("/ds-rawjson.csv", "n\n42\n")
    endpoint = convert_ok(gate, url)
    text = gate.get(endpoint).text.replace(" ", "")
    assert "[[42]]" in text


# ---------------------------------------------------------------------------
# Phrase: "- Time-like values (for example `08:30`, `9:15`, `12:00`) remain text."
# Context: dataset query type inference.
# ---------------------------------------------------------------------------
def test_time_like_values_remain_text(gate, origin):
    url = origin.add("/ds-times.csv", "a,b,c\n08:30,9:15,12:00\n")
    row = dataset(gate, url)["rows"][0]
    assert row == ["08:30", "9:15", "12:00"]
    assert all(isinstance(v, str) for v in row)


# ---------------------------------------------------------------------------
# Phrase: "- Time-like values ... remain text." (leading zero preserved)
# Context: `08:30` must not be reduced to `8:30` or split.
# ---------------------------------------------------------------------------
def test_time_like_value_text_is_verbatim(gate, origin):
    url = origin.add("/ds-time-verbatim.csv", "start\n08:30:05\n")
    assert dataset(gate, url)["rows"] == [["08:30:05"]]


# ---------------------------------------------------------------------------
# Phrase: "columns": ["<col1>", "<col2>", "..."]
# Context: header cells are always column names, never inferred numbers.
# ---------------------------------------------------------------------------
def test_columns_are_always_strings(gate, origin):
    url = origin.add("/ds-numeric-header.csv", "1,2\n3,4\n")
    body = dataset(gate, url)
    assert body["columns"] == ["1", "2"]
    assert body["rows"] == [[3, 4]]


# ---------------------------------------------------------------------------
# Phrase: "If `<id>` is unknown, return `HTTP 404`."
# Context: dataset query error.
# ---------------------------------------------------------------------------
def test_unknown_id_is_404(gate):
    resp = gate.get("/datasets/0123456789abcdef")
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# ---------------------------------------------------------------------------
# Phrase: '"query_ms": 3.2'
# Context: dataset query timing field is present and non-negative.
# ---------------------------------------------------------------------------
def test_query_ms_present_and_non_negative(gate, origin):
    url = origin.add("/ds-qms.csv", SIMPLE)
    body = dataset(gate, url)
    assert body["query_ms"] >= 0


# ---------------------------------------------------------------------------
# Phrase: "The endpoint returns stored rows"
# Context: a dataset stays queryable across repeated reads.
# ---------------------------------------------------------------------------
def test_dataset_is_repeatably_queryable(gate, origin):
    url = origin.add("/ds-repeat.csv", SIMPLE)
    endpoint = convert_ok(gate, url)
    first = gate.get(endpoint).json()
    second = gate.get(endpoint).json()
    assert first["columns"] == second["columns"]
    assert first["rows"] == second["rows"]


# ---------------------------------------------------------------------------
# Phrase: "Default row limit is 100."
# Context: the override is `_size`, per the controls spec; AMBIGUITIES T3 is
#          now resolved and the earlier bare `limit` guess is retired.
# ---------------------------------------------------------------------------
def test_size_parameter_overrides_the_default(gate, origin):
    csv_text = "n\n" + "".join(f"{i}\n" for i in range(250))
    url = origin.add("/ds-limit.csv", csv_text)
    endpoint = convert_ok(gate, url)
    assert len(gate.get(endpoint, params={"_size": 5}).json()["rows"]) == 5
    assert len(gate.get(endpoint).json()["rows"]) == 100
