"""Spec section: `total` and Pagination (`_size`, `_offset`)."""

import pytest

from conftest import SIMPLE_CSV

NUMBERED = "n\n" + "".join(f"{i}\n" for i in range(150))


# Phrase: "Responses include integer `total` for the row count before pagination."
def test_total_is_the_row_count(query):
    body = query("", SIMPLE_CSV).get_json()

    assert body["total"] == 2
    assert isinstance(body["total"], int)


# Phrase: "integer `total` for the row count before pagination" (context: paging does not shrink it)
def test_total_ignores_pagination(query):
    body = query("?_size=5&_offset=20", NUMBERED).get_json()

    assert body["total"] == 150
    assert len(body["rows"]) == 5


# Phrase: "`_size` (positive integer, default `100`) limits returned rows."
def test_size_limits_returned_rows(query):
    body = query("?_size=5", NUMBERED).get_json()

    assert body["rows"] == [[0], [1], [2], [3], [4]]


# Phrase: "`_size` (positive integer, default `100`)"
def test_size_defaults_to_100(query):
    body = query("", NUMBERED).get_json()

    assert len(body["rows"]) == 100
    assert body["rows"][-1] == [99]


# Phrase: "If it exceeds available rows, return all."
def test_size_larger_than_the_table_returns_every_row(query):
    body = query("?_size=1000", SIMPLE_CSV).get_json()

    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`_offset` (non-negative integer, default `0`) skips that many rows before returning."
def test_offset_skips_rows(query):
    body = query("?_offset=3&_size=2", NUMBERED).get_json()

    assert body["rows"] == [[3], [4]]


# Phrase: "`_offset` ... default `0`"
def test_offset_defaults_to_zero(query):
    body = query("?_size=1", NUMBERED).get_json()

    assert body["rows"] == [[0]]


# Phrase: "`_offset` ... skips that many rows" (context: past the end yields no rows)
def test_offset_beyond_the_table_returns_no_rows(query):
    body = query("?_offset=500", NUMBERED).get_json()

    assert body["rows"] == []
    assert body["total"] == 150


# Phrase: "`_offset` (non-negative integer ...)" (context: zero is allowed)
def test_offset_zero_is_valid(query):
    response = query("?_offset=0", SIMPLE_CSV)

    assert response.status_code == 200
    assert response.get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`." / "`_size` not a positive integer | 400"
@pytest.mark.parametrize("raw", ["0", "-1", "abc", "1.5", "", "5x", "1e3"])
def test_invalid_size_is_400(query, raw):
    response = query(f"?_size={raw}", SIMPLE_CSV)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`." / "`_offset` not a non-negative integer | 400"
@pytest.mark.parametrize("raw", ["-1", "abc", "2.5", "", "x7"])
def test_invalid_offset_is_400(query, raw):
    response = query(f"?_offset={raw}", SIMPLE_CSV)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)
