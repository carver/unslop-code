"""Spec section: Sorting (`_sort`, `_sort_desc`)."""

import pytest

# Two sortable columns plus a repeated `team`, which exposes sort stability.
ROSTER = "name,score,team\nada,30,b\ngrace,10,a\nlinus,20,a\nedsger,20,b\n"


# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
def test_sort_ascending(query):
    body = query("?_sort=score", ROSTER).get_json()

    assert [row[1] for row in body["rows"]] == [10, 20, 20, 30]


# Phrase: "`_sort=<column>` sorts ascending" (context: text columns compare lexicographically)
def test_sort_ascending_on_text(query):
    body = query("?_sort=name", ROSTER).get_json()

    assert [row[0] for row in body["rows"]] == ["ada", "edsger", "grace", "linus"]


# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
def test_sort_descending(query):
    body = query("?_sort_desc=score", ROSTER).get_json()

    assert [row[1] for row in body["rows"]] == [30, 20, 20, 10]


# Phrase: "If both are present, `_sort_desc` wins."
def test_sort_desc_wins_over_sort(query):
    body = query("?_sort=name&_sort_desc=score", ROSTER).get_json()

    assert [row[1] for row in body["rows"]] == [30, 20, 20, 10]


# Phrase: "Sorting is stable" (context: ties keep source order, ascending)
def test_ascending_sort_is_stable(query):
    body = query("?_sort=team", ROSTER).get_json()

    assert [row[0] for row in body["rows"]] == ["grace", "linus", "ada", "edsger"]


# Phrase: "Sorting is stable" (context: T20 — ties keep source order descending too)
def test_descending_sort_is_stable(query):
    body = query("?_sort_desc=team", ROSTER).get_json()

    assert [row[0] for row in body["rows"]] == ["ada", "edsger", "grace", "linus"]


# Phrase: "Sorting is stable and applied before pagination."
def test_sorting_precedes_pagination(query):
    body = query("?_sort_desc=score&_offset=1&_size=2", ROSTER).get_json()

    assert [row[1] for row in body["rows"]] == [20, 20]
    assert body["total"] == 4


# Phrase: "Sorting is ... applied before pagination." (context: T20 — mixed types order numbers first)
def test_mixed_type_column_sorts_numbers_before_text(query):
    body = query("?_sort=v", "v,w\nb,1\n2,2\n,3\n10,4\na,5\n").get_json()

    assert [row[0] for row in body["rows"]] == [2, 10, "", "a", "b"]


# Phrase: "Empty values or unknown columns return `HTTP 400`."
@pytest.mark.parametrize("parameter", ["_sort", "_sort_desc"])
def test_unknown_sort_column_is_400(query, parameter):
    response = query(f"?{parameter}=nope", ROSTER)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "Empty values or unknown columns return `HTTP 400`."
@pytest.mark.parametrize("parameter", ["_sort", "_sort_desc"])
def test_empty_sort_value_is_400(query, parameter):
    response = query(f"?{parameter}=", ROSTER)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Empty values or unknown columns return 400." (context: T21 — the losing `_sort` is validated too)
def test_unknown_losing_sort_column_is_400(query):
    response = query("?_sort=nope&_sort_desc=score", ROSTER)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "`_sort=<column>`" (context: sorting works in every shape)
def test_sorting_applies_to_object_rows(query):
    body = query("?_sort=score&_shape=objects", ROSTER).get_json()

    assert [row["name"] for row in body["rows"]] == ["grace", "linus", "edsger", "ada"]
