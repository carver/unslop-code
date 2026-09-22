"""Spec section: `total` and Pagination."""

import pytest

CSV = "name,score\n" + "".join(f"row{i},{i}\n" for i in range(250))
SMALL = "name,score\nada,3\ngrace,1\nlin,2\n"


# Phrase: "Responses include integer `total` for the row count before pagination."
def test_total_is_the_row_count(converted):
    body = converted(SMALL).get_json()

    assert body["total"] == 3
    assert isinstance(body["total"], int)


# Phrase: "`total` for the row count before pagination." -- context: unaffected by `_size`/`_offset`.
def test_total_ignores_pagination(converted):
    body = converted(CSV, query="?_size=5&_offset=10").get_json()

    assert body["total"] == 250
    assert len(body["rows"]) == 5


# Phrase: "`_size` (positive integer, default `100`) limits returned rows."
def test_size_limits_rows(converted):
    body = converted(CSV, query="?_size=7").get_json()

    assert len(body["rows"]) == 7
    assert body["rows"][0] == ["row0", 0]


# Phrase: "`_size` (positive integer, default `100`)" -- context: the default.
def test_size_defaults_to_100(converted):
    body = converted(CSV).get_json()

    assert len(body["rows"]) == 100


# Phrase: "If it exceeds available rows, return all."
def test_size_beyond_available_rows_returns_all(converted):
    body = converted(SMALL, query="?_size=999").get_json()

    assert len(body["rows"]) == 3


# Phrase: "`_offset` (non-negative integer, default `0`) skips that many rows before returning."
def test_offset_skips_rows(converted):
    body = converted(CSV, query="?_offset=3&_size=2").get_json()

    assert body["rows"] == [["row3", 3], ["row4", 4]]


# Phrase: "`_offset` (non-negative integer, default `0`)" -- context: the default.
def test_offset_defaults_to_zero(converted):
    body = converted(SMALL).get_json()

    assert body["rows"][0] == ["ada", 3]


# Phrase: "`_offset` ... skips that many rows" -- context: past the end (AMBIGUITIES T21).
def test_offset_past_the_end_is_an_empty_page(converted):
    response = converted(SMALL, query="?_offset=99")

    assert response.status_code == 200
    body = response.get_json()
    assert body["rows"] == []
    assert body["total"] == 3


# Phrase: "`_offset` (non-negative integer ...)" -- context: zero is allowed.
def test_offset_zero_is_valid(converted):
    response = converted(SMALL, query="?_offset=0")

    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 3


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`."
@pytest.mark.parametrize("query", ["?_size=0", "?_size=-1", "?_size=abc", "?_size=", "?_size=1.5"])
def test_invalid_size_is_400(converted, query):
    response = converted(SMALL, query=query)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Invalid `_size`/`_offset` -> `HTTP 400`."
@pytest.mark.parametrize("query", ["?_offset=-1", "?_offset=abc", "?_offset=", "?_offset=2.0"])
def test_invalid_offset_is_400(converted, query):
    response = converted(SMALL, query=query)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
