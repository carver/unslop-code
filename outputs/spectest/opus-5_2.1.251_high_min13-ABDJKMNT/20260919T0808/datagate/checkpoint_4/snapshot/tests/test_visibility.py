"""Spec sections: Visibility toggles, repeated control parameters, Error Handling."""

import pytest

from tests.conftest import SIMPLE_CSV

CONTROL_PARAMETERS = ["_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total"]


# Phrase: "`_rowid=hide` removes `rowid`."
def test_rowid_hide_removes_rowid_from_objects(dataset):
    payload = dataset(SIMPLE_CSV, dataset_query="?_shape=objects&_rowid=hide")
    assert payload["rows"] == [{"name": "ada", "age": 36}, {"name": "grace", "age": 45}]


# Phrase: "`_rowid=hide` removes `rowid`." - with the default shape there is nothing to
# remove, and the request is still valid (T19).
def test_rowid_hide_is_accepted_with_the_lists_shape(endpoint):
    response = endpoint()("?_rowid=hide")
    assert response.status_code == 200
    assert response.get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`_total=hide` removes `total`."
def test_total_hide_removes_total(dataset):
    payload = dataset(SIMPLE_CSV, dataset_query="?_total=hide")
    assert "total" not in payload
    assert set(payload) == {"ok", "columns", "rows", "query_ms"}


# Phrase: "`_total=hide` removes `total`." - the rest of the payload is untouched.
def test_total_hide_keeps_rows_and_columns(dataset):
    payload = dataset(SIMPLE_CSV, dataset_query="?_total=hide&_shape=objects")
    assert payload["columns"] == ["name", "age"]
    assert payload["rows"][0] == {"rowid": 1, "name": "ada", "age": 36}


# Phrase: "`_rowid=hide` ... `_total=hide`" - both at once.
def test_both_toggles_together(dataset):
    payload = dataset(SIMPLE_CSV, dataset_query="?_shape=objects&_rowid=hide&_total=hide")
    assert "total" not in payload
    assert payload["rows"][0] == {"name": "ada", "age": 36}


# Phrase: "Each toggle is valid only with value `hide`; any other value is `HTTP 400`."
@pytest.mark.parametrize("toggle", ["_rowid", "_total"])
def test_non_hide_toggle_values_are_400(endpoint, toggle):
    query = endpoint()
    for value in ["show", "", "true", "1", "HIDE", "Hide", "hidden"]:
        response = query(f"?{toggle}={value}")
        assert response.status_code == 400, f"{toggle}={value}"
        assert response.get_json()["ok"] is False


# Phrase: "Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`,
# `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`."
@pytest.mark.parametrize(
    "repeated",
    [
        "_size=1&_size=2",
        "_offset=0&_offset=1",
        "_shape=lists&_shape=objects",
        "_sort=name&_sort=age",
        "_sort_desc=name&_sort_desc=age",
        "_rowid=hide&_rowid=hide",
        "_total=hide&_total=hide",
    ],
)
def test_repeated_control_parameter_is_400(endpoint, repeated):
    response = endpoint()(f"?{repeated}")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Any repeated control parameter ... is `HTTP 400`." - identical values repeat
# just the same.
def test_repeat_with_identical_values_is_400(endpoint):
    assert endpoint()("?_size=2&_size=2").status_code == 400


# Phrase: "Any repeated control parameter ..." - the rule covers control parameters
# only; other query keys are ignored as before.
def test_repeating_a_non_control_parameter_is_fine(endpoint):
    assert endpoint()("?tag=a&tag=b").status_code == 200


# Phrase: error table - every listed condition answers with the JSON error envelope.
@pytest.mark.parametrize(
    "query",
    [
        "?_size=0",
        "?_offset=-2",
        "?_shape=tuples",
        "?_rowid=show",
        "?_total=yes",
        "?_size=1&_size=1",
        "?_sort=nope",
        "?_sort_desc=nope",
    ],
)
def test_control_errors_use_the_error_envelope(endpoint, query):
    response = endpoint()(query)
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"].strip()
    assert set(payload) == {"ok", "error"}


# Phrase: error table - a 400 from one control is not masked by a valid sibling.
def test_invalid_control_beside_valid_ones_is_400(endpoint):
    assert endpoint()("?_sort=name&_size=5&_shape=objects&_offset=x").status_code == 400


# Phrase: "control parameter repeated | 400" - checked even when the repeated values
# are themselves invalid.
def test_repeated_and_invalid_is_still_400(endpoint):
    assert endpoint()("?_shape=bogus&_shape=bogus").status_code == 400
