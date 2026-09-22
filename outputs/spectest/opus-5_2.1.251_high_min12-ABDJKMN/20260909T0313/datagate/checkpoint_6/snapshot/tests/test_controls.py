"""Spec section: Pagination, Sorting, and Response Controls.

`GET /datasets/<id>` accepts control parameters for pagination, sorting, and
shape.
"""

import pytest

# 5 rows, deliberately out of order and mixing widths so that a lexicographic
# sort differs from a numeric one.
BASIC = "name,age\ncarol,9\nalice,30\nerin,41\nbob,10\ndan,2\n"
BASIC_ROWS = [["carol", 9], ["alice", 30], ["erin", 41], ["bob", 10], ["dan", 2]]

CONTROLS = ["_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total"]


@pytest.fixture
def endpoint(convert, client, origin):
    """Ingest a CSV once and return `get(query_string) -> response`."""

    def _endpoint(path, body=BASIC, **kwargs):
        response = convert(path, body, **kwargs)
        assert response.status_code == 200, response.get_data(as_text=True)
        url = response.get_json()["endpoint"]

        def get(query=None):
            return client.get(url, query_string=query or {})

        return get

    return _endpoint


def numbered(count, prefix="/gen"):
    """A CSV with `count` data rows: i,v = 0,0 / 1,2 / 2,4 ..."""
    return "i,v\n" + "".join("{},{}\n".format(i, i * 2) for i in range(count))


# ==========================================================================
# `total`
# ==========================================================================


# Phrase: "Responses include integer `total` for the row count before pagination."
def test_total_present_and_integer(endpoint):
    payload = endpoint("/t-basic.csv")().get_json()
    assert "total" in payload
    assert isinstance(payload["total"], int)
    assert not isinstance(payload["total"], bool)
    assert payload["total"] == 5


# Phrase: "`total` for the row count before pagination."
# Context: `_size` truncates `rows` but must not change `total`.
def test_total_ignores_size(endpoint):
    payload = endpoint("/t-size.csv", numbered(40))({"_size": "3"}).get_json()
    assert len(payload["rows"]) == 3
    assert payload["total"] == 40


# Phrase: "`total` for the row count before pagination."
# Context: `_offset` likewise does not reduce `total`.
def test_total_ignores_offset(endpoint):
    payload = endpoint("/t-offset.csv", numbered(40))({"_offset": "35"}).get_json()
    assert len(payload["rows"]) == 5
    assert payload["total"] == 40


# Phrase: "`total` for the row count before pagination."
# Context: the default 100-row page does not cap `total`.
def test_total_exceeds_default_page(endpoint):
    payload = endpoint("/t-big.csv", numbered(250))().get_json()
    assert payload["total"] == 250
    assert len(payload["rows"]) == 100


# Phrase: "Responses include integer `total`" -- also under `_shape=objects`.
def test_total_present_for_objects_shape(endpoint):
    payload = endpoint("/t-obj.csv")({"_shape": "objects"}).get_json()
    assert payload["total"] == 5


# ==========================================================================
# Pagination -- `_size`
# ==========================================================================


# Phrase: "`_size` (positive integer, default `100`) limits returned rows."
def test_size_limits_rows(endpoint):
    payload = endpoint("/s-limit.csv")({"_size": "2"}).get_json()
    assert payload["rows"] == BASIC_ROWS[:2]


# Phrase: "`_size` ... default `100`"
def test_size_defaults_to_100(endpoint):
    payload = endpoint("/s-default.csv", numbered(150))().get_json()
    assert len(payload["rows"]) == 100
    assert payload["rows"][0] == [0, 0]
    assert payload["rows"][-1] == [99, 198]


# Phrase: "`_size` ... limits returned rows."
# Context: `_size=1` returns exactly the first row.
def test_size_one(endpoint):
    payload = endpoint("/s-one.csv")({"_size": "1"}).get_json()
    assert payload["rows"] == [BASIC_ROWS[0]]


# Phrase: "If it exceeds available rows, return all."
def test_size_larger_than_available_returns_all(endpoint):
    payload = endpoint("/s-over.csv")({"_size": "500"}).get_json()
    assert payload["rows"] == BASIC_ROWS


# Phrase: "If it exceeds available rows, return all."
# Context (T18): `_size` above 100 is honoured, not clamped back to 100.
def test_size_above_100_is_not_clamped(endpoint):
    payload = endpoint("/s-200.csv", numbered(250))({"_size": "200"}).get_json()
    assert len(payload["rows"]) == 200
    assert payload["rows"][-1] == [199, 398]


# Phrase: "`_size` ... limits returned rows."
# Context: exactly the available row count.
def test_size_equal_to_available(endpoint):
    payload = endpoint("/s-exact.csv")({"_size": "5"}).get_json()
    assert payload["rows"] == BASIC_ROWS


# ==========================================================================
# Pagination -- `_offset`
# ==========================================================================


# Phrase: "`_offset` (non-negative integer, default `0`) skips that many rows
# before returning."
def test_offset_skips_rows(endpoint):
    payload = endpoint("/o-skip.csv")({"_offset": "2"}).get_json()
    assert payload["rows"] == BASIC_ROWS[2:]


# Phrase: "`_offset` ... default `0`"
def test_offset_defaults_to_zero(endpoint):
    payload = endpoint("/o-default.csv")().get_json()
    assert payload["rows"] == BASIC_ROWS


# Phrase: "`_offset` ... default `0`" -- an explicit 0 matches the default.
def test_offset_zero_explicit(endpoint):
    payload = endpoint("/o-zero.csv")({"_offset": "0"}).get_json()
    assert payload["rows"] == BASIC_ROWS


# Phrase: "`_offset` ... skips that many rows before returning."
# Context: offset past the end yields an empty page, not an error.
def test_offset_past_end_is_empty(endpoint):
    payload = endpoint("/o-past.csv")({"_offset": "99"}).get_json()
    assert payload["rows"] == []
    assert payload["total"] == 5


# Phrase: `_size` + `_offset` together -- offset applied, then size.
def test_size_and_offset_together(endpoint):
    payload = endpoint("/o-both.csv")({"_offset": "1", "_size": "2"}).get_json()
    assert payload["rows"] == BASIC_ROWS[1:3]


# Phrase: `_size` + `_offset` -- a window that runs off the end is truncated.
def test_offset_window_truncated_at_end(endpoint):
    payload = endpoint("/o-tail.csv")({"_offset": "4", "_size": "10"}).get_json()
    assert payload["rows"] == BASIC_ROWS[4:]


# ==========================================================================
# Pagination -- "Invalid `_size`/`_offset` -> `HTTP 400`."
# ==========================================================================


def assert_error(response, status=400):
    assert response.status_code == status, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    return payload


# Phrase: "Invalid `_size` -> `HTTP 400`." / "`_size` not a positive integer | 400"
@pytest.mark.parametrize("value", ["0", "-1", "-100", "abc", "1.5", "1e2", "0x5"])
def test_invalid_size_is_400(endpoint, value):
    assert_error(endpoint("/s-bad-{}.csv".format(value))({"_size": value}))


# Phrase: "`_size` not a positive integer | 400 | {"ok": false, "error": "<message>"}"
def test_invalid_size_error_envelope(endpoint):
    payload = assert_error(endpoint("/s-env.csv")({"_size": "0"}))
    assert set(payload) >= {"ok", "error"}
    assert "rows" not in payload


# Phrase: "Invalid `_size` -> 400" -- context (T17): empty value is invalid.
def test_empty_size_is_400(endpoint):
    assert_error(endpoint("/s-empty.csv")({"_size": ""}))


# Phrase: "Invalid `_size` -> 400" -- context (T17): no underscores/unicode digits.
@pytest.mark.parametrize("value", ["1_0", "５", " "])
def test_non_ascii_integer_size_is_400(endpoint, value):
    assert_error(endpoint("/s-grammar.csv")({"_size": value}))


# Phrase: "`_size` (positive integer ...)" -- context (T17): `+5` is accepted.
def test_size_accepts_leading_plus(endpoint):
    payload = endpoint("/s-plus.csv")({"_size": "+2"}).get_json()
    assert payload["rows"] == BASIC_ROWS[:2]


# Phrase: "Invalid `_offset` -> `HTTP 400`."
# / "`_offset` not a non-negative integer | 400"
@pytest.mark.parametrize("value", ["-1", "-5", "abc", "2.0", "", "1_0"])
def test_invalid_offset_is_400(endpoint, value):
    assert_error(endpoint("/o-bad.csv")({"_offset": value}))


# Phrase: "`_offset` (non-negative integer ...)" -- context (T17): `-0` is zero.
def test_offset_minus_zero_is_accepted(endpoint):
    payload = endpoint("/o-negzero.csv")({"_offset": "-0"}).get_json()
    assert payload["rows"] == BASIC_ROWS


# ==========================================================================
# Sorting
# ==========================================================================

SORTABLE = "name,age\ncarol,9\nalice,30\nerin,41\nbob,10\ndan,2\n"


# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
def test_sort_ascending_by_text_column(endpoint):
    payload = endpoint("/sort-name.csv")({"_sort": "name"}).get_json()
    assert [row[0] for row in payload["rows"]] == [
        "alice",
        "bob",
        "carol",
        "dan",
        "erin",
    ]


# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
# Context: a numeric column sorts numerically, not lexicographically (T20).
def test_sort_ascending_by_numeric_column(endpoint):
    payload = endpoint("/sort-age.csv")({"_sort": "age"}).get_json()
    assert [row[1] for row in payload["rows"]] == [2, 9, 10, 30, 41]


# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
def test_sort_desc_by_numeric_column(endpoint):
    payload = endpoint("/sortd-age.csv")({"_sort_desc": "age"}).get_json()
    assert [row[1] for row in payload["rows"]] == [41, 30, 10, 9, 2]


# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
def test_sort_desc_by_text_column(endpoint):
    payload = endpoint("/sortd-name.csv")({"_sort_desc": "name"}).get_json()
    assert [row[0] for row in payload["rows"]] == [
        "erin",
        "dan",
        "carol",
        "bob",
        "alice",
    ]


# Phrase: "If both are present, `_sort_desc` wins."
def test_sort_desc_wins_over_sort(endpoint):
    payload = endpoint("/sort-both.csv")(
        {"_sort": "name", "_sort_desc": "age"}
    ).get_json()
    assert [row[1] for row in payload["rows"]] == [41, 30, 10, 9, 2]


# Phrase: "If both are present, `_sort_desc` wins."
# Context: same column in both -- descending order results.
def test_sort_desc_wins_same_column(endpoint):
    payload = endpoint("/sort-both-same.csv")(
        {"_sort": "age", "_sort_desc": "age"}
    ).get_json()
    assert [row[1] for row in payload["rows"]] == [41, 30, 10, 9, 2]


# Phrase: "Sorting is stable"
# Context: ties keep source order under `_sort`.
def test_sort_is_stable_ascending(endpoint):
    csv_text = "grp,tag\nb,1\na,2\nb,3\na,4\nb,5\n"
    payload = endpoint("/stable-asc.csv", csv_text)({"_sort": "grp"}).get_json()
    assert payload["rows"] == [
        ["a", 2],
        ["a", 4],
        ["b", 1],
        ["b", 3],
        ["b", 5],
    ]


# Phrase: "Sorting is stable"
# Context: ties keep source order under `_sort_desc` too -- a descending sort
# reverses the keys, not the tied rows.
def test_sort_is_stable_descending(endpoint):
    csv_text = "grp,tag\nb,1\na,2\nb,3\na,4\nb,5\n"
    payload = endpoint("/stable-desc.csv", csv_text)({"_sort_desc": "grp"}).get_json()
    assert payload["rows"] == [
        ["b", 1],
        ["b", 3],
        ["b", 5],
        ["a", 2],
        ["a", 4],
    ]


# Phrase: "Sorting is ... applied before pagination."
def test_sort_applied_before_size(endpoint):
    payload = endpoint("/sort-page.csv")({"_sort": "age", "_size": "2"}).get_json()
    assert payload["rows"] == [["dan", 2], ["carol", 9]]


# Phrase: "Sorting is ... applied before pagination."
# Context: `_offset` indexes into the sorted order.
def test_sort_applied_before_offset(endpoint):
    payload = endpoint("/sort-off.csv")(
        {"_sort": "age", "_offset": "3", "_size": "1"}
    ).get_json()
    assert payload["rows"] == [["alice", 30]]


# Phrase: "Sorting is ... applied before pagination."
# Context: descending sort + window.
def test_sort_desc_applied_before_pagination(endpoint):
    payload = endpoint("/sortd-page.csv")(
        {"_sort_desc": "age", "_offset": "1", "_size": "2"}
    ).get_json()
    assert payload["rows"] == [["alice", 30], ["bob", 10]]


# Phrase: "Sorting is ... applied before pagination."
# Context: sorting does not change `total`.
def test_sort_does_not_change_total(endpoint):
    payload = endpoint("/sort-total.csv")({"_sort": "age", "_size": "1"}).get_json()
    assert payload["total"] == 5


# Phrase: "Empty values ... return `HTTP 400`."
def test_empty_sort_is_400(endpoint):
    assert_error(endpoint("/sort-empty.csv")({"_sort": ""}))


# Phrase: "Empty values ... return `HTTP 400`."
def test_empty_sort_desc_is_400(endpoint):
    assert_error(endpoint("/sortd-empty.csv")({"_sort_desc": ""}))


# Phrase: "... or unknown columns return `HTTP 400`."
# / "`_sort`/`_sort_desc` unknown column | 400"
def test_unknown_sort_column_is_400(endpoint):
    payload = assert_error(endpoint("/sort-unknown.csv")({"_sort": "nope"}))
    assert payload["ok"] is False


# Phrase: "... or unknown columns return `HTTP 400`."
def test_unknown_sort_desc_column_is_400(endpoint):
    assert_error(endpoint("/sortd-unknown.csv")({"_sort_desc": "nope"}))


# Phrase: "... unknown columns return `HTTP 400`."
# Context: column matching is case-sensitive, as `columns` is echoed verbatim.
def test_sort_column_is_case_sensitive(endpoint):
    assert_error(endpoint("/sort-case.csv")({"_sort": "NAME"}))


# Phrase: "... unknown columns return `HTTP 400`."
# Context (T21): `rowid` is not in `columns`, so it is not a sortable column.
def test_sort_by_rowid_is_400(endpoint):
    assert_error(endpoint("/sort-rowid.csv")({"_sort": "rowid"}))


# Phrase: "If both are present, `_sort_desc` wins."
# Context (T19): the losing parameter is not validated.
def test_invalid_sort_ignored_when_sort_desc_present(endpoint):
    response = endpoint("/sort-loser.csv")({"_sort": "nope", "_sort_desc": "age"})
    assert response.status_code == 200
    assert [row[1] for row in response.get_json()["rows"]] == [41, 30, 10, 9, 2]


# Phrase: "If both are present, `_sort_desc` wins."
# Context (T19): an empty losing `_sort` is likewise not validated.
def test_empty_sort_ignored_when_sort_desc_present(endpoint):
    response = endpoint("/sort-loser2.csv")({"_sort": "", "_sort_desc": "name"})
    assert response.status_code == 200
    assert [row[0] for row in response.get_json()["rows"]][0] == "erin"


# Phrase: "`_sort=<column>` sorts ascending" -- context (T20): a column mixing
# numbers and text has a total order; numbers precede strings.
def test_sort_mixed_types_orders_numbers_first(endpoint):
    csv_text = "k,v\nzebra,1\n10,2\napple,3\n2,4\n"
    payload = endpoint("/sort-mixed.csv", csv_text)({"_sort": "k"}).get_json()
    assert [row[0] for row in payload["rows"]] == [2, 10, "apple", "zebra"]


# Phrase: "`_sort=<column>` sorts ascending" -- context: empty cells sort first
# among the text values.
def test_sort_with_empty_cells(endpoint):
    csv_text = "k,v\nb,1\n,2\na,3\n"
    payload = endpoint("/sort-blank.csv", csv_text)({"_sort": "k"}).get_json()
    assert [row[0] for row in payload["rows"]] == ["", "a", "b"]


# Phrase: sorting works with `_shape=objects` as well.
def test_sort_with_objects_shape(endpoint):
    payload = endpoint("/sort-obj.csv")(
        {"_sort": "age", "_shape": "objects"}
    ).get_json()
    assert [row["age"] for row in payload["rows"]] == [2, 9, 10, 30, 41]


# ==========================================================================
# Response shape
# ==========================================================================


# Phrase: "`_shape=lists` (default): `rows` is arrays."
def test_default_shape_is_lists(endpoint):
    payload = endpoint("/sh-default.csv")().get_json()
    assert all(isinstance(row, list) for row in payload["rows"])
    assert payload["rows"] == BASIC_ROWS


# Phrase: "`_shape=lists` (default): `rows` is arrays."
def test_explicit_shape_lists(endpoint):
    payload = endpoint("/sh-lists.csv")({"_shape": "lists"}).get_json()
    assert payload["rows"] == BASIC_ROWS


# Phrase: "`_shape=lists` (default): `rows` is arrays."
# Context: the lists shape carries no `rowid`.
def test_lists_shape_has_no_rowid(endpoint):
    payload = endpoint("/sh-lists-norowid.csv")({"_shape": "lists"}).get_json()
    for row in payload["rows"]:
        assert len(row) == len(payload["columns"])


# Phrase: "`_shape=objects`: `rows` is objects"
def test_objects_shape_rows_are_objects(endpoint):
    payload = endpoint("/sh-obj.csv")({"_shape": "objects"}).get_json()
    assert all(isinstance(row, dict) for row in payload["rows"])
    assert payload["rows"][0]["name"] == "carol"
    assert payload["rows"][0]["age"] == 9


# Phrase: "`_shape=objects`: `rows` is objects ... and includes `rowid`"
def test_objects_shape_includes_rowid(endpoint):
    payload = endpoint("/sh-rowid.csv")({"_shape": "objects"}).get_json()
    for row in payload["rows"]:
        assert "rowid" in row
        assert isinstance(row["rowid"], int)


# Phrase: "`rowid` (1-based source-file row number)"
# Context (T16): the first data row is 1.
def test_rowid_is_one_based(endpoint):
    payload = endpoint("/sh-rowid1.csv")({"_shape": "objects"}).get_json()
    assert [row["rowid"] for row in payload["rows"]] == [1, 2, 3, 4, 5]


# Phrase: "`rowid` (1-based source-file row number)"
# Context (T16): rowid follows the source file, so sorting does not renumber.
def test_rowid_survives_sorting(endpoint):
    payload = endpoint("/sh-rowid-sort.csv")(
        {"_shape": "objects", "_sort": "age"}
    ).get_json()
    assert [(row["name"], row["rowid"]) for row in payload["rows"]] == [
        ("dan", 5),
        ("carol", 1),
        ("bob", 4),
        ("alice", 2),
        ("erin", 3),
    ]


# Phrase: "`rowid` (1-based source-file row number)"
# Context (T16): pagination does not renumber either.
def test_rowid_survives_offset(endpoint):
    payload = endpoint("/sh-rowid-off.csv")(
        {"_shape": "objects", "_offset": "3"}
    ).get_json()
    assert [row["rowid"] for row in payload["rows"]] == [4, 5]


# Phrase: "`rowid` is not in `columns`."
def test_rowid_not_in_columns(endpoint):
    payload = endpoint("/sh-cols.csv")({"_shape": "objects"}).get_json()
    assert payload["columns"] == ["name", "age"]
    assert "rowid" not in payload["columns"]


# Phrase: "`_shape` not `lists`/`objects` | 400"
@pytest.mark.parametrize("value", ["arrays", "object", "list", "", "LISTS", "dict"])
def test_invalid_shape_is_400(endpoint, value):
    assert_error(endpoint("/sh-bad.csv")({"_shape": value}))


# Phrase: "`_shape` not `lists`/`objects` | 400 | {"ok": false, "error": ...}"
def test_invalid_shape_error_envelope(endpoint):
    payload = assert_error(endpoint("/sh-env.csv")({"_shape": "nope"}))
    assert payload["ok"] is False
    assert isinstance(payload["error"], str)


# ==========================================================================
# Visibility toggles
# ==========================================================================


# Phrase: "`_rowid=hide` removes `rowid`."
def test_rowid_hide_removes_rowid_from_objects(endpoint):
    payload = endpoint("/v-rowid.csv")(
        {"_shape": "objects", "_rowid": "hide"}
    ).get_json()
    for row in payload["rows"]:
        assert "rowid" not in row
        assert set(row) == {"name", "age"}


# Phrase: "`_rowid=hide` removes `rowid`."
# Context (T23): harmless under the default lists shape.
def test_rowid_hide_is_ok_with_lists_shape(endpoint):
    response = endpoint("/v-rowid-lists.csv")({"_rowid": "hide"})
    assert response.status_code == 200
    assert response.get_json()["rows"] == BASIC_ROWS


# Phrase: "`_total=hide` removes `total`."
def test_total_hide_removes_total(endpoint):
    payload = endpoint("/v-total.csv")({"_total": "hide"}).get_json()
    assert "total" not in payload
    assert payload["rows"] == BASIC_ROWS


# Phrase: "`_total=hide` removes `total`." -- context: also under objects shape.
def test_total_hide_with_objects_shape(endpoint):
    payload = endpoint("/v-total-obj.csv")(
        {"_total": "hide", "_shape": "objects"}
    ).get_json()
    assert "total" not in payload


# Phrase: both toggles at once.
def test_both_toggles_together(endpoint):
    payload = endpoint("/v-both.csv")(
        {"_shape": "objects", "_rowid": "hide", "_total": "hide"}
    ).get_json()
    assert "total" not in payload
    assert all("rowid" not in row for row in payload["rows"])


# Phrase: "Each toggle is valid only with value `hide`; any other value is
# `HTTP 400`." / "invalid `_rowid`/`_total` value | 400"
@pytest.mark.parametrize("value", ["show", "true", "1", "", "HIDE", "hidden", "no"])
def test_invalid_rowid_value_is_400(endpoint, value):
    assert_error(endpoint("/v-rowid-bad.csv")({"_rowid": value}))


# Phrase: "Each toggle is valid only with value `hide`; any other value is 400."
@pytest.mark.parametrize("value", ["show", "false", "0", "", "Hide", "hide "])
def test_invalid_total_value_is_400(endpoint, value):
    assert_error(endpoint("/v-total-bad.csv")({"_total": value}))


# Phrase: "invalid `_rowid`/`_total` value | 400 | {"ok": false, "error": ...}"
def test_invalid_toggle_error_envelope(endpoint):
    payload = assert_error(endpoint("/v-env.csv")({"_rowid": "show"}))
    assert payload["ok"] is False
    assert isinstance(payload["error"], str)


# ==========================================================================
# Repeated control parameters
# ==========================================================================

REPEATED = {
    "_size": "_size=2&_size=3",
    "_offset": "_offset=0&_offset=1",
    "_shape": "_shape=lists&_shape=objects",
    "_sort": "_sort=name&_sort=age",
    "_sort_desc": "_sort_desc=name&_sort_desc=age",
    "_rowid": "_rowid=hide&_rowid=hide",
    "_total": "_total=hide&_total=hide",
}


# Phrase: "Any repeated control parameter (`_size`, `_offset`, `_shape`,
# `_sort`, `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`."
@pytest.mark.parametrize("name", CONTROLS)
def test_repeated_control_parameter_is_400(endpoint, name):
    assert_error(endpoint("/r-{}.csv".format(name))(REPEATED[name]))


# Phrase: "Any repeated control parameter ... is `HTTP 400`."
# Context (T24): identical repeated values are still an error.
def test_repeated_identical_values_is_400(endpoint):
    assert_error(endpoint("/r-same.csv")("_size=2&_size=2"))


# Phrase: "Any repeated control parameter ... is `HTTP 400`."
# Context (T24): a repeat whose second occurrence is empty is still an error.
def test_repeated_with_empty_second_value_is_400(endpoint):
    assert_error(endpoint("/r-empty.csv")("_size=2&_size="))


# Phrase: "Any repeated control parameter ... is `HTTP 400`."
# Context: three occurrences.
def test_repeated_three_times_is_400(endpoint):
    assert_error(endpoint("/r-three.csv")("_offset=0&_offset=0&_offset=0"))


# Phrase: "Any repeated control parameter ... is `HTTP 400`."
# Context: repeating `_sort` and `_sort_desc` is still an error even though
# `_sort_desc` would otherwise win.
def test_repeated_sort_with_sort_desc_present_is_400(endpoint):
    assert_error(endpoint("/r-sortpair.csv")("_sort=name&_sort=age&_sort_desc=age"))


# Phrase: "Any repeated control parameter (<the seven listed>) is 400."
# Context (T24): only those seven names are policed.
def test_repeated_non_control_parameter_is_allowed(endpoint):
    response = endpoint("/r-other.csv")("foo=1&foo=2")
    assert response.status_code == 200


# Phrase: repeating a control parameter beats other validation -- still 400.
def test_repeated_and_invalid_is_still_400(endpoint):
    assert_error(endpoint("/r-mixed.csv")("_size=0&_size=0"))


# ==========================================================================
# Error handling -- envelope and interactions
# ==========================================================================


# Phrase: error table -- every 400 row uses `{"ok": false, "error": "<message>"}`.
@pytest.mark.parametrize(
    "query",
    [
        {"_size": "0"},
        {"_offset": "-1"},
        {"_shape": "nope"},
        {"_rowid": "show"},
        {"_total": "show"},
        {"_sort": "nope"},
        {"_sort_desc": "nope"},
        "_size=1&_size=2",
    ],
)
def test_every_documented_400_uses_the_envelope(endpoint, query):
    payload = assert_error(endpoint("/e-envelope.csv")(query))
    assert set(payload) == {"ok", "error"}


# Phrase: "If `<id>` is unknown, return `HTTP 404`." + control validation.
# Context (T22): the dataset lookup happens first.
def test_unknown_id_with_invalid_control_is_404(client):
    response = client.get("/datasets/nope", query_string={"_size": "0"})
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: controls do not disturb the rest of the documented response body.
def test_controls_keep_ok_columns_and_query_ms(endpoint):
    payload = endpoint("/e-body.csv")(
        {"_sort_desc": "age", "_size": "2", "_offset": "1", "_shape": "objects"}
    ).get_json()
    assert payload["ok"] is True
    assert payload["columns"] == ["name", "age"]
    assert isinstance(payload["query_ms"], (int, float))
    assert payload["total"] == 5


# Phrase: all controls combined behave as sort -> offset -> size -> shape.
def test_all_controls_combined(endpoint):
    payload = endpoint("/e-all.csv")(
        {
            "_sort_desc": "age",
            "_offset": "1",
            "_size": "2",
            "_shape": "objects",
            "_total": "hide",
        }
    ).get_json()
    assert "total" not in payload
    assert payload["rows"] == [
        {"name": "alice", "age": 30, "rowid": 2},
        {"name": "bob", "age": 10, "rowid": 4},
    ]
