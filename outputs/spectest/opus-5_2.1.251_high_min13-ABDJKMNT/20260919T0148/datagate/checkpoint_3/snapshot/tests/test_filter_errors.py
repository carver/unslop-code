"""Spec section: Column-Level Filtering -- Error Handling."""

import pytest

CSV = "name,score,city\nada,10,Paris\ngrace,2,Parma\nlinus,7,Oslo\nalan,n/a,Paris\n"


def assert_json_error(response):
    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"].strip()


# Phrase: "| Invalid comparator (`exact|contains|less|greater`) | 400 |
# `{"ok": false, "error": "<message>"}` |"
@pytest.mark.parametrize("comparator", ["equals", "lt", "startswith", "exactly"])
def test_unknown_comparator_is_400(converted, comparator):
    assert_json_error(converted(CSV, query=f"?name__{comparator}=ada"))


# Phrase: "Invalid comparator" -- context: comparator names are case-sensitive.
def test_comparator_is_case_sensitive(converted):
    assert_json_error(converted(CSV, query="?name__EXACT=ada"))


# Phrase: "Invalid comparator" -- context: an empty comparator (AMBIGUITIES T28).
def test_empty_comparator_is_400(converted):
    assert_json_error(converted(CSV, query="?name__=ada"))


# Phrase: "Invalid comparator" -- context: the comparator is the segment after the last `__`,
# so what precedes it must name a column (AMBIGUITIES T24).
def test_extra_separator_is_400(converted):
    assert_json_error(converted(CSV, query="?name__exact__contains=ada"))


# Phrase: "| Comparator target not numeric (`__less`/`__greater`) | 400 | ... |"
@pytest.mark.parametrize("comparator", ["less", "greater"])
@pytest.mark.parametrize("value", ["abc", "", "1,5", "ten"])
def test_non_numeric_filter_value_is_400(converted, comparator, value):
    assert_json_error(converted(CSV, query=f"?score__{comparator}={value}"))


# Phrase: "Comparator target not numeric" -- context: only the numeric comparators care.
@pytest.mark.parametrize("comparator", ["exact", "contains"])
def test_string_comparators_accept_non_numeric_values(converted, comparator):
    assert converted(CSV, query=f"?name__{comparator}=ada").status_code == 200


# Phrase: "Comparator target not numeric" -- context: an empty value is still a match for the
# string comparators (AMBIGUITIES T29).
def test_empty_value_is_allowed_for_string_comparators(converted):
    response = converted("name,note\nada,\ngrace,hi\n", query="?note__exact=")

    assert response.status_code == 200
    assert [row[0] for row in response.get_json()["rows"]] == ["ada"]


# Phrase: "| Unknown filter column | 400 | ... |"
def test_unknown_filter_column_is_400(converted):
    assert_json_error(converted(CSV, query="?missing__exact=ada"))


# Phrase: "Column matching is exact and case-sensitive."
def test_filter_column_match_is_case_sensitive(converted):
    assert_json_error(converted(CSV, query="?Name__exact=ada"))


# Phrase: "Column matching is exact" -- context: a prefix of a real column is unknown.
def test_filter_column_match_is_not_a_prefix_match(converted):
    assert_json_error(converted(CSV, query="?nam__exact=ada"))


# Phrase: "Control params (names beginning with `_`) are not filters." -- context: an empty
# column name leaves a key that begins with `_`, so it is ignored (AMBIGUITIES T28).
def test_empty_filter_column_is_ignored(converted):
    response = converted(CSV, query="?__exact=ada")

    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 4


# Phrase: "| Duplicate filter key | 400 | ... |"
def test_duplicate_filter_key_is_400(converted):
    assert_json_error(converted(CSV, query="?name__exact=ada&name__exact=grace"))


# Phrase: "Duplicate filter key" -- context: the repeat is rejected even when the values agree.
def test_duplicate_filter_key_with_equal_values_is_400(converted):
    assert_json_error(converted(CSV, query="?name__exact=ada&name__exact=ada"))


# Phrase: "Duplicate filter key" -- context: one column with two comparators is not a duplicate
# key (AMBIGUITIES T30).
def test_same_column_with_two_comparators_is_allowed(converted):
    response = converted(CSV, query="?name__exact=ada&name__contains=ad")

    assert response.status_code == 200
    assert [row[0] for row in response.get_json()["rows"]] == ["ada"]


# Phrase: "| Query timeout | 400 | ... |" (AMBIGUITIES T31)
def test_query_timeout_is_400(converted, monkeypatch):
    monkeypatch.setattr("datagate_core.timing.QUERY_TIMEOUT_SECONDS", -1.0)

    assert_json_error(converted(CSV, query="?score__greater=1"))


# Phrase: "Query timeout" -- context: the budget covers an unfiltered query too.
def test_query_timeout_applies_without_filters(converted, monkeypatch):
    monkeypatch.setattr("datagate_core.timing.QUERY_TIMEOUT_SECONDS", -1.0)

    assert_json_error(converted(CSV))


# Phrase: "Query timeout" -- context: the default budget lets an ordinary query through.
def test_ordinary_query_does_not_time_out(converted):
    assert converted(CSV, query="?score__greater=1").status_code == 200


# Phrase: "If `<id>` is unknown, return `HTTP 404`." -- context: an invalid filter on an unknown
# dataset still reports the missing dataset (AMBIGUITIES T18).
def test_unknown_dataset_outranks_invalid_filters(client):
    assert client.get("/datasets/deadbeefdeadbeef?nope__exact=x").status_code == 404


# Phrase: "Error Handling" -- context: an invalid filter is reported even alongside valid ones.
def test_one_invalid_filter_fails_the_request(converted):
    assert_json_error(converted(CSV, query="?name__exact=ada&score__less=abc"))
