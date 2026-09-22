"""Row count and pagination controls: `total`, `_size` and `_offset`."""

NUMBERED = "n,label\n" + "".join(f"{i},row{i}\n" for i in range(250))
SMALL = "n,label\n" + "".join(f"{i},row{i}\n" for i in range(7))


# Spec: "Responses include integer `total` for the row count before pagination."
# Context: an unpaginated read of a dataset smaller than the default window.
def test_total_is_the_row_count(reader):
    payload = reader(SMALL)().get_json()
    assert payload["total"] == 7
    assert isinstance(payload["total"], int)


# Spec: "integer `total` for the row count before pagination"
# Context: `total` counts every stored row, not the rows the window returns.
def test_total_ignores_pagination(reader):
    payload = reader(NUMBERED)({"_size": "5", "_offset": "10"}).get_json()
    assert payload["total"] == 250
    assert len(payload["rows"]) == 5


# Spec: "`_size` (positive integer, default `100`) limits returned rows."
# Context: an explicit `_size` narrows the window.
def test_size_limits_returned_rows(reader):
    payload = reader(NUMBERED)({"_size": "3"}).get_json()
    assert payload["rows"] == [[0, "row0"], [1, "row1"], [2, "row2"]]


# Spec: "`_size` (positive integer, default `100`)"
# Context: no `_size` at all falls back to 100 rows.
def test_size_defaults_to_100(reader):
    assert len(reader(NUMBERED)().get_json()["rows"]) == 100


# Spec: "If it exceeds available rows, return all."
# Context: a `_size` larger than the stored row count.
def test_size_beyond_available_rows_returns_all(reader):
    payload = reader(SMALL)({"_size": "500"}).get_json()
    assert len(payload["rows"]) == 7
    assert payload["total"] == 7


# Spec: "`_offset` (non-negative integer, default `0`) skips that many rows
# before returning."
# Context: an offset inside the dataset.
def test_offset_skips_rows(reader):
    payload = reader(NUMBERED)({"_offset": "10", "_size": "2"}).get_json()
    assert payload["rows"] == [[10, "row10"], [11, "row11"]]


# Spec: "`_offset` (non-negative integer, default `0`)"
# Context: the default offset starts at the first row; `_offset=0` is the same.
def test_offset_defaults_to_zero(reader):
    read = reader(NUMBERED)
    assert read({"_size": "1"}).get_json()["rows"] == [[0, "row0"]]
    assert read({"_size": "1", "_offset": "0"}).get_json()["rows"] == [[0, "row0"]]


# Spec: "`_offset` ... skips that many rows before returning."
# Context: an offset past the end leaves nothing to return.
def test_offset_past_the_end_returns_no_rows(reader):
    payload = reader(SMALL)({"_offset": "50"}).get_json()
    assert payload["rows"] == []
    assert payload["total"] == 7


# Spec: "`_size` ... limits returned rows." / "`_offset` ... skips that many rows"
# Context: the two combine into a window, and a short tail is not padded.
def test_size_and_offset_window_the_tail(reader):
    payload = reader(SMALL)({"_offset": "5", "_size": "10"}).get_json()
    assert payload["rows"] == [[5, "row5"], [6, "row6"]]


# Spec: "Invalid `_size`/`_offset` -> `HTTP 400`."
# Context: `_size` must be a positive integer (AMBIGUITIES T14).
def test_invalid_size_is_400(reader):
    read = reader(SMALL)
    for bad in ("0", "-1", "abc", "", "1.5", "1e3", "٣"):
        response = read({"_size": bad})
        assert response.status_code == 400, bad
        body = response.get_json()
        assert body["ok"] is False
        assert isinstance(body["error"], str) and body["error"]


# Spec: "Invalid `_size`/`_offset` -> `HTTP 400`."
# Context: `_offset` must be a non-negative integer, so `0` is accepted and
# negatives are not (AMBIGUITIES T14).
def test_invalid_offset_is_400(reader):
    read = reader(SMALL)
    for bad in ("-1", "abc", "", "2.0", "0x1"):
        assert read({"_offset": bad}).status_code == 400, bad
    assert read({"_offset": "0"}).status_code == 200
