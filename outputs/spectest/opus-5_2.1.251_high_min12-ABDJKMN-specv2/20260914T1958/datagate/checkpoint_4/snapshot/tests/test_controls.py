"""Spec section: Pagination, Sorting, and Response Controls.

Every test is labelled with the minimal spec phrase it exercises.
"""
import pytest

from conftest import convert_ok

SIMPLE = "name,age\nAlice,30\nBob,41\n"

# 5 rows, ties in `k`, so stability and ordering are both observable.
TIES = "k,v\nb,1\na,2\na,3\na,4\nb,5\n"

# 250 numbered rows for pagination arithmetic.
BIG = "n\n" + "".join(f"{i}\n" for i in range(250))


def endpoint_for(gate, origin, path, body):
    """Register a CSV on the fake origin, convert it, return its endpoint."""
    return convert_ok(gate, origin.add(path, body))


@pytest.fixture(scope="module")
def simple_ep(gate, origin):
    return endpoint_for(gate, origin, "/ctl-simple.csv", SIMPLE)


@pytest.fixture(scope="module")
def ties_ep(gate, origin):
    return endpoint_for(gate, origin, "/ctl-ties.csv", TIES)


@pytest.fixture(scope="module")
def big_ep(gate, origin):
    return endpoint_for(gate, origin, "/ctl-big.csv", BIG)


def ok(gate, endpoint, **params):
    resp = gate.get(endpoint, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def bad(gate, endpoint, query):
    """Send a raw query string (so repeats survive) and require a 400 envelope."""
    resp = gate.get(f"{endpoint}?{query}")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]
    return body


# ---------------------------------------------------------------------------
# Phrase: "`GET /datasets/<id>` accepts control parameters for pagination,
#          sorting, and shape."
# Context: section preamble -- the control names are accepted together.
# ---------------------------------------------------------------------------
def test_control_parameters_are_accepted_together(gate, ties_ep):
    body = ok(gate, ties_ep, _size=2, _offset=1, _sort="k", _shape="objects")
    assert body["ok"] is True
    assert len(body["rows"]) == 2


# ---------------------------------------------------------------------------
# Phrase: "Responses include integer `total` for the row count before
#          pagination."
# Context: `total` presence and type.
# ---------------------------------------------------------------------------
def test_total_is_an_integer(gate, simple_ep):
    body = ok(gate, simple_ep)
    assert body["total"] == 2
    assert isinstance(body["total"], int) and not isinstance(body["total"], bool)


# ---------------------------------------------------------------------------
# Phrase: "... for the row count before pagination."
# Context: `total` ignores `_size`/`_offset`.
# ---------------------------------------------------------------------------
def test_total_is_unaffected_by_pagination(gate, big_ep):
    body = ok(gate, big_ep, _size=5, _offset=10)
    assert body["total"] == 250
    assert len(body["rows"]) == 5


# ---------------------------------------------------------------------------
# Phrase: "... the row count before pagination."
# Context: `total` counts data rows only, never the header.
# ---------------------------------------------------------------------------
def test_total_excludes_the_header_row(gate, ties_ep):
    assert ok(gate, ties_ep)["total"] == 5


# ---------------------------------------------------------------------------
# Phrase: "Responses include integer `total`"
# Context: `total` is present in the `objects` shape too.
# ---------------------------------------------------------------------------
def test_total_present_in_objects_shape(gate, simple_ep):
    assert ok(gate, simple_ep, _shape="objects")["total"] == 2


# ---------------------------------------------------------------------------
# Phrase: "`_size` (positive integer, default `100`) limits returned rows."
# Context: explicit `_size`.
# ---------------------------------------------------------------------------
def test_size_limits_returned_rows(gate, big_ep):
    body = ok(gate, big_ep, _size=5)
    assert len(body["rows"]) == 5
    assert body["rows"] == [[0], [1], [2], [3], [4]]


# ---------------------------------------------------------------------------
# Phrase: "`_size` (positive integer, default `100`)"
# Context: omitting `_size` yields the documented default of 100.
# ---------------------------------------------------------------------------
def test_size_defaults_to_100(gate, big_ep):
    assert len(ok(gate, big_ep)["rows"]) == 100


# ---------------------------------------------------------------------------
# Phrase: "`_size` (positive integer ...)"
# Context: `_size=1` is the smallest legal value.
# ---------------------------------------------------------------------------
def test_size_of_one(gate, big_ep):
    assert ok(gate, big_ep, _size=1)["rows"] == [[0]]


# ---------------------------------------------------------------------------
# Phrase: "If it exceeds available rows, return all."
# Context: `_size` larger than the dataset.
# ---------------------------------------------------------------------------
def test_size_larger_than_dataset_returns_all(gate, simple_ep):
    body = ok(gate, simple_ep, _size=1000)
    assert body["rows"] == [["Alice", 30], ["Bob", 41]]
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# Phrase: "If it exceeds available rows, return all."
# Context: `_size` above 100 is honoured, not re-clamped to the default.
# ---------------------------------------------------------------------------
def test_size_above_default_is_honoured(gate, big_ep):
    assert len(ok(gate, big_ep, _size=200)["rows"]) == 200


# ---------------------------------------------------------------------------
# Phrase: "`_offset` (non-negative integer, default `0`) skips that many rows
#          before returning."
# Context: explicit `_offset`.
# ---------------------------------------------------------------------------
def test_offset_skips_rows(gate, big_ep):
    assert ok(gate, big_ep, _offset=3, _size=2)["rows"] == [[3], [4]]


# ---------------------------------------------------------------------------
# Phrase: "`_offset` ... default `0`"
# Context: omitting `_offset` starts at the first row.
# ---------------------------------------------------------------------------
def test_offset_defaults_to_zero(gate, big_ep):
    assert ok(gate, big_ep, _size=1)["rows"] == [[0]]


# ---------------------------------------------------------------------------
# Phrase: "`_offset` (non-negative integer ...)"
# Context: `_offset=0` is legal and is a no-op.
# ---------------------------------------------------------------------------
def test_offset_zero_is_legal(gate, simple_ep):
    assert ok(gate, simple_ep, _offset=0)["rows"] == [["Alice", 30], ["Bob", 41]]


# ---------------------------------------------------------------------------
# Phrase: "`_offset` ... skips that many rows before returning."
# Context: an offset past the end yields no rows but a full `total`.
# ---------------------------------------------------------------------------
def test_offset_past_end_returns_no_rows(gate, simple_ep):
    body = ok(gate, simple_ep, _offset=99)
    assert body["rows"] == []
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`."
# Context: `_size` that is not a positive integer.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5", "", "1e2", "two"])
def test_invalid_size_is_400(gate, simple_ep, value):
    bad(gate, simple_ep, f"_size={value}")


# ---------------------------------------------------------------------------
# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`."
# Context: `_offset` that is not a non-negative integer.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["-1", "abc", "1.5", "", "x"])
def test_invalid_offset_is_400(gate, simple_ep, value):
    bad(gate, simple_ep, f"_offset={value}")


# ---------------------------------------------------------------------------
# Phrase: "`_offset` (non-negative integer ...)"
# Context: zero is valid for `_offset` even though it is invalid for `_size`.
# ---------------------------------------------------------------------------
def test_offset_zero_valid_while_size_zero_is_not(gate, simple_ep):
    assert gate.get(f"{simple_ep}?_offset=0").status_code == 200
    assert gate.get(f"{simple_ep}?_size=0").status_code == 400


# ---------------------------------------------------------------------------
# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
# Context: ascending sort on a text column.
# ---------------------------------------------------------------------------
def test_sort_ascending(gate, ties_ep):
    body = ok(gate, ties_ep, _sort="k")
    assert [row[0] for row in body["rows"]] == ["a", "a", "a", "b", "b"]


# ---------------------------------------------------------------------------
# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
# Context: ascending sort on a numeric column is numeric, not lexicographic.
# ---------------------------------------------------------------------------
def test_sort_ascending_numeric(gate, origin):
    ep = endpoint_for(gate, origin, "/ctl-num.csv", "n\n10\n9\n100\n2\n")
    assert ok(gate, ep, _sort="n")["rows"] == [[2], [9], [10], [100]]


# ---------------------------------------------------------------------------
# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
# Context: descending sort.
# ---------------------------------------------------------------------------
def test_sort_desc(gate, ties_ep):
    body = ok(gate, ties_ep, _sort_desc="k")
    assert [row[0] for row in body["rows"]] == ["b", "b", "a", "a", "a"]


# ---------------------------------------------------------------------------
# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
# Context: descending sort on a numeric column.
# ---------------------------------------------------------------------------
def test_sort_desc_numeric(gate, origin):
    ep = endpoint_for(gate, origin, "/ctl-numd.csv", "n\n10\n9\n100\n2\n")
    assert ok(gate, ep, _sort_desc="n")["rows"] == [[100], [10], [9], [2]]


# ---------------------------------------------------------------------------
# Phrase: "If both are present, `_sort_desc` wins."
# Context: conflicting sort parameters.
# ---------------------------------------------------------------------------
def test_sort_desc_wins_over_sort(gate, ties_ep):
    body = ok(gate, ties_ep, _sort="v", _sort_desc="v")
    assert [row[1] for row in body["rows"]] == [5, 4, 3, 2, 1]


# ---------------------------------------------------------------------------
# Phrase: "If both are present, `_sort_desc` wins."
# Context: the losing `_sort` may name a different column; it is ignored, but
#          still has to be a real column (see AMBIGUITIES T20).
# ---------------------------------------------------------------------------
def test_sort_desc_wins_with_different_columns(gate, ties_ep):
    body = ok(gate, ties_ep, _sort="k", _sort_desc="v")
    assert [row[1] for row in body["rows"]] == [5, 4, 3, 2, 1]


# ---------------------------------------------------------------------------
# Phrase: "Sorting is stable"
# Context: ties keep source order, ascending.
# ---------------------------------------------------------------------------
def test_sort_is_stable_ascending(gate, ties_ep):
    body = ok(gate, ties_ep, _sort="k")
    assert body["rows"] == [["a", 2], ["a", 3], ["a", 4], ["b", 1], ["b", 5]]


# ---------------------------------------------------------------------------
# Phrase: "Sorting is stable"
# Context: ties keep source order under descending sort too -- the tie group is
#          not reversed (see AMBIGUITIES T19).
# ---------------------------------------------------------------------------
def test_sort_is_stable_descending(gate, ties_ep):
    body = ok(gate, ties_ep, _sort_desc="k")
    assert body["rows"] == [["b", 1], ["b", 5], ["a", 2], ["a", 3], ["a", 4]]


# ---------------------------------------------------------------------------
# Phrase: "and applied before pagination."
# Context: `_size` takes the head of the sorted order, not of source order.
# ---------------------------------------------------------------------------
def test_sort_applied_before_size(gate, big_ep):
    assert ok(gate, big_ep, _sort_desc="n", _size=3)["rows"] == [[249], [248], [247]]


# ---------------------------------------------------------------------------
# Phrase: "and applied before pagination."
# Context: `_offset` counts into the sorted order.
# ---------------------------------------------------------------------------
def test_sort_applied_before_offset(gate, big_ep):
    body = ok(gate, big_ep, _sort_desc="n", _size=2, _offset=2)
    assert body["rows"] == [[247], [246]]


# ---------------------------------------------------------------------------
# Phrase: "Empty values or unknown columns return `HTTP 400`."
# Context: empty `_sort`/`_sort_desc` values.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", ["_sort=", "_sort_desc=", "_sort", "_sort_desc"])
def test_empty_sort_value_is_400(gate, simple_ep, query):
    bad(gate, simple_ep, query)


# ---------------------------------------------------------------------------
# Phrase: "Empty values or unknown columns return `HTTP 400`."
# Context: unknown sort columns, including a case-mismatched name.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query", ["_sort=nope", "_sort_desc=nope", "_sort=NAME", "_sort_desc=Age"]
)
def test_unknown_sort_column_is_400(gate, simple_ep, query):
    bad(gate, simple_ep, query)


# ---------------------------------------------------------------------------
# Phrase: "Empty values or unknown columns return `HTTP 400`."
# Context: `rowid` is not a column, so sorting by it is rejected
#          (see AMBIGUITIES T20).
# ---------------------------------------------------------------------------
def test_sort_by_rowid_is_400(gate, simple_ep):
    bad(gate, simple_ep, "_sort=rowid")


# ---------------------------------------------------------------------------
# Phrase: "Empty values or unknown columns return `HTTP 400`."
# Context: a bad `_sort` is still rejected when `_sort_desc` would win.
# ---------------------------------------------------------------------------
def test_bad_sort_rejected_even_when_sort_desc_present(gate, simple_ep):
    bad(gate, simple_ep, "_sort=nope&_sort_desc=name")


# ---------------------------------------------------------------------------
# Phrase: "`_shape=lists` (default): `rows` is arrays."
# Context: explicit `_shape=lists`.
# ---------------------------------------------------------------------------
def test_shape_lists_is_arrays(gate, simple_ep):
    body = ok(gate, simple_ep, _shape="lists")
    assert body["rows"] == [["Alice", 30], ["Bob", 41]]
    assert all(isinstance(row, list) for row in body["rows"])


# ---------------------------------------------------------------------------
# Phrase: "`_shape=lists` (default)"
# Context: omitting `_shape` behaves exactly like `_shape=lists`.
# ---------------------------------------------------------------------------
def test_shape_defaults_to_lists(gate, simple_ep):
    default = ok(gate, simple_ep)
    explicit = ok(gate, simple_ep, _shape="lists")
    assert default["rows"] == explicit["rows"]
    assert all(isinstance(row, list) for row in default["rows"])


# ---------------------------------------------------------------------------
# Phrase: "`_shape=lists` (default): `rows` is arrays."
# Context: the lists shape carries no `rowid` anywhere
#          (see AMBIGUITIES T21).
# ---------------------------------------------------------------------------
def test_shape_lists_has_no_rowid(gate, simple_ep):
    body = ok(gate, simple_ep, _shape="lists")
    assert "rowid" not in body
    assert body["columns"] == ["name", "age"]
    assert all(len(row) == 2 for row in body["rows"])


# ---------------------------------------------------------------------------
# Phrase: "`_shape=objects`: `rows` is objects"
# Context: objects shape keys each row by column name.
# ---------------------------------------------------------------------------
def test_shape_objects_is_objects(gate, simple_ep):
    body = ok(gate, simple_ep, _shape="objects")
    assert all(isinstance(row, dict) for row in body["rows"])
    assert body["rows"][0]["name"] == "Alice"
    assert body["rows"][0]["age"] == 30


# ---------------------------------------------------------------------------
# Phrase: "and includes `rowid` (1-based source-file row number, starting at
#          the header)."
# Context: the header is row 1, so the first data row is rowid 2.
# ---------------------------------------------------------------------------
def test_objects_rowid_starts_at_two(gate, simple_ep):
    rows = ok(gate, simple_ep, _shape="objects")["rows"]
    assert [row["rowid"] for row in rows] == [2, 3]


# ---------------------------------------------------------------------------
# Phrase: "rowid (1-based source-file row number ...)"
# Context: rowid follows the row, not its position in the response, so sorting
#          and offsetting carry the original numbers along.
# ---------------------------------------------------------------------------
def test_objects_rowid_follows_the_row_through_sorting(gate, ties_ep):
    rows = ok(gate, ties_ep, _shape="objects", _sort="k")["rows"]
    assert [row["rowid"] for row in rows] == [3, 4, 5, 2, 6]


# ---------------------------------------------------------------------------
# Phrase: "rowid (1-based source-file row number ...)"
# Context: `_offset` does not renumber rowid.
# ---------------------------------------------------------------------------
def test_objects_rowid_with_offset(gate, big_ep):
    rows = ok(gate, big_ep, _shape="objects", _offset=10, _size=2)["rows"]
    assert [row["rowid"] for row in rows] == [12, 13]
    assert [row["n"] for row in rows] == [10, 11]


# ---------------------------------------------------------------------------
# Phrase: "`rowid` is not in `columns`."
# Context: the columns list describes the source columns only.
# ---------------------------------------------------------------------------
def test_rowid_not_in_columns(gate, simple_ep):
    body = ok(gate, simple_ep, _shape="objects")
    assert body["columns"] == ["name", "age"]
    assert "rowid" not in body["columns"]


# ---------------------------------------------------------------------------
# Phrase: "`_rowid=hide` removes `rowid`."
# Context: objects shape without rowid.
# ---------------------------------------------------------------------------
def test_rowid_hide_removes_rowid(gate, simple_ep):
    body = ok(gate, simple_ep, _shape="objects", _rowid="hide")
    assert all("rowid" not in row for row in body["rows"])
    assert body["rows"][0] == {"name": "Alice", "age": 30}


# ---------------------------------------------------------------------------
# Phrase: "`_rowid=hide` removes `rowid`."
# Context: harmless on the lists shape, which has no rowid to begin with
#          (see AMBIGUITIES T21).
# ---------------------------------------------------------------------------
def test_rowid_hide_accepted_with_lists_shape(gate, simple_ep):
    body = ok(gate, simple_ep, _rowid="hide")
    assert body["rows"] == [["Alice", 30], ["Bob", 41]]


# ---------------------------------------------------------------------------
# Phrase: "`_total=hide` removes `total`."
# Context: the key is absent, not null or zero.
# ---------------------------------------------------------------------------
def test_total_hide_removes_total(gate, simple_ep):
    body = ok(gate, simple_ep, _total="hide")
    assert "total" not in body
    assert body["ok"] is True
    assert body["rows"] == [["Alice", 30], ["Bob", 41]]


# ---------------------------------------------------------------------------
# Phrase: "`_total=hide` removes `total`."
# Context: both toggles at once.
# ---------------------------------------------------------------------------
def test_both_toggles_together(gate, simple_ep):
    body = ok(gate, simple_ep, _shape="objects", _rowid="hide", _total="hide")
    assert "total" not in body
    assert body["rows"] == [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 41}]


# ---------------------------------------------------------------------------
# Phrase: "Each toggle is valid only with value `hide`; any other value is
#          `HTTP 400`."
# Context: non-`hide` values for `_rowid`.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["show", "", "HIDE", "true", "1", "hidden"])
def test_invalid_rowid_value_is_400(gate, simple_ep, value):
    bad(gate, simple_ep, f"_rowid={value}")


# ---------------------------------------------------------------------------
# Phrase: "Each toggle is valid only with value `hide`; any other value is
#          `HTTP 400`."
# Context: non-`hide` values for `_total`.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["show", "", "HIDE", "false", "0", "hide "])
def test_invalid_total_value_is_400(gate, simple_ep, value):
    bad(gate, simple_ep, f"_total={value}")


# ---------------------------------------------------------------------------
# Phrase: "Each toggle is valid only with value `hide`"
# Context: a bare toggle with no `=` carries no value, so it is not `hide`.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", ["_rowid", "_total"])
def test_bare_toggle_without_value_is_400(gate, simple_ep, query):
    bad(gate, simple_ep, query)


# ---------------------------------------------------------------------------
# Phrase: "`_shape` not `lists`/`objects` | 400"
# Context: invalid shape values.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["array", "", "LISTS", "Objects", "object", "list"])
def test_invalid_shape_is_400(gate, simple_ep, value):
    bad(gate, simple_ep, f"_shape={value}")


# ---------------------------------------------------------------------------
# Phrase: "Any repeated control parameter (`_size`, `_offset`, `_shape`,
#          `_sort`, `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`."
# Context: every control name, repeated with differing values.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "_size=1&_size=2",
        "_offset=0&_offset=1",
        "_shape=lists&_shape=objects",
        "_sort=name&_sort=age",
        "_sort_desc=name&_sort_desc=age",
        "_rowid=hide&_rowid=show",
        "_total=hide&_total=show",
    ],
)
def test_repeated_control_parameter_is_400(gate, simple_ep, query):
    bad(gate, simple_ep, query)


# ---------------------------------------------------------------------------
# Phrase: "Any repeated control parameter ... is `HTTP 400`."
# Context: repetition is rejected even when both copies are identical and
#          individually valid (see AMBIGUITIES T22).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "_size=5&_size=5",
        "_offset=1&_offset=1",
        "_shape=objects&_shape=objects",
        "_sort=name&_sort=name",
        "_rowid=hide&_rowid=hide",
        "_total=hide&_total=hide",
    ],
)
def test_repeated_identical_control_parameter_is_400(gate, simple_ep, query):
    bad(gate, simple_ep, query)


# ---------------------------------------------------------------------------
# Phrase: "Any repeated control parameter ... is `HTTP 400`."
# Context: `_sort` and `_sort_desc` are different parameters; using one of each
#          is not a repeat (that case is governed by "`_sort_desc` wins").
# ---------------------------------------------------------------------------
def test_sort_and_sort_desc_together_is_not_a_repeat(gate, simple_ep):
    assert gate.get(f"{simple_ep}?_sort=name&_sort_desc=age").status_code == 200


# ---------------------------------------------------------------------------
# Phrase: "Any repeated *control* parameter ... is `HTTP 400`."
# Context: non-control parameters are not controls, so repeating them is not an
#          error (see AMBIGUITIES T23).
# ---------------------------------------------------------------------------
def test_repeated_non_control_parameter_is_ignored(gate, simple_ep):
    resp = gate.get(f"{simple_ep}?colour=red&colour=blue")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


# ---------------------------------------------------------------------------
# Phrase: error table, every row -> `{"ok": false, "error": "<message>"}`.
# Context: the 400 envelope shape is uniform across all control errors.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "_size=0",
        "_offset=-1",
        "_shape=nope",
        "_rowid=nope",
        "_total=nope",
        "_size=1&_size=1",
        "_sort=nope",
        "_sort_desc=",
    ],
)
def test_control_errors_use_the_json_envelope(gate, simple_ep, query):
    resp = gate.get(f"{simple_ep}?{query}")
    assert resp.status_code == 400
    assert resp.headers["Content-Type"].startswith("application/json")
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]
    assert "rows" not in body and "total" not in body


# ---------------------------------------------------------------------------
# Phrase: "`GET /datasets/<id>` accepts control parameters"
# Context: an unknown dataset id still 404s, whatever the controls say
#          (see AMBIGUITIES T24).
# ---------------------------------------------------------------------------
def test_unknown_dataset_still_404_with_controls(gate):
    resp = gate.get("/datasets/0123456789abcdef?_size=0")
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Phrase: "Sorting is stable and applied before pagination."
# Context: sorting a column holding both numbers and text must not crash
#          (see AMBIGUITIES T19).
# ---------------------------------------------------------------------------
def test_sort_mixed_types_is_total(gate, origin):
    ep = endpoint_for(gate, origin, "/ctl-mixed.csv", "v\n10\nzebra\n2\napple\n")
    body = ok(gate, ep, _sort="v")
    assert body["total"] == 4
    assert len(body["rows"]) == 4
    assert [row[0] for row in body["rows"]] == [2, 10, "apple", "zebra"]


# ---------------------------------------------------------------------------
# Phrase: "Responses include integer `total`" + existing envelope.
# Context: controls do not disturb the pre-existing response fields.
# ---------------------------------------------------------------------------
def test_existing_envelope_fields_survive(gate, simple_ep):
    body = ok(gate, simple_ep, _shape="objects", _sort="name", _size=1)
    assert body["ok"] is True
    assert body["columns"] == ["name", "age"]
    assert body["query_ms"] >= 0
