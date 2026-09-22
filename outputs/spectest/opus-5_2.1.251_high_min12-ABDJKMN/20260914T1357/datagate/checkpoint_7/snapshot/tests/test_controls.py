"""Spec tests for pagination, sorting and response controls on /datasets/<id>.

Each section quotes the spec phrase (and its context) that it covers.
"""
import json

import pytest


SIMPLE = "name,age\nada,36\ngrace,45\n"
TIES = "name,age\nzoe,30\nada,36\nmia,30\nbea,36\n"
MANY = "n,v\n" + "".join("%d,a\n" % i for i in range(120))

CONTROLS = ["_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total"]


@pytest.fixture
def ds(server, csv_url):
    """Convert a CSV body; return its /datasets/<id> endpoint path."""
    def make(body, name="ctl"):
        url = csv_url(body, name=name)
        status, _, data = server.convert(url)
        assert status == 200, data
        return data["endpoint"]
    return make


def assert_error(status, data):
    """Spec: 400 responses are `{"ok": false, "error": "<message>"}`."""
    assert status == 400, data
    assert data is not None
    assert data["ok"] is False
    assert isinstance(data["error"], str) and data["error"].strip()


# ==========================================================================
# Spec: "`GET /datasets/<id>` accepts control parameters for pagination,
#        sorting, and shape."
# ==========================================================================
def test_control_parameters_are_accepted_on_datasets_endpoint(server, ds):
    endpoint = ds(SIMPLE, name="accept")
    query = "?_size=1&_offset=1&_sort=name&_shape=objects"
    status, _, data = server.get(endpoint + query)
    assert status == 200, data
    assert data["ok"] is True


# Spec: control parameters do not disturb the existing response envelope.
def test_controls_keep_ok_columns_and_query_ms(server, ds):
    endpoint = ds(SIMPLE, name="envelope")
    status, _, data = server.get(endpoint + "?_size=1")
    assert status == 200
    assert data["ok"] is True
    assert data["columns"] == ["name", "age"]
    assert "query_ms" in data


# ==========================================================================
# Spec: "### `total` — Responses include integer `total` for the row count
#        before pagination."
# ==========================================================================
def test_total_is_present_and_integer(server, ds):
    endpoint = ds(SIMPLE, name="total")
    data = server.get(endpoint)[2]
    assert "total" in data
    assert isinstance(data["total"], int) and not isinstance(data["total"], bool)
    assert data["total"] == 2


# Spec: "`total` for the row count before pagination" — the default 100-row
# page does not shrink `total`.
def test_total_is_row_count_before_default_pagination(server, ds):
    endpoint = ds(MANY, name="total-many")
    data = server.get(endpoint)[2]
    assert len(data["rows"]) == 100
    assert data["total"] == 120


# Spec: "before pagination" — `_size`/`_offset` never change `total`.
@pytest.mark.parametrize("query", ["?_size=1", "?_offset=3", "?_size=2&_offset=110",
                                   "?_offset=500", "?_size=1000"])
def test_total_unaffected_by_pagination_params(server, ds, query):
    endpoint = ds(MANY, name="total-page")
    data = server.get(endpoint + query)[2]
    assert data["total"] == 120


# Spec: "before pagination" — sorting does not change `total` either.
def test_total_unaffected_by_sorting(server, ds):
    endpoint = ds(MANY, name="total-sort")
    assert server.get(endpoint + "?_sort=n")[2]["total"] == 120
    assert server.get(endpoint + "?_sort_desc=n&_size=3")[2]["total"] == 120


# ==========================================================================
# Spec: "### Pagination — `_size` (positive integer, default `100`) limits
#        returned rows."
# ==========================================================================
def test_size_limits_returned_rows(server, ds):
    endpoint = ds(MANY, name="size")
    data = server.get(endpoint + "?_size=5")[2]
    assert len(data["rows"]) == 5
    assert data["rows"] == [[i, "a"] for i in range(5)]


# Spec: "`_size` (positive integer, default `100`)"
def test_size_defaults_to_100(server, ds):
    endpoint = ds(MANY, name="size-default")
    assert len(server.get(endpoint)[2]["rows"]) == 100


# Spec: "`_size` ... If it exceeds available rows, return all."
def test_size_exceeding_available_rows_returns_all(server, ds):
    endpoint = ds(MANY, name="size-big")
    data = server.get(endpoint + "?_size=1000")[2]
    assert len(data["rows"]) == 120
    assert data["total"] == 120


# Spec: "If it exceeds available rows, return all." — also for a tiny dataset.
def test_size_exceeding_tiny_dataset(server, ds):
    endpoint = ds(SIMPLE, name="size-tiny")
    data = server.get(endpoint + "?_size=99")[2]
    assert data["rows"] == [["ada", 36], ["grace", 45]]


# Spec: "`_size` (positive integer ...)" — 1 is the smallest valid value.
def test_size_one(server, ds):
    endpoint = ds(MANY, name="size-one")
    assert server.get(endpoint + "?_size=1")[2]["rows"] == [[0, "a"]]


# ==========================================================================
# Spec: "`_offset` (non-negative integer, default `0`) skips that many rows
#        before returning."
# ==========================================================================
def test_offset_skips_rows(server, ds):
    endpoint = ds(MANY, name="offset")
    data = server.get(endpoint + "?_offset=10&_size=3")[2]
    assert data["rows"] == [[10, "a"], [11, "a"], [12, "a"]]


# Spec: "`_offset` ... default `0`"
def test_offset_defaults_to_zero(server, ds):
    endpoint = ds(MANY, name="offset-default")
    assert server.get(endpoint + "?_size=2")[2]["rows"] == [[0, "a"], [1, "a"]]


# Spec: "`_offset` (non-negative integer ...)" — 0 is valid and is a no-op.
def test_offset_zero_is_valid(server, ds):
    endpoint = ds(SIMPLE, name="offset-zero")
    status, _, data = server.get(endpoint + "?_offset=0")
    assert status == 200
    assert data["rows"] == [["ada", 36], ["grace", 45]]


# Spec: "_offset ... skips that many rows" — skipping past the end yields none.
def test_offset_past_end_returns_no_rows(server, ds):
    endpoint = ds(SIMPLE, name="offset-past")
    status, _, data = server.get(endpoint + "?_offset=99")
    assert status == 200
    assert data["rows"] == []
    assert data["total"] == 2


# Spec: `_offset` combined with the default `_size` still caps the page at 100.
def test_offset_with_default_size(server, ds):
    endpoint = ds(MANY, name="offset-default-size")
    data = server.get(endpoint + "?_offset=5")[2]
    assert len(data["rows"]) == 100
    assert data["rows"][0] == [5, "a"]


# ==========================================================================
# Spec: "Invalid `_size`/`_offset` -> `HTTP 400`." and the error table rows
#       "`_size` not a positive integer | 400" /
#       "`_offset` not a non-negative integer | 400".
# ==========================================================================
@pytest.mark.parametrize("value", ["0", "-1", "-10", "abc", "1.5", "", " ", "1e3",
                                   "10x", "nan", "null", "0x10"])
def test_invalid_size_is_400(server, ds, value):
    from urllib.parse import quote
    endpoint = ds(SIMPLE, name="bad-size")
    status, _, data = server.get(endpoint + "?_size=" + quote(value, safe=""))
    assert_error(status, data)


@pytest.mark.parametrize("value", ["-1", "-100", "abc", "1.5", "", " ", "2e2",
                                   "10x", "null"])
def test_invalid_offset_is_400(server, ds, value):
    from urllib.parse import quote
    endpoint = ds(SIMPLE, name="bad-offset")
    status, _, data = server.get(endpoint + "?_offset=" + quote(value, safe=""))
    assert_error(status, data)


# Spec: a bare control parameter with no value is an empty (invalid) value.
def test_bare_size_and_offset_are_400(server, ds):
    endpoint = ds(SIMPLE, name="bare-page")
    assert_error(*server.get(endpoint + "?_size")[::2])
    assert_error(*server.get(endpoint + "?_offset")[::2])


# ==========================================================================
# Spec: "### Sorting — `_sort=<column>` sorts ascending by `<column>`."
# ==========================================================================
def test_sort_ascending_by_text_column(server, ds):
    endpoint = ds(TIES, name="sort-asc")
    data = server.get(endpoint + "?_sort=name")[2]
    assert [r[0] for r in data["rows"]] == ["ada", "bea", "mia", "zoe"]


def test_sort_ascending_by_numeric_column(server, ds):
    endpoint = ds("name,age\nzoe,30\nada,100\nmia,9\n", name="sort-num")
    data = server.get(endpoint + "?_sort=age")[2]
    assert [r[1] for r in data["rows"]] == [9, 30, 100]


# Spec: "`_sort_desc=<column>` sorts descending by `<column>`."
def test_sort_desc_descending(server, ds):
    endpoint = ds(TIES, name="sort-desc")
    data = server.get(endpoint + "?_sort_desc=name")[2]
    assert [r[0] for r in data["rows"]] == ["zoe", "mia", "bea", "ada"]


def test_sort_desc_numeric(server, ds):
    endpoint = ds("name,age\nzoe,30\nada,100\nmia,9\n", name="sort-desc-num")
    data = server.get(endpoint + "?_sort_desc=age")[2]
    assert [r[1] for r in data["rows"]] == [100, 30, 9]


# Spec: "If both are present, `_sort_desc` wins."
def test_sort_desc_wins_over_sort(server, ds):
    endpoint = ds(TIES, name="sort-both")
    data = server.get(endpoint + "?_sort=name&_sort_desc=name")[2]
    assert [r[0] for r in data["rows"]] == ["zoe", "mia", "bea", "ada"]


# Spec: "If both are present, `_sort_desc` wins." — different columns, too.
def test_sort_desc_wins_with_different_columns(server, ds):
    endpoint = ds(TIES, name="sort-both-cols")
    data = server.get(endpoint + "?_sort=name&_sort_desc=age")[2]
    assert [r[1] for r in data["rows"]] == [36, 36, 30, 30]


# Spec: "Sorting is stable" — rows that tie keep their source order.
def test_sort_is_stable_ascending(server, ds):
    endpoint = ds(TIES, name="stable-asc")
    data = server.get(endpoint + "?_sort=age")[2]
    assert [r[0] for r in data["rows"]] == ["zoe", "mia", "ada", "bea"]


# Spec: "Sorting is stable" — descending ties are not reversed either.
def test_sort_is_stable_descending(server, ds):
    endpoint = ds(TIES, name="stable-desc")
    data = server.get(endpoint + "?_sort_desc=age")[2]
    assert [r[0] for r in data["rows"]] == ["ada", "bea", "zoe", "mia"]


# Spec: "Sorting is ... applied before pagination."
def test_sort_applied_before_pagination(server, ds):
    body = "n,v\n" + "".join("%d,a\n" % i for i in (5, 3, 9, 1, 7))
    endpoint = ds(body, name="sort-page")
    data = server.get(endpoint + "?_sort=n&_size=2")[2]
    assert data["rows"] == [[1, "a"], [3, "a"]]
    data = server.get(endpoint + "?_sort=n&_size=2&_offset=2")[2]
    assert data["rows"] == [[5, "a"], [7, "a"]]
    data = server.get(endpoint + "?_sort_desc=n&_size=1")[2]
    assert data["rows"] == [[9, "a"]]


# Spec: "applied before pagination" — the sort spans the whole dataset, not
# just the default first page.
def test_sort_spans_whole_dataset_not_just_first_page(server, ds):
    endpoint = ds(MANY, name="sort-whole")
    data = server.get(endpoint + "?_sort_desc=n&_size=3")[2]
    assert data["rows"] == [[119, "a"], [118, "a"], [117, "a"]]


# Spec: "Empty values or unknown columns return `HTTP 400`."
@pytest.mark.parametrize("param", ["_sort", "_sort_desc"])
def test_sort_empty_value_is_400(server, ds, param):
    endpoint = ds(SIMPLE, name="sort-empty")
    status, _, data = server.get(endpoint + "?%s=" % param)
    assert_error(status, data)
    status, _, data = server.get(endpoint + "?" + param)
    assert_error(status, data)


@pytest.mark.parametrize("param", ["_sort", "_sort_desc"])
@pytest.mark.parametrize("column", ["nope", "NAME", "name ", "rowid", "0", "age;"])
def test_sort_unknown_column_is_400(server, ds, param, column):
    endpoint = ds(SIMPLE, name="sort-unknown")
    from urllib.parse import quote
    status, _, data = server.get(
        endpoint + "?%s=%s" % (param, quote(column, safe="")))
    assert_error(status, data)


# ==========================================================================
# Spec: "### Response shape — `_shape=lists` (default): `rows` is arrays."
# ==========================================================================
def test_default_shape_is_lists(server, ds):
    endpoint = ds(SIMPLE, name="shape-default")
    data = server.get(endpoint)[2]
    assert data["rows"] == [["ada", 36], ["grace", 45]]
    assert all(isinstance(r, list) for r in data["rows"])


def test_explicit_shape_lists(server, ds):
    endpoint = ds(SIMPLE, name="shape-lists")
    status, _, data = server.get(endpoint + "?_shape=lists")
    assert status == 200
    assert data["rows"] == [["ada", 36], ["grace", 45]]


# Spec: "`_shape=lists` (default)" — lists shape carries no `rowid`.
def test_lists_shape_has_no_rowid(server, ds):
    endpoint = ds(SIMPLE, name="shape-lists-norowid")
    body = server.raw(endpoint + "?_shape=lists")[2].decode("utf-8")
    assert "rowid" not in body


# Spec: "`_shape=objects`: `rows` is objects and includes `rowid` (1-based
#        source-file row number)."
def test_shape_objects_returns_objects_with_rowid(server, ds):
    endpoint = ds(SIMPLE, name="shape-objects")
    status, _, data = server.get(endpoint + "?_shape=objects")
    assert status == 200
    assert data["rows"] == [
        {"rowid": 1, "name": "ada", "age": 36},
        {"rowid": 2, "name": "grace", "age": 45},
    ]


# Spec: "`rowid` is not in `columns`."
def test_rowid_not_in_columns(server, ds):
    endpoint = ds(SIMPLE, name="shape-columns")
    data = server.get(endpoint + "?_shape=objects")[2]
    assert data["columns"] == ["name", "age"]
    assert "rowid" not in data["columns"]


# Spec: "`rowid` (1-based source-file row number)" — the number identifies the
# source row, so it survives sorting.
def test_rowid_follows_source_row_through_sorting(server, ds):
    endpoint = ds(TIES, name="rowid-sort")
    data = server.get(endpoint + "?_shape=objects&_sort=name")[2]
    assert [(r["name"], r["rowid"]) for r in data["rows"]] == [
        ("ada", 2), ("bea", 4), ("mia", 3), ("zoe", 1)]


# Spec: "`rowid` (1-based source-file row number)" — and through pagination.
def test_rowid_follows_source_row_through_pagination(server, ds):
    endpoint = ds(MANY, name="rowid-page")
    data = server.get(endpoint + "?_shape=objects&_offset=10&_size=2")[2]
    assert [r["rowid"] for r in data["rows"]] == [11, 12]


# Spec: "`_shape=objects`: `rows` is objects" — objects keyed by column names.
def test_objects_shape_keys_are_columns(server, ds):
    endpoint = ds(SIMPLE, name="objects-keys")
    data = server.get(endpoint + "?_shape=objects")[2]
    for row in data["rows"]:
        assert set(row) == {"rowid"} | set(data["columns"])


# Spec error table: "`_shape` not `lists`/`objects` | 400"
@pytest.mark.parametrize("value", ["", "list", "object", "LISTS", "Objects",
                                   "arrays", "dicts", "0", " lists"])
def test_invalid_shape_is_400(server, ds, value):
    from urllib.parse import quote
    endpoint = ds(SIMPLE, name="bad-shape")
    status, _, data = server.get(endpoint + "?_shape=" + quote(value, safe=""))
    assert_error(status, data)


def test_bare_shape_is_400(server, ds):
    endpoint = ds(SIMPLE, name="bare-shape")
    assert_error(*server.get(endpoint + "?_shape")[::2])


# ==========================================================================
# Spec: "### Visibility toggles — `_rowid=hide` removes `rowid`."
# ==========================================================================
def test_rowid_hide_removes_rowid(server, ds):
    endpoint = ds(SIMPLE, name="rowid-hide")
    status, _, data = server.get(endpoint + "?_shape=objects&_rowid=hide")
    assert status == 200
    assert data["rows"] == [{"name": "ada", "age": 36},
                            {"name": "grace", "age": 45}]
    assert all("rowid" not in r for r in data["rows"])


# Spec: "`_total=hide` removes `total`."
def test_total_hide_removes_total(server, ds):
    endpoint = ds(SIMPLE, name="total-hide")
    status, _, data = server.get(endpoint + "?_total=hide")
    assert status == 200
    assert "total" not in data
    assert data["ok"] is True
    assert data["rows"] == [["ada", 36], ["grace", 45]]


# Spec: both toggles at once.
def test_both_toggles_together(server, ds):
    endpoint = ds(SIMPLE, name="both-hide")
    status, _, data = server.get(
        endpoint + "?_shape=objects&_rowid=hide&_total=hide")
    assert status == 200
    assert "total" not in data
    assert data["rows"] == [{"name": "ada", "age": 36},
                            {"name": "grace", "age": 45}]


# Spec: "Each toggle is valid only with value `hide`; any other value is
#        `HTTP 400`."
@pytest.mark.parametrize("param", ["_rowid", "_total"])
@pytest.mark.parametrize("value", ["", "show", "HIDE", "Hide", "true", "1",
                                   "hidden", "no", " hide"])
def test_invalid_toggle_value_is_400(server, ds, param, value):
    from urllib.parse import quote
    endpoint = ds(SIMPLE, name="bad-toggle")
    status, _, data = server.get(
        endpoint + "?%s=%s" % (param, quote(value, safe="")))
    assert_error(status, data)


@pytest.mark.parametrize("param", ["_rowid", "_total"])
def test_bare_toggle_is_400(server, ds, param):
    endpoint = ds(SIMPLE, name="bare-toggle")
    assert_error(*server.get(endpoint + "?" + param)[::2])


# ==========================================================================
# Spec: "Any repeated control parameter (`_size`, `_offset`, `_shape`,
#        `_sort`, `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`."
# ==========================================================================
REPEATS = {
    "_size": ("1", "2"),
    "_offset": ("0", "1"),
    "_shape": ("lists", "objects"),
    "_sort": ("name", "age"),
    "_sort_desc": ("name", "age"),
    "_rowid": ("hide", "hide"),
    "_total": ("hide", "hide"),
}


@pytest.mark.parametrize("param", CONTROLS)
def test_repeated_control_parameter_is_400(server, ds, param):
    endpoint = ds(SIMPLE, name="repeat")
    a, b = REPEATS[param]
    status, _, data = server.get(
        endpoint + "?%s=%s&%s=%s" % (param, a, param, b))
    assert_error(status, data)


# Spec: "Any repeated control parameter ... is `HTTP 400`" — repeating with the
# same (otherwise valid) value is still a repeat.
@pytest.mark.parametrize("param", CONTROLS)
def test_repeated_identical_value_is_400(server, ds, param):
    endpoint = ds(SIMPLE, name="repeat-same")
    value = REPEATS[param][0]
    status, _, data = server.get(
        endpoint + "?%s=%s&%s=%s" % (param, value, param, value))
    assert_error(status, data)


# Spec: "Any repeated control parameter ... is `HTTP 400`" — three copies too,
# and a repeat next to other valid controls.
def test_repeat_among_other_controls_is_400(server, ds):
    endpoint = ds(SIMPLE, name="repeat-mixed")
    assert_error(*server.get(endpoint + "?_size=1&_size=1&_size=1")[::2])
    assert_error(*server.get(
        endpoint + "?_shape=objects&_offset=0&_offset=0&_sort=name")[::2])


# Spec: `_sort` and `_sort_desc` are distinct parameters — using both once is
# not a "repeat" (it is resolved by `_sort_desc` wins).
def test_sort_and_sort_desc_together_is_not_a_repeat(server, ds):
    endpoint = ds(SIMPLE, name="not-repeat")
    status, _, data = server.get(endpoint + "?_sort=name&_sort_desc=name")
    assert status == 200, data


# ==========================================================================
# Spec: Error Handling table — every listed condition answers 400 with
#       `{"ok": false, "error": "<message>"}`.
# ==========================================================================
@pytest.mark.parametrize("query", [
    "?_size=0",              # _size not a positive integer
    "?_offset=-1",           # _offset not a non-negative integer
    "?_shape=weird",         # _shape not lists/objects
    "?_rowid=show",          # invalid _rowid value
    "?_total=show",          # invalid _total value
    "?_size=1&_size=2",      # control parameter repeated
    "?_sort=missing",        # _sort unknown column
    "?_sort_desc=missing",   # _sort_desc unknown column
])
def test_error_envelope_for_every_table_row(server, ds, query):
    endpoint = ds(SIMPLE, name="table")
    status, headers, data = server.get(endpoint + query)
    assert_error(status, data)
    assert "json" in headers.get("Content-Type", "").lower()
    assert "rows" not in data and "total" not in data


# Spec: a 400 from the control layer must not be confused with a 404 for an
# unknown dataset id.
def test_unknown_dataset_still_404_with_controls(server):
    status, _, data = server.get("/datasets/no-such-id?_size=5")
    assert status == 404
    assert data["ok"] is False


# ==========================================================================
# Spec: combinations — shape + sort + pagination + toggles interact as one
#       pipeline (sort, then offset/size, then shape/visibility).
# ==========================================================================
def test_full_pipeline_combination(server, ds):
    endpoint = ds(TIES, name="pipeline")
    data = server.get(
        endpoint + "?_sort_desc=age&_offset=1&_size=2&_shape=objects")[2]
    assert data["total"] == 4
    assert data["rows"] == [
        {"rowid": 4, "name": "bea", "age": 36},
        {"rowid": 1, "name": "zoe", "age": 30},
    ]


# Spec: responses stay deterministic for a fixed query.
def test_controls_are_deterministic(server, ds):
    endpoint = ds(TIES, name="determinism")
    query = "?_sort=name&_shape=objects&_size=3"
    seen = set()
    for _ in range(3):
        payload = server.get(endpoint + query)[2]
        payload.pop("query_ms", None)
        seen.add(json.dumps(payload, sort_keys=True))
    assert len(seen) == 1
