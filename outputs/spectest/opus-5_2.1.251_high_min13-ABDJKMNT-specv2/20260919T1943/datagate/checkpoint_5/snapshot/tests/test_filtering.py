"""Spec section: Column-Level Filtering (`<column>__<comparator>=<value>`)."""

import pytest

import datagate_app.filtering as filtering

# Four rows with a repeated age, two sortable columns and mixed-case text.
PEOPLE = "name,age,city\nada,36,London\ngrace,45,New York\nlinus,28,Helsinki\nedsger,45,Austin\n"


def names(body):
    return [row[0] for row in body["rows"]]


# Phrase: "`GET /datasets/<id>` accepts filter params in this form: `<column>__<comparator>=<value>`"
def test_filter_param_selects_matching_rows(query):
    body = query("?name__exact=ada", PEOPLE).get_json()

    assert body["rows"] == [["ada", 36, "London"]]


# Phrase: "Control params (names beginning with `_`) are not filters."
def test_control_params_are_not_treated_as_filters(query):
    body = query("?_sort=age&_size=2", PEOPLE).get_json()

    assert names(body) == ["linus", "ada"]
    assert body["total"] == 4


# Phrase: "Control params (names beginning with `_`) are not filters." (context: T31 — `_`-prefixed
# names are never filters even when they contain `__`)
def test_underscore_prefixed_name_with_comparator_is_ignored(query):
    response = query("?_mystery__exact=ada", PEOPLE)

    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# Phrase: "Control params (names beginning with `_`) are not filters." (context: T31 — a key that
# is all separator has no column name and still begins with `_`)
def test_bare_comparator_key_is_ignored(query):
    response = query("?__exact=ada", PEOPLE)

    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# Phrase: "`exact`: case-sensitive string equality."
def test_exact_is_case_sensitive(query):
    body = query("?city__exact=london", PEOPLE).get_json()

    assert body["rows"] == []
    assert body["total"] == 0


# Phrase: "`exact`: ... string equality." (context: a prefix of the stored value does not match)
def test_exact_requires_the_whole_value(query):
    body = query("?name__exact=ad", PEOPLE).get_json()

    assert body["rows"] == []


# Phrase: "`exact`: case-sensitive string equality." (context: T28 — numeric cells compare as text)
def test_exact_matches_a_numeric_cell(query):
    body = query("?age__exact=36", PEOPLE).get_json()

    assert names(body) == ["ada"]


# Phrase: "`exact`: ... string equality." (context: an empty filter value matches empty cells)
def test_exact_matches_empty_cells(query):
    body = query("?v__exact=", "v,w\n,1\na,2\n").get_json()

    assert body["rows"] == [["", 1]]


# Phrase: "`contains`: case-sensitive substring."
def test_contains_matches_a_substring(query):
    body = query("?city__contains=Yor", PEOPLE).get_json()

    assert names(body) == ["grace"]


# Phrase: "`contains`: case-sensitive substring."
def test_contains_is_case_sensitive(query):
    body = query("?city__contains=yor", PEOPLE).get_json()

    assert body["rows"] == []


# Phrase: "`contains`: ... substring." (context: T28 — numeric cells are searched as text)
def test_contains_matches_inside_a_numeric_cell(query):
    body = query("?age__contains=4", PEOPLE).get_json()

    assert names(body) == ["grace", "edsger"]


# Phrase: "`less`: numeric strict less (`float` parse on stored and filter values)."
def test_less_keeps_smaller_values(query):
    body = query("?age__less=36", PEOPLE).get_json()

    assert names(body) == ["linus"]


# Phrase: "`less`: numeric *strict* less"
def test_less_excludes_equal_values(query):
    body = query("?age__less=28", PEOPLE).get_json()

    assert body["rows"] == []


# Phrase: "`greater`: numeric strict greater."
def test_greater_keeps_larger_values(query):
    body = query("?age__greater=36", PEOPLE).get_json()

    assert names(body) == ["grace", "edsger"]


# Phrase: "`greater`: numeric *strict* greater."
def test_greater_excludes_equal_values(query):
    body = query("?age__greater=45", PEOPLE).get_json()

    assert body["rows"] == []


# Phrase: "(`float` parse on stored and filter values)" (context: a fractional filter value)
def test_numeric_comparators_parse_floats(query):
    body = query("?age__less=36.5", PEOPLE).get_json()

    assert names(body) == ["ada", "linus"]


# Phrase: "(`float` parse on stored and filter values)" (context: decimal cells compare numerically)
def test_numeric_comparators_compare_decimal_cells(query):
    body = query("?v__greater=2", "v\n10.5\n2.25\n1.75\n").get_json()

    assert body["rows"] == [[10.5], [2.25]]


# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
@pytest.mark.parametrize("comparator", ["less", "greater"])
@pytest.mark.parametrize("value", ["abc", "", "36abc", "1,5"])
def test_non_numeric_filter_value_is_400(query, comparator, value):
    response = query(f"?age__{comparator}={value}", PEOPLE)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "Rows with non-numeric stored values are not matched for numeric comparators."
@pytest.mark.parametrize("query_string", ["?v__greater=0", "?v__less=1000"])
def test_text_cells_never_match_numeric_comparators(query, query_string):
    body = query(query_string, "v,w\n5,1\nabc,2\n,3\n").get_json()

    assert body["rows"] == [[5, 1]]
    assert body["total"] == 1


# Phrase: "Multiple filters are ANDed."
def test_multiple_filters_are_anded(query):
    body = query("?age__greater=30&name__contains=a", PEOPLE).get_json()

    assert names(body) == ["ada", "grace"]


# Phrase: "Multiple filters are ANDed." (context: T32 — two comparators on one column are distinct keys)
def test_two_comparators_on_one_column_are_anded(query):
    body = query("?age__greater=30&age__less=46", PEOPLE).get_json()

    assert names(body) == ["ada", "grace", "edsger"]


# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
def test_duplicate_filter_key_is_400(query):
    response = query("?age__less=40&age__less=50", PEOPLE)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Duplicate filter keys are invalid" (context: T32 — identical repeats are rejected too)
def test_repeated_identical_filter_key_is_400(query):
    response = query("?name__exact=ada&name__exact=ada", PEOPLE)

    assert response.status_code == 400


# Phrase: "Column matching is exact and case-sensitive."
def test_column_matching_is_case_sensitive(query):
    response = query("?Name__exact=ada", PEOPLE)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Column matching is exact" (context: T27 — a column whose name contains `__`)
def test_column_name_containing_double_underscore(query):
    body = query("?first__name__exact=ada", "first__name,age\nada,36\ngrace,45\n").get_json()

    assert body["rows"] == [["ada", 36]]


# Phrase: "Filtering precedes sorting."
def test_filtering_precedes_sorting(query):
    body = query("?age__greater=30&_sort_desc=age", PEOPLE).get_json()

    assert names(body) == ["grace", "edsger", "ada"]


# Phrase: "Pagination runs on filtered+sorted results."
def test_pagination_runs_on_filtered_and_sorted_rows(query):
    body = query("?age__greater=30&_sort=age&_size=1&_offset=1", PEOPLE).get_json()

    assert names(body) == ["grace"]


# Phrase: "`total` counts filtered rows before pagination."
def test_total_counts_filtered_rows_before_pagination(query):
    body = query("?age__greater=30&_size=1", PEOPLE).get_json()

    assert body["total"] == 3
    assert len(body["rows"]) == 1


# Phrase: "`total` counts filtered rows" (context: nothing matches)
def test_total_is_zero_when_nothing_matches(query):
    body = query("?name__exact=nobody", PEOPLE).get_json()

    assert body["total"] == 0
    assert body["rows"] == []


# Phrase: "Query timeout returns `HTTP 400`." (context: T30 — the budget guards filter evaluation)
def test_query_timeout_is_400(query, monkeypatch):
    monkeypatch.setattr(filtering, "QUERY_TIMEOUT_SECONDS", 0.0)

    response = query("?age__greater=0", PEOPLE)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "| Invalid comparator (`exact|contains|less|greater`) | 400 |"
@pytest.mark.parametrize("key", ["name__bogus", "name__EXACT", "name__", "name__exact__exact"])
def test_invalid_comparator_is_400(query, key):
    response = query(f"?{key}=ada", PEOPLE)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "| Unknown filter column | 400 |"
@pytest.mark.parametrize("key", ["nope__exact", "rowid__exact", "name__exact__exact"])
def test_unknown_filter_column_is_400(query, key):
    response = query(f"?{key}=ada", PEOPLE)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "Params without `_` and without `__` are ignored as filters."
@pytest.mark.parametrize("query_string", ["?name=ada", "?foo=bar", "?age=1&other=2"])
def test_params_without_a_comparator_are_ignored(query, query_string):
    response = query(query_string, PEOPLE)

    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# Phrase: "Params without `_` and without `__` are ignored" (context: repeats of them are ignored too)
def test_repeated_non_filter_param_is_ignored(query):
    response = query("?name=ada&name=grace", PEOPLE)

    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# Phrase: "`<column>__<comparator>=<value>`" (context: filters apply in every response shape)
def test_filtering_applies_to_object_rows(query):
    body = query("?age__greater=40&_shape=objects&_rowid=hide", PEOPLE).get_json()

    assert body["rows"] == [
        {"name": "grace", "age": 45, "city": "New York"},
        {"name": "edsger", "age": 45, "city": "Austin"},
    ]


# Phrase: "`total` counts filtered rows" (context: `_total=hide` still drops the field)
def test_total_can_still_be_hidden(query):
    body = query("?age__greater=40&_total=hide", PEOPLE).get_json()

    assert "total" not in body
    assert len(body["rows"]) == 2
