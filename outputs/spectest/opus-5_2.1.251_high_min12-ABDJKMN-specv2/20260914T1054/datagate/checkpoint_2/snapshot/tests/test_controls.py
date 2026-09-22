"""Spec section: Pagination, Sorting, and Response Controls.

Every test is labelled with the minimal spec phrase it pins down, plus the
context that phrase applies in.
"""
import pytest

CSV = "name,qty\nwidget,3\ngadget,4\n"


def numbers_csv(n, start=0):
    """A one-column CSV `n` with values start..start+n-1, in that order."""
    return "n\n" + "".join("%d\n" % i for i in range(start, start + n))


# ============================================================== `total` =====

# Phrase: "Responses include integer `total` for the row count before pagination."
# Context: the key is present on an ordinary dataset query.
def test_total_present(dataset):
    status, body = dataset(CSV)
    assert status == 200
    assert "total" in body


# Phrase: "Responses include integer `total` ..."
# Context: the value is a JSON integer, not a string and not a float.
def test_total_is_an_integer(dataset):
    _, body = dataset(CSV)
    assert isinstance(body["total"], int)
    assert not isinstance(body["total"], bool)


# Phrase: "... `total` for the row count ..."
# Context: with no control parameters it is simply the number of data rows.
def test_total_counts_all_data_rows(dataset):
    _, body = dataset(numbers_csv(7))
    assert body["total"] == 7
    assert len(body["rows"]) == 7


# Phrase: "... the row count *before pagination*."
# Context: `_size` truncates `rows` but must not change `total`.
def test_total_unaffected_by_size(dataset):
    _, body = dataset(numbers_csv(7), query_string={"_size": 2})
    assert body["total"] == 7
    assert len(body["rows"]) == 2


# Phrase: "... the row count *before pagination*."
# Context: `_offset` skips rows but must not change `total`.
def test_total_unaffected_by_offset(dataset):
    _, body = dataset(numbers_csv(7), query_string={"_offset": 5})
    assert body["total"] == 7
    assert len(body["rows"]) == 2


# Phrase: "... the row count before pagination."
# Context: the default cap of 100 is itself pagination - `total` sees past it.
def test_total_exceeds_default_page(dataset):
    _, body = dataset(numbers_csv(250))
    assert body["total"] == 250
    assert len(body["rows"]) == 100


# Phrase: "... the row count before pagination."
# Context: sorting reorders rows without changing how many there are.
def test_total_unaffected_by_sorting(dataset):
    _, body = dataset(numbers_csv(7), query_string={"_sort_desc": "n"})
    assert body["total"] == 7


# ========================================================== pagination ======

# Phrase: "`_size` (positive integer, default `100`) limits returned rows."
# Context: omitted -> the default of 100.
def test_size_defaults_to_100(dataset):
    _, body = dataset(numbers_csv(250))
    assert len(body["rows"]) == 100
    assert body["rows"][0] == [0]
    assert body["rows"][-1] == [99]


# Phrase: "`_size` ... limits returned rows."
# Context: an explicit smaller size takes the first N rows in order.
def test_size_limits_rows(dataset):
    _, body = dataset(numbers_csv(10), query_string={"_size": 3})
    assert body["rows"] == [[0], [1], [2]]


# Phrase: "`_size` ... limits returned rows."
# Context: a size above the default is honoured too.
def test_size_above_default(dataset):
    _, body = dataset(numbers_csv(250), query_string={"_size": 150})
    assert len(body["rows"]) == 150


# Phrase: "`_size` (positive integer ...)"
# Context: 1 is the smallest valid size.
def test_size_one(dataset):
    _, body = dataset(numbers_csv(10), query_string={"_size": 1})
    assert body["rows"] == [[0]]


# Phrase: "If it exceeds available rows, return all."
# Context: `_size` larger than the row count is not an error.
def test_size_exceeding_available_returns_all(dataset):
    status, body = dataset(numbers_csv(4), query_string={"_size": 1000})
    assert status == 200
    assert len(body["rows"]) == 4
    assert body["total"] == 4


# Phrase: "`_offset` (non-negative integer, default `0`) skips that many rows
#          before returning."
# Context: omitted -> start at the first row.
def test_offset_defaults_to_zero(dataset):
    _, body = dataset(numbers_csv(5))
    assert body["rows"][0] == [0]


# Phrase: "`_offset` ... skips that many rows before returning."
# Context: an explicit offset drops exactly that many leading rows.
def test_offset_skips_rows(dataset):
    _, body = dataset(numbers_csv(5), query_string={"_offset": 2})
    assert body["rows"] == [[2], [3], [4]]


# Phrase: "`_offset` (non-negative integer ...)"
# Context: 0 is valid and means "skip nothing".
def test_offset_zero_is_valid(dataset):
    status, body = dataset(numbers_csv(3), query_string={"_offset": 0})
    assert status == 200
    assert body["rows"] == [[0], [1], [2]]


# Phrase: "`_offset` ... skips that many rows before returning."
# Context: combined with `_size` it is a page window.
def test_offset_and_size_together(dataset):
    _, body = dataset(numbers_csv(20), query_string={"_offset": 5, "_size": 3})
    assert body["rows"] == [[5], [6], [7]]
    assert body["total"] == 20


# Phrase: "`_offset` ... skips that many rows before returning."
# Context: an offset past the end yields no rows, not an error.  (see AMBIGUITIES T22)
def test_offset_past_end_returns_empty(dataset):
    status, body = dataset(numbers_csv(3), query_string={"_offset": 10})
    assert status == 200
    assert body["rows"] == []
    assert body["total"] == 3


# Phrase: "`_offset` ... skips that many rows before returning."
# Context: an offset exactly at the row count yields no rows.
def test_offset_equal_to_total_returns_empty(dataset):
    status, body = dataset(numbers_csv(3), query_string={"_offset": 3})
    assert status == 200
    assert body["rows"] == []


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`."
# Context: `_size` must be a *positive* integer, so 0 and negatives are invalid.
@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_size_non_positive_is_400(dataset, value):
    status, body = dataset(CSV, query_string={"_size": value})
    assert status == 400
    assert body["ok"] is False


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`."
# Context: non-integer `_size` values.  (see AMBIGUITIES T21)
@pytest.mark.parametrize("value", ["abc", "1.5", "5.0", "1e3", "", " ", "3px", "0x10"])
def test_size_non_integer_is_400(dataset, value):
    status, body = dataset(CSV, query_string={"_size": value})
    assert status == 400
    assert body["ok"] is False


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`."
# Context: `_offset` must be non-negative, so negatives are invalid.
@pytest.mark.parametrize("value", ["-1", "-42"])
def test_offset_negative_is_400(dataset, value):
    status, body = dataset(CSV, query_string={"_offset": value})
    assert status == 400
    assert body["ok"] is False


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`."
# Context: non-integer `_offset` values.  (see AMBIGUITIES T21)
@pytest.mark.parametrize("value", ["abc", "1.5", "2.0", "", " ", "1,000"])
def test_offset_non_integer_is_400(dataset, value):
    status, body = dataset(CSV, query_string={"_offset": value})
    assert status == 400
    assert body["ok"] is False


# Phrase: '| `_size` not a positive integer | 400 | {"ok": false, "error": "<message>"} |'
# Context: the error envelope carries a human-readable message.
def test_size_error_envelope(dataset):
    status, body = dataset(CSV, query_string={"_size": "0"})
    assert status == 400
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# Phrase: '| `_offset` not a non-negative integer | 400 | {"ok": false, "error": "<message>"} |'
# Context: the error envelope carries a human-readable message.
def test_offset_error_envelope(dataset):
    status, body = dataset(CSV, query_string={"_offset": "-1"})
    assert status == 400
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# ============================================================= sorting ======

SORT_CSV = "name,qty\nbeta,2\nalpha,3\ngamma,1\n"


# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
# Context: a text column.
def test_sort_ascending_text(dataset):
    _, body = dataset(SORT_CSV, query_string={"_sort": "name"})
    assert [r[0] for r in body["rows"]] == ["alpha", "beta", "gamma"]


# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
# Context: a numeric column sorts numerically, not lexicographically.
def test_sort_ascending_numeric(dataset):
    _, body = dataset("n\n10\n9\n100\n2\n", query_string={"_sort": "n"})
    assert [r[0] for r in body["rows"]] == [2, 9, 10, 100]


# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
# Context: sorting by a second column leaves the row contents intact.
def test_sort_keeps_whole_rows(dataset):
    _, body = dataset(SORT_CSV, query_string={"_sort": "qty"})
    assert body["rows"] == [["gamma", 1], ["beta", 2], ["alpha", 3]]


# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
# Context: a text column.
def test_sort_desc_text(dataset):
    _, body = dataset(SORT_CSV, query_string={"_sort_desc": "name"})
    assert [r[0] for r in body["rows"]] == ["gamma", "beta", "alpha"]


# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
# Context: a numeric column.
def test_sort_desc_numeric(dataset):
    _, body = dataset("n\n10\n9\n100\n2\n", query_string={"_sort_desc": "n"})
    assert [r[0] for r in body["rows"]] == [100, 10, 9, 2]


# Phrase: "If both are present, `_sort_desc` wins."
# Context: two different valid columns - the descending one decides the order.
def test_sort_desc_wins_over_sort(dataset):
    _, body = dataset(SORT_CSV, query_string={"_sort": "name", "_sort_desc": "qty"})
    assert [r[1] for r in body["rows"]] == [3, 2, 1]


# Phrase: "If both are present, `_sort_desc` wins."
# Context: the same column in both - descending order results.
def test_sort_desc_wins_same_column(dataset):
    _, body = dataset(SORT_CSV, query_string={"_sort": "name", "_sort_desc": "name"})
    assert [r[0] for r in body["rows"]] == ["gamma", "beta", "alpha"]


# Phrase: "Sorting is stable"
# Context: rows tied on the sort column keep their source-file order (ascending).
def test_sort_is_stable_ascending(dataset):
    csv = "k,v\n1,alpha\n1,beta\n0,gamma\n1,delta\n"
    _, body = dataset(csv, query_string={"_sort": "k"})
    assert [r[1] for r in body["rows"]] == ["gamma", "alpha", "beta", "delta"]


# Phrase: "Sorting is stable"
# Context: ties keep source order under `_sort_desc` too.  (see AMBIGUITIES T23)
def test_sort_is_stable_descending(dataset):
    csv = "k,v\n1,alpha\n1,beta\n0,gamma\n1,delta\n"
    _, body = dataset(csv, query_string={"_sort_desc": "k"})
    assert [r[1] for r in body["rows"]] == ["alpha", "beta", "delta", "gamma"]


# Phrase: "Sorting is ... applied before pagination."
# Context: `_size` takes the first rows of the *sorted* order, not of source order.
def test_sort_applied_before_size(dataset):
    _, body = dataset("n\n5\n3\n9\n1\n7\n", query_string={"_sort": "n", "_size": 2})
    assert body["rows"] == [[1], [3]]


# Phrase: "Sorting is ... applied before pagination."
# Context: `_offset` walks the sorted order.
def test_sort_applied_before_offset(dataset):
    _, body = dataset(
        "n\n5\n3\n9\n1\n7\n", query_string={"_sort": "n", "_offset": 3}
    )
    assert body["rows"] == [[7], [9]]


# Phrase: "Sorting is ... applied before pagination."
# Context: descending sort plus a window.
def test_sort_desc_applied_before_pagination(dataset):
    _, body = dataset(
        "n\n5\n3\n9\n1\n7\n",
        query_string={"_sort_desc": "n", "_offset": 1, "_size": 2},
    )
    assert body["rows"] == [[7], [5]]


# Phrase: "Empty values ... return `HTTP 400`."
# Context: `_sort` present with an empty value.
def test_empty_sort_is_400(dataset):
    status, body = dataset(CSV, query_string={"_sort": ""})
    assert status == 400
    assert body["ok"] is False


# Phrase: "Empty values ... return `HTTP 400`."
# Context: `_sort_desc` present with an empty value.
def test_empty_sort_desc_is_400(dataset):
    status, body = dataset(CSV, query_string={"_sort_desc": ""})
    assert status == 400
    assert body["ok"] is False


# Phrase: "... or unknown columns return `HTTP 400`."
# Context: a column name that is not in `columns`.
def test_unknown_sort_column_is_400(dataset):
    status, body = dataset(CSV, query_string={"_sort": "nope"})
    assert status == 400
    assert body["ok"] is False


# Phrase: "... or unknown columns return `HTTP 400`."
# Context: the same for `_sort_desc`.
def test_unknown_sort_desc_column_is_400(dataset):
    status, body = dataset(CSV, query_string={"_sort_desc": "nope"})
    assert status == 400
    assert body["ok"] is False


# Phrase: "... unknown columns return `HTTP 400`."
# Context: column matching is exact - case and whitespace variants are unknown.
#          (see AMBIGUITIES T24)
@pytest.mark.parametrize("value", ["NAME", "Name", " name", "name "])
def test_sort_column_match_is_exact(dataset, value):
    status, _ = dataset(CSV, query_string={"_sort": value})
    assert status == 400


# Phrase: "If both are present, `_sort_desc` wins." + "unknown columns return 400"
# Context: chosen reading - both parameters are validated even though only the
#          descending one orders the rows.  (see AMBIGUITIES T25)
def test_invalid_sort_alongside_valid_sort_desc_is_400(dataset):
    status, body = dataset(CSV, query_string={"_sort": "nope", "_sort_desc": "name"})
    assert status == 400
    assert body["ok"] is False


# Phrase: '| `_sort`/`_sort_desc` unknown column | 400 | {"ok": false, "error": ...} |'
# Context: the error envelope.
def test_sort_error_envelope(dataset):
    status, body = dataset(CSV, query_string={"_sort": "nope"})
    assert status == 400
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# ====================================================== response shape ======

# Phrase: "`_shape=lists` (default): `rows` is arrays."
# Context: with no `_shape` parameter at all.
def test_default_shape_is_lists(dataset):
    _, body = dataset(CSV)
    assert all(isinstance(r, list) for r in body["rows"])


# Phrase: "`_shape=lists` (default): `rows` is arrays."
# Context: explicitly requested.
def test_explicit_shape_lists(dataset):
    status, body = dataset(CSV, query_string={"_shape": "lists"})
    assert status == 200
    assert body["rows"] == [["widget", 3], ["gadget", 4]]


# Phrase: "`_shape=objects`: `rows` is objects"
# Context: each row becomes a mapping keyed by column name.
def test_shape_objects_rows_are_objects(dataset):
    status, body = dataset(CSV, query_string={"_shape": "objects"})
    assert status == 200
    assert all(isinstance(r, dict) for r in body["rows"])
    assert body["rows"][0]["name"] == "widget"
    assert body["rows"][0]["qty"] == 3


# Phrase: "`_shape=objects`: ... includes `rowid` (1-based source-file row
#          number, starting at the header)."
# Context: the header is row 1, so the first data row is rowid 2.
def test_shape_objects_rowid_numbering(dataset):
    _, body = dataset(CSV, query_string={"_shape": "objects"})
    assert [r["rowid"] for r in body["rows"]] == [2, 3]


# Phrase: "... `rowid` (1-based source-file row number ...)"
# Context: rowid is an integer.
def test_rowid_is_integer(dataset):
    _, body = dataset(CSV, query_string={"_shape": "objects"})
    assert all(isinstance(r["rowid"], int) for r in body["rows"])


# Phrase: "`rowid` is not in `columns`."
# Context: `columns` stays exactly the source header.
def test_rowid_not_in_columns(dataset):
    _, body = dataset(CSV, query_string={"_shape": "objects"})
    assert body["columns"] == ["name", "qty"]
    assert "rowid" not in body["columns"]


# Phrase: "`rowid` (1-based source-file row number ...)" + "Sorting ... applied
#          before pagination."
# Context: rowid identifies the source row, so sorting carries it along.
def test_rowid_follows_the_row_through_sorting(dataset):
    _, body = dataset(
        SORT_CSV, query_string={"_shape": "objects", "_sort": "name"}
    )
    assert [(r["name"], r["rowid"]) for r in body["rows"]] == [
        ("alpha", 3),
        ("beta", 2),
        ("gamma", 4),
    ]


# Phrase: "`rowid` (1-based source-file row number ...)"
# Context: rowid reflects the source row, not the position within the page.
def test_rowid_survives_offset(dataset):
    _, body = dataset(
        numbers_csv(6), query_string={"_shape": "objects", "_offset": 3, "_size": 2}
    )
    assert [r["rowid"] for r in body["rows"]] == [5, 6]
    assert [r["n"] for r in body["rows"]] == [3, 4]


# Phrase: '| `_shape` not `lists`/`objects` | 400 |'
# Context: any other value, including case variants and the empty string.
@pytest.mark.parametrize("value", ["list", "object", "Lists", "OBJECTS", "", "array"])
def test_invalid_shape_is_400(dataset, value):
    status, body = dataset(CSV, query_string={"_shape": value})
    assert status == 400
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# ==================================================== visibility toggles ====

# Phrase: "`_rowid=hide` removes `rowid`."
# Context: in the objects shape, where rowid would otherwise appear.
def test_rowid_hide_removes_rowid(dataset):
    status, body = dataset(
        CSV, query_string={"_shape": "objects", "_rowid": "hide"}
    )
    assert status == 200
    assert all("rowid" not in r for r in body["rows"])
    assert body["rows"] == [{"name": "widget", "qty": 3}, {"name": "gadget", "qty": 4}]


# Phrase: "`_rowid=hide` removes `rowid`."
# Context: harmless in the lists shape, which never carries rowid.
#          (see AMBIGUITIES T26)
def test_rowid_hide_with_lists_shape_is_ok(dataset):
    status, body = dataset(CSV, query_string={"_rowid": "hide"})
    assert status == 200
    assert body["rows"] == [["widget", 3], ["gadget", 4]]


# Phrase: "`_total=hide` removes `total`."
# Context: the key is absent from the response entirely.
def test_total_hide_removes_total(dataset):
    status, body = dataset(CSV, query_string={"_total": "hide"})
    assert status == 200
    assert "total" not in body
    assert body["ok"] is True


# Phrase: "`_total=hide` removes `total`."
# Context: the rest of the envelope is untouched.
def test_total_hide_keeps_other_keys(dataset):
    _, body = dataset(CSV, query_string={"_total": "hide"})
    assert set(body) >= {"ok", "columns", "rows", "query_ms"}


# Phrase: "`_rowid=hide` removes `rowid`." / "`_total=hide` removes `total`."
# Context: both toggles at once.
def test_both_toggles_together(dataset):
    _, body = dataset(
        CSV, query_string={"_shape": "objects", "_rowid": "hide", "_total": "hide"}
    )
    assert "total" not in body
    assert all("rowid" not in r for r in body["rows"])


# Phrase: "Each toggle is valid only with value `hide`; any other value is `HTTP 400`."
# Context: `_rowid` with anything but `hide`.
@pytest.mark.parametrize("value", ["show", "HIDE", "Hide", "", "true", "1", "no"])
def test_invalid_rowid_value_is_400(dataset, value):
    status, body = dataset(CSV, query_string={"_rowid": value})
    assert status == 400
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# Phrase: "Each toggle is valid only with value `hide`; any other value is `HTTP 400`."
# Context: `_total` with anything but `hide`.
@pytest.mark.parametrize("value", ["show", "HIDE", "", "false", "0"])
def test_invalid_total_value_is_400(dataset, value):
    status, body = dataset(CSV, query_string={"_total": value})
    assert status == 400
    assert body["ok"] is False


# Phrase: "Each toggle is valid only with value `hide` ..."
# Context: an invalid toggle is rejected even in the shape where it is a no-op.
def test_invalid_rowid_value_is_400_in_lists_shape(dataset):
    status, _ = dataset(CSV, query_string={"_shape": "lists", "_rowid": "show"})
    assert status == 400


# ==================================================== repeated parameters ===

# Phrase: "Any repeated control parameter (`_size`, `_offset`, `_shape`,
#          `_sort`, `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`."
# Context: each listed name, repeated with two distinct valid-looking values.
@pytest.mark.parametrize("query", [
    "_size=1&_size=2",
    "_offset=0&_offset=1",
    "_shape=lists&_shape=objects",
    "_sort=name&_sort=qty",
    "_sort_desc=name&_sort_desc=qty",
    "_rowid=hide&_rowid=hide",
    "_total=hide&_total=hide",
])
def test_repeated_control_parameter_is_400(dataset, query):
    status, body = dataset(CSV, query_string=query)
    assert status == 400
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# Phrase: "Any repeated control parameter ... is `HTTP 400`."
# Context: repetition with identical values still counts as repetition.
def test_repeated_identical_values_is_400(dataset):
    status, _ = dataset(CSV, query_string="_size=2&_size=2")
    assert status == 400


# Phrase: "Any repeated control parameter ... is `HTTP 400`."
# Context: three occurrences.
def test_thrice_repeated_is_400(dataset):
    status, _ = dataset(CSV, query_string="_offset=0&_offset=0&_offset=0")
    assert status == 400


# Phrase: "If both are present, `_sort_desc` wins."
# Context: `_sort` plus `_sort_desc` are two *different* parameters, not a repeat.
def test_sort_plus_sort_desc_is_not_a_repeat(dataset):
    status, body = dataset(SORT_CSV, query_string="_sort=name&_sort_desc=name")
    assert status == 200
    assert [r[0] for r in body["rows"]] == ["gamma", "beta", "alpha"]


# Phrase: "Any repeated *control* parameter ... is `HTTP 400`."
# Context: chosen reading - non-control parameters are not policed.
#          (see AMBIGUITIES T27)
def test_repeated_non_control_parameter_is_ignored(dataset):
    status, body = dataset(CSV, query_string="foo=1&foo=2")
    assert status == 200
    assert len(body["rows"]) == 2


# ======================================================== interactions ======

# Phrase: the control parameters compose.
# Context: sort + window + objects shape + total, all at once.
def test_controls_compose(dataset):
    csv = "name,qty\ndelta,4\nalpha,1\ncharlie,3\nbravo,2\n"
    _, body = dataset(
        csv,
        query_string={"_shape": "objects", "_sort_desc": "qty", "_offset": 1, "_size": 2},
    )
    assert body["total"] == 4
    assert [r["name"] for r in body["rows"]] == ["charlie", "bravo"]
    assert [r["rowid"] for r in body["rows"]] == [4, 5]


# Phrase: "`_shape=objects`: `rows` is objects"
# Context: an empty page still returns a (empty) list of rows.
def test_empty_page_in_objects_shape(dataset):
    status, body = dataset(CSV, query_string={"_shape": "objects", "_offset": 99})
    assert status == 200
    assert body["rows"] == []
    assert body["total"] == 2


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`." vs. "If `<id>` is unknown,
#          return `HTTP 404`."
# Context: chosen reading - an unknown dataset is reported before its query is
#          validated.  (see AMBIGUITIES T28)
def test_unknown_dataset_wins_over_bad_control(client):
    resp = client.get("/datasets/deadbeefdeadbeef", query_string={"_size": "0"})
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False
