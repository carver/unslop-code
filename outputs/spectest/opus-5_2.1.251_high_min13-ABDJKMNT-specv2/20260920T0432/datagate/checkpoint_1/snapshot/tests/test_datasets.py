"""Dataset query endpoint: GET /datasets/<id>."""


# Spec: "Success (HTTP 200): {"ok": true, "columns": [...], "rows": [[...]], "query_ms": 3.2}"
# Context: reading back a converted dataset.
def test_success_payload_shape(dataset):
    payload = dataset("name,age\nada,36\ngrace,45\n")
    assert payload["ok"] is True
    assert set(payload) == {"ok", "columns", "rows", "query_ms"}
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"] == [["ada", 36], ["grace", 45]]


# Spec: "The endpoint returns stored rows and columns, in source order."
# Context: column order follows the header, not alphabetical or any other order.
def test_columns_and_rows_keep_source_order(dataset):
    payload = dataset("zeta,alpha,mid\n3,1,2\n6,4,5\n")
    assert payload["columns"] == ["zeta", "alpha", "mid"]
    assert payload["rows"] == [[3, 1, 2], [6, 4, 5]]


# Spec: "`rows` returns at most 100 items (or all rows if fewer)."
# Context: a source with more than 100 data rows.
def test_rows_capped_at_100(dataset):
    body = "n\tlabel\n" + "".join(f"{i}\trow{i}\n" for i in range(250))
    payload = dataset(body)
    assert len(payload["rows"]) == 100
    assert payload["rows"][0] == [0, "row0"]
    assert payload["rows"][-1] == [99, "row99"]


# Spec: "`rows` returns at most 100 items (or all rows if fewer)."
# Context: a source with fewer than 100 data rows returns all of them.
def test_all_rows_when_fewer_than_limit(dataset):
    body = "n;label\n" + "".join(f"{i};x\n" for i in range(7))
    assert len(dataset(body)["rows"]) == 7


# Spec: "Default row limit is 100." (AMBIGUITIES T5)
# Context: an explicit `limit` narrows the window; a missing one keeps 100.
def test_explicit_limit_overrides_default(dataset):
    body = "n,label\n" + "".join(f"{i},row{i}\n" for i in range(150))
    assert len(dataset(body, query={"limit": "5"})["rows"]) == 5
    assert len(dataset(body, query={"limit": "120"})["rows"]) == 120
    assert len(dataset(body)["rows"]) == 100


# Spec: "Default row limit is 100." (AMBIGUITIES T5)
# Context: an unusable `limit` falls back to the default rather than erroring.
def test_unusable_limit_falls_back_to_default(dataset):
    body = "n,label\n" + "".join(f"{i},row{i}\n" for i in range(150))
    for bad in ("abc", "-3", "0", ""):
        assert len(dataset(body, query={"limit": bad})["rows"]) == 100, bad


# Spec: "Strings remain text."
# Context: non-numeric cells are returned as JSON strings.
def test_strings_remain_text(dataset):
    payload = dataset("a,b\nada,x1\n")
    assert payload["rows"] == [["ada", "x1"]]


# Spec: "Integers/decimals are JSON numbers."
# Context: integer and decimal spellings, including signs and exponents.
def test_integers_and_decimals_are_numbers(dataset):
    payload = dataset("i,neg,dec,signed,exp\n42,-7,3.14,+5,1e3\n")
    assert payload["rows"] == [[42, -7, 3.14, 5, 1000.0]]
    assert all(isinstance(v, (int, float)) for v in payload["rows"][0])


# Spec: "Time-like values (for example `08:30`, `9:15`, `12:00`) remain text."
# Context: the three examples given by the spec.
def test_time_like_values_remain_text(dataset):
    payload = dataset("a,b,c\n08:30,9:15,12:00\n")
    assert payload["rows"] == [["08:30", "9:15", "12:00"]]


# Spec: "Strings remain text." / "Integers/decimals are JSON numbers."
# Context: near-numeric spellings that are not plain integers or decimals
# (AMBIGUITIES T4).
def test_non_numeric_lookalikes_remain_text(dataset):
    payload = dataset("a,b,c,d,e\n1_000,nan,inf,2024-01-05,$3\n")
    assert payload["rows"] == [["1_000", "nan", "inf", "2024-01-05", "$3"]]


# Spec: "If `<id>` is unknown, return HTTP 404."
# Context: an id that was never produced by /convert.
def test_unknown_dataset_id_is_404(client):
    response = client.get("/datasets/deadbeefdeadbeef")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Spec: "query_ms": 3.2 / "query_ms is present and non-negative."
# Context: every successful dataset read reports its own timing.
def test_query_ms_is_present_and_non_negative(dataset):
    payload = dataset("a,b\n1,2\n")
    assert isinstance(payload["query_ms"], (int, float))
    assert payload["query_ms"] >= 0
