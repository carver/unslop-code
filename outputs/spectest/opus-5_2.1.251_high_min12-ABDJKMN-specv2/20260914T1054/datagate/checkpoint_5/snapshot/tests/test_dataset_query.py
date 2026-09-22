"""Spec section: Dataset Query: `GET /datasets/<id>`."""
import pytest

CSV = "name,qty\nwidget,3\ngadget,4\n"


# Phrase: 'Success (`HTTP 200`): {"ok": true, "columns": [...], "rows": [...], "query_ms": 3.2}'
# Context: the full success envelope for a dataset query.
def test_success_envelope_keys(dataset):
    status, body = dataset(CSV)
    assert status == 200
    assert body["ok"] is True
    assert set(body) >= {"ok", "columns", "rows", "query_ms"}
    assert isinstance(body["columns"], list)
    assert isinstance(body["rows"], list)


# Phrase: "The endpoint returns stored rows and columns, in source order."
# Context: header cells become `columns`, left to right.
def test_columns_in_source_order(dataset):
    _, body = dataset("zeta,alpha,mid\n1,2,3\n")
    assert body["columns"] == ["zeta", "alpha", "mid"]


# Phrase: "The endpoint returns stored rows and columns, in source order."
# Context: data rows keep file order and per-row column order.
def test_rows_in_source_order(dataset):
    _, body = dataset("a,b\n1,2\n3,4\n5,6\n")
    assert body["rows"] == [[1, 2], [3, 4], [5, 6]]


# Phrase: "rows": [["<val1>", "<val2>", "..."], ["..."]]
# Context: each row is a list positionally aligned with `columns`.
def test_rows_are_lists_aligned_with_columns(dataset):
    _, body = dataset(CSV)
    assert all(isinstance(r, list) for r in body["rows"])
    assert all(len(r) == len(body["columns"]) for r in body["rows"])


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
# Context: fewer than 100 rows -> all of them.
def test_returns_all_rows_when_fewer_than_limit(dataset):
    body_csv = "n\n" + "".join("%d\n" % i for i in range(7))
    _, body = dataset(body_csv)
    assert len(body["rows"]) == 7


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
# Context: exactly 100 rows -> all 100.
def test_returns_exactly_100_when_100_rows(dataset):
    body_csv = "n\n" + "".join("%d\n" % i for i in range(100))
    _, body = dataset(body_csv)
    assert len(body["rows"]) == 100


# Phrase: "`rows` returns at most 100 items"
# Context: more than 100 rows -> truncated to the first 100, in source order.
def test_caps_rows_at_100(dataset):
    body_csv = "n\n" + "".join("%d\n" % i for i in range(250))
    _, body = dataset(body_csv)
    assert len(body["rows"]) == 100
    assert body["rows"][0] == [0]
    assert body["rows"][-1] == [99]


# Phrase: '"query_ms": 3.2'
# Context: present, numeric, non-negative (Determinism restates this).
def test_query_ms_is_non_negative_number(dataset):
    _, body = dataset(CSV)
    assert isinstance(body["query_ms"], (int, float))
    assert not isinstance(body["query_ms"], bool)
    assert body["query_ms"] >= 0


# ----------------------------------------------------------- type handling ---

# Phrase: "Strings remain text."
# Context: non-numeric cells round-trip as their source text.
def test_strings_remain_text(dataset):
    _, body = dataset("a,b\nwidget,hello world\n")
    assert body["rows"][0] == ["widget", "hello world"]


# Phrase: "Integers/decimals are JSON numbers."
# Context: integer cells deserialize as ints, not strings.
def test_integers_are_numbers(dataset):
    _, body = dataset("a,b,c\n3,-7,0\n")
    assert body["rows"][0] == [3, -7, 0]
    assert all(isinstance(v, int) for v in body["rows"][0])


# Phrase: "Integers/decimals are JSON numbers."
# Context: decimal cells deserialize as floats.
def test_decimals_are_numbers(dataset):
    _, body = dataset("a,b,c\n3.5,-0.25,10.0\n")
    row = body["rows"][0]
    assert row == [3.5, -0.25, 10.0]
    assert all(isinstance(v, float) for v in row)


# Phrase: "Time-like values (for example `08:30`, `9:15`, `12:00`) remain text."
# Context: the spec's own examples, verbatim.
def test_time_like_values_remain_text(dataset):
    _, body = dataset("start,mid,end\n08:30,9:15,12:00\n")
    assert body["rows"][0] == ["08:30", "9:15", "12:00"]


# Phrase: "Time-like values ... remain text."  (see AMBIGUITIES T5)
# Context: no date/datetime coercion either.
@pytest.mark.parametrize("value", ["2024-01-05", "2024-01-05T08:30:00Z", "1:2:3", "23:59:59"])
def test_datetime_like_values_remain_text(dataset, value):
    _, body = dataset("when\n%s\n" % value)
    assert body["rows"][0] == [value]


# Phrase: "Strings remain text." / "Integers/decimals are JSON numbers."  (see T3)
# Context: number-adjacent strings that are not plain numeric literals stay text.
@pytest.mark.parametrize("value", ["$5", "50%", "1,234", "12abc", "NaN", "Infinity", "1_000", "0x1f", "--3"])
def test_non_numeric_lookalikes_remain_text(dataset, value):
    _, body = dataset('v\n"%s"\n' % value)
    assert body["rows"][0] == [value]


# Phrase: "Integers/decimals are JSON numbers."  (see AMBIGUITIES T3)
# Context: chosen reading - a leading-zero integer literal is still a number.
def test_leading_zero_integers_are_numbers(dataset):
    _, body = dataset("code\n007\n")
    assert body["rows"][0] == [7]


# Phrase: "Integers/decimals are JSON numbers."
# Context: surrounding whitespace does not defeat numeric detection.
def test_whitespace_padded_numbers(dataset):
    _, body = dataset('a,b\n" 42 ","  x "\n')
    assert body["rows"][0] == [42, "x"]


# Phrase: "Strings remain text."  (see AMBIGUITIES T4)
# Context: chosen reading - an empty cell is the empty string.
def test_empty_cells_are_empty_strings(dataset):
    _, body = dataset("a,b\n,\n")
    assert body["rows"][0] == ["", ""]


# Phrase: type handling must survive JSON serialisation
# Context: numbers must not be emitted as JSON strings.
def test_numbers_serialize_as_json_numbers(client, convert, origin):
    url = origin.add("a\n5\n")
    _, payload = convert(source=url)
    raw = client.get(payload["endpoint"]).get_data(as_text=True)
    assert '"5"' not in raw
    assert "5" in raw


# ------------------------------------------------------------- unknown id ---

# Phrase: "If `<id>` is unknown, return `HTTP 404`."
# Context: an id that was never ingested.
def test_unknown_id_is_404(client):
    resp = client.get("/datasets/deadbeefdeadbeef")
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


# Phrase: "If `<id>` is unknown, return `HTTP 404`."
# Context: odd-shaped ids are still just unknown ids, and still JSON.
@pytest.mark.parametrize("bad", ["x", "0", "%20", "a-b_c.d"])
def test_unknown_id_variants_are_404_json(client, bad):
    resp = client.get("/datasets/%s" % bad)
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


# Phrase: "Default row limit is 100."  (see AMBIGUITIES T6, resolved by the
#          Pagination section: the override parameter is `_size`, not `limit`.)
# Context: the explicit override is `_size`.
def test_explicit_size_overrides_default(dataset):
    body_csv = "n\n" + "".join("%d\n" % i for i in range(250))
    _, body = dataset(body_csv, query_string={"_size": 5})
    assert len(body["rows"]) == 5
    assert body["rows"] == [[0], [1], [2], [3], [4]]


# Phrase: "Default row limit is 100." / "`_size` ... If it exceeds available rows,
#          return all."
# Context: a size above the row count returns all rows; a bad size is a 400.
def test_size_edge_cases(dataset):
    body_csv = "n\n" + "".join("%d\n" % i for i in range(150))
    _, body = dataset(body_csv, query_string={"_size": 1000})
    assert len(body["rows"]) == 150
    status, err = dataset(body_csv, query_string={"_size": "abc"})
    assert status == 400
    assert err["ok"] is False


# Phrase: "`_size` (positive integer, default `100`) limits returned rows."
# Context: chosen reading - `limit` is not a control parameter (see AMBIGUITIES T6);
#          it is an unknown query parameter and is ignored.
def test_limit_is_not_a_control_parameter(dataset):
    body_csv = "n\n" + "".join("%d\n" % i for i in range(150))
    status, body = dataset(body_csv, query_string={"limit": 5})
    assert status == 200
    assert len(body["rows"]) == 100
