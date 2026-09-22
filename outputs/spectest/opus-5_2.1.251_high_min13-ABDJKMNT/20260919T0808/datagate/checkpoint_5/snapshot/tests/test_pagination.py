"""Spec section: Pagination (`_size`, `_offset`)."""

from tests.conftest import numbered_csv


# Phrase: "`_size` (positive integer, default `100`) limits returned rows."
def test_size_limits_the_returned_rows(dataset):
    payload = dataset(numbered_csv(40), dataset_query="?_size=7")
    assert [row[0] for row in payload["rows"]] == list(range(7))


# Phrase: "`_size` ... default `100`"
def test_size_defaults_to_100(dataset):
    assert len(dataset(numbered_csv(250))["rows"]) == 100


# Phrase: "If it exceeds available rows, return all."
def test_size_beyond_the_row_count_returns_every_row(dataset):
    payload = dataset(numbered_csv(6), dataset_query="?_size=500")
    assert len(payload["rows"]) == 6


# Phrase: "`_offset` (non-negative integer, default `0`) skips that many rows before
# returning."
def test_offset_skips_rows(dataset):
    payload = dataset(numbered_csv(10), dataset_query="?_offset=4")
    assert [row[0] for row in payload["rows"]] == [4, 5, 6, 7, 8, 9]


# Phrase: "`_offset` ... default `0`"
def test_offset_defaults_to_zero(dataset):
    assert dataset(numbered_csv(10))["rows"][0][0] == 0


# Phrase: "`_offset` ... skips that many rows" combined with "`_size` ... limits
# returned rows": the page is the `_size` rows following `_offset`.
def test_size_and_offset_combine_into_a_page(dataset):
    payload = dataset(numbered_csv(30), dataset_query="?_offset=10&_size=3")
    assert [row[0] for row in payload["rows"]] == [10, 11, 12]


# Phrase: "`_offset` ... skips that many rows" - past the end yields no rows (T22).
def test_offset_past_the_end_returns_an_empty_page(endpoint):
    response = endpoint(numbered_csv(5))("?_offset=99")
    assert response.status_code == 200
    assert response.get_json()["rows"] == []
    assert response.get_json()["total"] == 5


# Phrase: "`_size` (positive integer ...)" / "Invalid `_size`/`_offset` -> `HTTP 400`."
def test_invalid_size_is_400(endpoint):
    query = endpoint()
    for value in ["0", "-1", "abc", "", "3.5", "1e2", "%204", "+4", "one"]:
        response = query(f"?_size={value}")
        assert response.status_code == 400, value
        assert response.get_json()["ok"] is False


# Phrase: "`_offset` (non-negative integer ...)" / "Invalid `_size`/`_offset` -> 400."
def test_invalid_offset_is_400(endpoint):
    query = endpoint()
    for value in ["-1", "abc", "", "2.0", "-0"]:
        response = query(f"?_offset={value}")
        assert response.status_code == 400, value
        assert response.get_json()["ok"] is False


# Phrase: "`_offset` (non-negative integer ...)" - zero is valid.
def test_offset_zero_is_accepted(endpoint):
    assert endpoint(numbered_csv(3))("?_offset=0").status_code == 200


# Phrase: "`_size` (positive integer ...)" - one is valid.
def test_size_one_is_accepted(endpoint):
    response = endpoint(numbered_csv(3))("?_size=1")
    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 1
