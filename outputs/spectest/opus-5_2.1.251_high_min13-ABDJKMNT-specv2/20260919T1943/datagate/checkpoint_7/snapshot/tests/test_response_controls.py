"""Spec section: Response shape, visibility toggles and repeated control parameters."""

import pytest

from conftest import SIMPLE_CSV

CONTROL_PARAMETERS = ["_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total"]


# Phrase: "`_shape=lists` (default): `rows` is arrays."
def test_lists_is_the_default_shape(query):
    body = query("", SIMPLE_CSV).get_json()

    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`_shape=lists` (default): `rows` is arrays."
def test_shape_lists_is_explicit_arrays(query):
    body = query("?_shape=lists", SIMPLE_CSV).get_json()

    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`_shape=objects`: `rows` is objects and includes `rowid`"
def test_shape_objects_returns_objects_with_rowid(query):
    body = query("?_shape=objects", SIMPLE_CSV).get_json()

    assert body["rows"] == [
        {"rowid": 2, "name": "ada", "age": 36},
        {"rowid": 3, "name": "grace", "age": 45},
    ]


# Phrase: "`rowid` (1-based source-file row number, starting at the header)" (context: T18)
def test_rowid_counts_the_header_as_row_one(query):
    body = query("?_shape=objects", "a\n1\n2\n3\n").get_json()

    assert [row["rowid"] for row in body["rows"]] == [2, 3, 4]


# Phrase: "1-based source-file row number" (context: T26 — skipped source lines keep their numbers)
def test_rowid_follows_the_source_file_line(query):
    body = query("?_shape=objects", "a\n1\n\n2\n").get_json()

    assert [row["rowid"] for row in body["rows"]] == [2, 4]


# Phrase: "`rowid` ... source-file row number" (context: rowid survives sorting and paging)
def test_rowid_travels_with_its_row(query):
    body = query("?_shape=objects&_sort_desc=name&_size=1", SIMPLE_CSV).get_json()

    assert body["rows"] == [{"rowid": 3, "name": "grace", "age": 45}]


# Phrase: "`rowid` is not in `columns`."
def test_rowid_is_not_a_column(query):
    body = query("?_shape=objects", SIMPLE_CSV).get_json()

    assert body["columns"] == ["name", "age"]


# Phrase: "`rowid` is not in `columns`." (context: T19 — list rows carry no rowid either)
def test_list_rows_do_not_carry_a_rowid(query):
    body = query("?_shape=lists", SIMPLE_CSV).get_json()

    assert body["rows"] == [["ada", 36], ["grace", 45]]
    assert body["columns"] == ["name", "age"]


# Phrase: "| `_shape` not `lists`/`objects` | 400 |"
@pytest.mark.parametrize("raw", ["arrays", "Objects", "", "object", "lists,objects"])
def test_invalid_shape_is_400(query, raw):
    response = query(f"?_shape={raw}", SIMPLE_CSV)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "`_rowid=hide` removes `rowid`."
def test_rowid_hide_removes_rowid(query):
    body = query("?_shape=objects&_rowid=hide", SIMPLE_CSV).get_json()

    assert body["rows"] == [{"name": "ada", "age": 36}, {"name": "grace", "age": 45}]


# Phrase: "`_rowid=hide` removes `rowid`." (context: T19 — nothing to remove from list rows)
def test_rowid_hide_is_accepted_for_list_rows(query):
    response = query("?_rowid=hide", SIMPLE_CSV)

    assert response.status_code == 200
    assert response.get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`_total=hide` removes `total`."
def test_total_hide_removes_total(query):
    body = query("?_total=hide", SIMPLE_CSV).get_json()

    assert "total" not in body
    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Each toggle is valid only with value `hide`; any other value is `HTTP 400`."
@pytest.mark.parametrize("parameter", ["_rowid", "_total"])
@pytest.mark.parametrize("raw", ["show", "Hide", "", "1", "true"])
def test_invalid_toggle_value_is_400(query, parameter, raw):
    response = query(f"?{parameter}={raw}", SIMPLE_CSV)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "Any repeated control parameter (...) is `HTTP 400`."
@pytest.mark.parametrize("parameter", CONTROL_PARAMETERS)
def test_repeated_control_parameter_is_400(query, parameter):
    valid = {"_size": "2", "_offset": "0", "_shape": "lists", "_sort": "name", "_sort_desc": "name", "_rowid": "hide", "_total": "hide"}[parameter]

    response = query(f"?{parameter}={valid}&{parameter}={valid}", SIMPLE_CSV)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Any repeated control parameter ... is 400." (context: T23 — repeats with different values too)
def test_repeated_control_parameter_with_different_values_is_400(query):
    response = query("?_size=1&_size=2", SIMPLE_CSV)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Any repeated control parameter ... is 400." (context: T24 — other parameters are ignored)
def test_repeated_non_control_parameter_is_ignored(query):
    response = query("?limit=1&limit=2", SIMPLE_CSV)

    assert response.status_code == 200
    assert response.get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: whole control section (context: controls combine)
def test_controls_combine(query):
    body = query("?_shape=objects&_sort_desc=age&_size=1&_offset=1&_total=hide", SIMPLE_CSV).get_json()

    assert body["rows"] == [{"rowid": 2, "name": "ada", "age": 36}]
    assert "total" not in body
