"""Spec section: Sorting."""

import pytest

# carol and bob tie on score, so their relative order exposes sort stability.
CSV = "name,score\ncarol,7\nalice,3\nbob,7\n"


# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
def test_sort_ascending(converted):
    body = converted(CSV, query="?_sort=score").get_json()

    assert [row[1] for row in body["rows"]] == [3, 7, 7]


# Phrase: "`_sort=<column>` sorts ascending by `<column>`." -- context: text columns.
def test_sort_ascending_on_text(converted):
    body = converted(CSV, query="?_sort=name").get_json()

    assert [row[0] for row in body["rows"]] == ["alice", "bob", "carol"]


# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
def test_sort_descending(converted):
    body = converted(CSV, query="?_sort_desc=name").get_json()

    assert [row[0] for row in body["rows"]] == ["carol", "bob", "alice"]


# Phrase: "If both are present, `_sort_desc` wins."
def test_sort_desc_wins_over_sort(converted):
    body = converted(CSV, query="?_sort=name&_sort_desc=score").get_json()

    assert [row[1] for row in body["rows"]] == [7, 7, 3]
    assert [row[0] for row in body["rows"]] == ["carol", "bob", "alice"]


# Phrase: "Sorting is stable" -- context: ties keep source order, ascending.
def test_ascending_sort_is_stable(converted):
    body = converted(CSV, query="?_sort=score").get_json()

    assert [row[0] for row in body["rows"]] == ["alice", "carol", "bob"]


# Phrase: "Sorting is stable" -- context: ties keep source order, descending (AMBIGUITIES T16).
def test_descending_sort_is_stable(converted):
    body = converted(CSV, query="?_sort_desc=score").get_json()

    assert [row[0] for row in body["rows"]] == ["carol", "bob", "alice"]


# Phrase: "Sorting is ... applied before pagination."
def test_sorting_precedes_pagination(converted):
    body = converted(CSV, query="?_sort=name&_size=1").get_json()

    assert body["rows"] == [["alice", 3]]


# Phrase: "Sorting is ... applied before pagination." -- context: offset walks the sorted rows.
def test_offset_applies_to_sorted_rows(converted):
    body = converted(CSV, query="?_sort_desc=name&_offset=1&_size=1").get_json()

    assert body["rows"] == [["bob", 7]]


# Phrase: "Sorting is ... applied before pagination." -- context: mixed cell types (AMBIGUITIES T15).
def test_mixed_type_column_sorts_numbers_before_text(converted):
    body = converted("v,note\n10,a\nzed,b\n2,c\n", query="?_sort=v").get_json()

    assert [row[0] for row in body["rows"]] == [2, 10, "zed"]


# Phrase: "Empty values or unknown columns return `HTTP 400`."
@pytest.mark.parametrize("query", ["?_sort=", "?_sort_desc=", "?_sort=nope", "?_sort_desc=nope"])
def test_empty_or_unknown_sort_column_is_400(converted, query):
    response = converted(CSV, query=query)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "unknown columns return `HTTP 400`." -- context: column names are matched exactly.
def test_sort_column_match_is_case_sensitive(converted):
    response = converted(CSV, query="?_sort=Score")

    assert response.status_code == 400


# Phrase: "If both are present, `_sort_desc` wins." -- context: the loser is not validated (T14).
def test_unknown_sort_is_ignored_when_sort_desc_wins(converted):
    response = converted(CSV, query="?_sort=nope&_sort_desc=score")

    assert response.status_code == 200
    assert [row[1] for row in response.get_json()["rows"]] == [7, 7, 3]
