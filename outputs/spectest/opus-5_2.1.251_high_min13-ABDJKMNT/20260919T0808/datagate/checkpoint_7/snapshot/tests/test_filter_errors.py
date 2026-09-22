"""Spec section: Column-Level Filtering - the error table."""

import pytest

from datagate_core import timing
from tests.conftest import TEAMS_CSV


def assert_bad_request(response):
    """Every filter failure is a 400 carrying the JSON error envelope."""
    assert response.status_code == 400, response.get_json()
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    return payload


# Phrase: "Invalid comparator (`exact|contains|less|greater`) | 400"
@pytest.mark.parametrize("comparator", ["equals", "gt", "EXACT", "Contains", "startswith"])
def test_invalid_comparator_is_400(endpoint, comparator):
    assert_bad_request(endpoint(TEAMS_CSV)(f"?name__{comparator}=ada"))


# Phrase: "Invalid comparator" - a key ending in `__` names no comparator at all.
def test_empty_comparator_is_400(endpoint):
    assert_bad_request(endpoint(TEAMS_CSV)("?name__=ada"))


# Phrase: "Invalid comparator" - only the last `__` separates the comparator (T26).
def test_comparator_is_the_final_segment(endpoint):
    assert_bad_request(endpoint(TEAMS_CSV)("?name__exact__contains=ada"))


# Phrase: "Comparator target not numeric (`__less`/`__greater`) | 400"
@pytest.mark.parametrize("comparator", ["less", "greater"])
def test_non_numeric_filter_value_is_400(endpoint, comparator):
    assert_bad_request(endpoint(TEAMS_CSV)(f"?age__{comparator}=old"))


# Phrase: "Comparator target not numeric" - an empty value is not numeric (T29, T31).
def test_empty_numeric_filter_value_is_400(endpoint):
    assert_bad_request(endpoint(TEAMS_CSV)("?age__less="))


# Phrase: "Comparator target not numeric" - the rule is about the filter value, so a
# numeric value against a text column is fine and simply matches nothing.
def test_numeric_filter_on_a_text_column_is_not_an_error(endpoint):
    response = endpoint(TEAMS_CSV)("?name__less=10")
    assert response.status_code == 200
    assert response.get_json()["rows"] == []


# Phrase: "Comparator target not numeric" - `float` spellings the parse accepts are
# valid filter values (T31).
@pytest.mark.parametrize("value", ["45", "-3", "4.5e1", ".5"])
def test_float_parsable_values_are_accepted(endpoint, value):
    assert endpoint(TEAMS_CSV)(f"?age__less={value}").status_code == 200


# Phrase: "Unknown filter column | 400"
def test_unknown_filter_column_is_400(endpoint):
    assert_bad_request(endpoint(TEAMS_CSV)("?height__exact=180"))


# Phrase: "Column matching is exact and case-sensitive." - a case variant of a real
# column is an unknown column.
def test_column_match_is_case_sensitive(endpoint):
    assert_bad_request(endpoint(TEAMS_CSV)("?Name__exact=ada"))


# Phrase: "Control params (names beginning with `_`) are not filters." - `__exact` names
# no column, but it does begin with `_`, so it is ignored rather than rejected (T33).
def test_a_key_without_a_column_name_is_ignored(endpoint):
    response = endpoint(TEAMS_CSV)("?__exact=ada")
    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 4


# Phrase: "Unknown filter column" - `rowid` is not in `columns`, so it is unknown (T32).
def test_rowid_is_not_a_filter_column(endpoint):
    assert_bad_request(endpoint(TEAMS_CSV)("?rowid__greater=1"))


# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
def test_duplicate_filter_key_is_400(endpoint):
    assert_bad_request(endpoint(TEAMS_CSV)("?age__less=40&age__less=45"))


# Phrase: "Duplicate filter keys are invalid" - even when the repeated values agree.
def test_duplicate_filter_key_with_equal_values_is_400(endpoint):
    assert_bad_request(endpoint(TEAMS_CSV)("?team__exact=blue&team__exact=blue"))


# Phrase: "Duplicate filter keys are invalid" - the key is column *and* comparator, so
# differing comparators on one column are not duplicates (T30).
def test_same_column_with_different_comparators_is_allowed(endpoint):
    assert endpoint(TEAMS_CSV)("?age__less=45&age__greater=30").status_code == 200


# Phrase: "Query timeout returns `HTTP 400`."
def test_query_timeout_is_400(endpoint, monkeypatch):
    monkeypatch.setattr(timing, "QUERY_TIMEOUT_SECONDS", 0)
    assert_bad_request(endpoint(TEAMS_CSV)("?team__exact=blue"))


# Phrase: "Query timeout returns `HTTP 400`." - the budget covers unfiltered queries too.
def test_query_timeout_applies_without_filters(endpoint, monkeypatch):
    monkeypatch.setattr(timing, "QUERY_TIMEOUT_SECONDS", 0)
    assert_bad_request(endpoint(TEAMS_CSV)(""))


# Phrase: "{"ok": false, "error": "<message>"}" - filter errors use the same envelope as
# the rest of the API, with no dataset payload leaking through.
def test_filter_errors_carry_only_the_envelope(endpoint):
    payload = assert_bad_request(endpoint(TEAMS_CSV)("?name__nope=ada"))
    assert set(payload) == {"ok", "error"}
