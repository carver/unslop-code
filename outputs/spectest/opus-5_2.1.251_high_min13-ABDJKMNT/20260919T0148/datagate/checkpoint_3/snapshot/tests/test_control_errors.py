"""Spec section: Error Handling for control parameters."""

import pytest

CSV = "name,score\nada,3\ngrace,1\n"
CONTROLS = ["_size", "_offset", "_shape", "_sort", "_sort_desc", "_rowid", "_total"]


def assert_json_error(response):
    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"].strip()


# Phrase: "| `_size` not a positive integer | 400 | `{"ok": false, "error": "<message>"}` |"
def test_size_error_envelope(converted):
    assert_json_error(converted(CSV, query="?_size=0"))


# Phrase: "| `_offset` not a non-negative integer | 400 | ... |"
def test_offset_error_envelope(converted):
    assert_json_error(converted(CSV, query="?_offset=-3"))


# Phrase: "| `_shape` not `lists`/`objects` | 400 | ... |"
@pytest.mark.parametrize("value", ["arrays", "object", "", "LISTS"])
def test_unknown_shape_is_400(converted, value):
    assert_json_error(converted(CSV, query=f"?_shape={value}"))


# Phrase: "Each toggle is valid only with value `hide`; any other value is `HTTP 400`."
@pytest.mark.parametrize("name", ["_rowid", "_total"])
@pytest.mark.parametrize("value", ["show", "", "1", "true", "HIDE"])
def test_toggle_values_other_than_hide_are_400(converted, name, value):
    assert_json_error(converted(CSV, query=f"?{name}={value}"))


# Phrase: "| `_sort`/`_sort_desc` unknown column | 400 | ... |"
def test_unknown_sort_column_error_envelope(converted):
    assert_json_error(converted(CSV, query="?_sort=missing"))


# Phrase: "Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`,
# `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`."
@pytest.mark.parametrize(
    "name,value",
    [
        ("_size", "1"),
        ("_offset", "0"),
        ("_shape", "lists"),
        ("_sort", "name"),
        ("_sort_desc", "name"),
        ("_rowid", "hide"),
        ("_total", "hide"),
    ],
)
def test_repeated_control_parameter_is_400(converted, name, value):
    assert_json_error(converted(CSV, query=f"?{name}={value}&{name}={value}"))


# Phrase: "Any repeated control parameter ... is `HTTP 400`." -- context: differing values too.
def test_repeated_control_parameter_with_different_values_is_400(converted):
    assert_json_error(converted(CSV, query="?_size=1&_size=2"))


# Phrase: "Any repeated control parameter ..." -- context: the list is exactly these seven.
def test_every_control_parameter_rejects_repeats(converted):
    for name in CONTROLS:
        assert converted(CSV, query=f"?{name}=hide&{name}=hide").status_code == 400


# Phrase: "Any repeated control parameter ..." -- context: repeats of the losing sort
# parameter are still rejected.
def test_repeated_losing_sort_parameter_is_400(converted):
    assert_json_error(converted(CSV, query="?_sort=name&_sort=score&_sort_desc=name"))


# Phrase: "control parameter repeated" -- context: other query parameters are unaffected.
def test_unknown_parameters_are_ignored(converted):
    response = converted(CSV, query="?limit=1&limit=2")

    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 2


# Phrase: "If `<id>` is unknown, return `HTTP 404`." -- context: a bad control parameter on an
# unknown dataset still reports the missing dataset (AMBIGUITIES T18).
def test_unknown_dataset_outranks_invalid_controls(client):
    response = client.get("/datasets/deadbeefdeadbeef?_size=0")

    assert response.status_code == 404
