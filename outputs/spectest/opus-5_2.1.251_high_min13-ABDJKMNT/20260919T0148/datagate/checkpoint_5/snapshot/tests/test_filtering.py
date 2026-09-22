"""Spec section: Column-Level Filtering -- comparators and filter behaviour."""

import pytest

# `score` mixes numbers with the non-numeric "n/a"; `city` shares the prefix "Par"
# between two rows so that `contains` and `exact` can be told apart.
CSV = "name,score,city\nada,10,Paris\ngrace,2,Parma\nlinus,7,Oslo\nalan,n/a,Paris\n"


def names(response):
    """The `name` cell of every returned row, in response order."""
    return [row[0] for row in response.get_json()["rows"]]


# Phrase: "`GET /datasets/<id>` accepts filter params in this form: `<column>__<comparator>=<value>`."
def test_filter_param_selects_rows(converted):
    assert names(converted(CSV, query="?name__exact=ada")) == ["ada"]


# Phrase: "`exact`: case-sensitive string equality."
def test_exact_matches_the_whole_value(converted):
    assert names(converted(CSV, query="?city__exact=Paris")) == ["ada", "alan"]


# Phrase: "`exact`: case-sensitive string equality." -- context: a prefix is not equality.
def test_exact_does_not_match_a_substring(converted):
    assert names(converted(CSV, query="?city__exact=Par")) == []


# Phrase: "`exact`: case-sensitive string equality." -- context: case must agree.
def test_exact_is_case_sensitive(converted):
    assert names(converted(CSV, query="?name__exact=Ada")) == []


# Phrase: "`exact`: case-sensitive string equality." -- context: numeric cells compare as
# their rendered text (AMBIGUITIES T23).
def test_exact_matches_a_numeric_cell(converted):
    assert names(converted(CSV, query="?score__exact=10")) == ["ada"]


# Phrase: "`contains`: case-sensitive substring."
def test_contains_matches_a_substring(converted):
    assert names(converted(CSV, query="?city__contains=Par")) == ["ada", "grace", "alan"]


# Phrase: "`contains`: case-sensitive substring." -- context: case must agree.
def test_contains_is_case_sensitive(converted):
    assert names(converted(CSV, query="?city__contains=par")) == []


# Phrase: "`contains`: case-sensitive substring." -- context: the whole value is a substring
# of itself.
def test_contains_matches_an_equal_value(converted):
    assert names(converted(CSV, query="?name__contains=linus")) == ["linus"]


# Phrase: "`contains`: case-sensitive substring." -- context: numeric cells compare as their
# rendered text (AMBIGUITIES T23).
def test_contains_matches_inside_a_number(converted):
    assert names(converted(CSV, query="?score__contains=0")) == ["ada"]


# Phrase: "`less`: numeric strict less (`float` parse on stored and filter values)."
def test_less_keeps_smaller_numbers(converted):
    assert names(converted(CSV, query="?score__less=8")) == ["grace", "linus"]


# Phrase: "`less`: numeric strict less" -- context: strict excludes the equal value.
def test_less_is_strict(converted):
    assert names(converted(CSV, query="?score__less=2")) == []


# Phrase: "`greater`: numeric strict greater."
def test_greater_keeps_larger_numbers(converted):
    assert names(converted(CSV, query="?score__greater=7")) == ["ada"]


# Phrase: "`greater`: numeric strict greater." -- context: strict excludes the equal value.
def test_greater_is_strict(converted):
    assert names(converted(CSV, query="?score__greater=10")) == []


# Phrase: "(`float` parse on stored and filter values)" -- context: a fractional filter value.
def test_numeric_filter_value_may_be_fractional(converted):
    assert names(converted(CSV, query="?score__less=7.5")) == ["grace", "linus"]


# Phrase: "(`float` parse on stored and filter values)" -- context: fractional stored values.
def test_numeric_comparison_parses_fractional_cells(converted):
    body = converted("name,score\nada,2.5\ngrace,1.75\n", query="?score__greater=2").get_json()

    assert [row[0] for row in body["rows"]] == ["ada"]


# Phrase: "(`float` parse on stored and filter values)" -- context: integers and floats compare
# against each other.
def test_integer_cell_compares_against_float_filter(converted):
    assert names(converted(CSV, query="?score__greater=9.5")) == ["ada"]


# Phrase: "Rows with non-numeric stored values are not matched for numeric comparators."
@pytest.mark.parametrize("query", ["?score__less=1000", "?score__greater=-1000"])
def test_non_numeric_cells_never_match_numeric_comparators(converted, query):
    assert "alan" not in names(converted(CSV, query=query))


# Phrase: "Rows with non-numeric stored values are not matched" -- context: text columns
# drop every row rather than failing.
def test_numeric_comparator_on_a_text_column_matches_nothing(converted):
    response = converted(CSV, query="?name__less=1000")

    assert response.status_code == 200
    assert names(response) == []


# Phrase: "Multiple filters are ANDed."
def test_filters_are_anded(converted):
    assert names(converted(CSV, query="?city__contains=Par&score__greater=5")) == ["ada"]


# Phrase: "Multiple filters are ANDed." -- context: two comparators on one column bound a range.
def test_two_comparators_on_one_column_are_anded(converted):
    assert names(converted(CSV, query="?score__greater=1&score__less=8")) == ["grace", "linus"]


# Phrase: "Multiple filters are ANDed." -- context: contradictory filters keep nothing.
def test_contradictory_filters_match_nothing(converted):
    assert names(converted(CSV, query="?name__exact=ada&city__exact=Oslo")) == []


# Phrase: "Filtering precedes sorting."
def test_filtering_precedes_sorting(converted):
    assert names(converted(CSV, query="?score__less=8&_sort_desc=score")) == ["linus", "grace"]


# Phrase: "Filtering precedes sorting." -- context: excluded rows cannot reappear at the top.
def test_sorting_orders_only_the_filtered_rows(converted):
    assert names(converted(CSV, query="?city__contains=Par&_sort=score")) == [
        "grace",
        "ada",
        "alan",
    ]


# Phrase: "Pagination runs on filtered+sorted results."
def test_pagination_runs_on_filtered_and_sorted_rows(converted):
    assert names(converted(CSV, query="?score__less=8&_sort=score&_size=1")) == ["grace"]


# Phrase: "Pagination runs on filtered+sorted results." -- context: the offset walks the
# filtered rows.
def test_offset_walks_the_filtered_rows(converted):
    assert names(converted(CSV, query="?score__less=8&_sort=score&_offset=1&_size=1")) == ["linus"]


# Phrase: "`total` counts filtered rows before pagination."
def test_total_counts_filtered_rows(converted):
    body = converted(CSV, query="?city__exact=Paris&_size=1").get_json()

    assert body["total"] == 2
    assert len(body["rows"]) == 1


# Phrase: "`total` counts filtered rows before pagination." -- context: no match is a total of 0.
def test_total_is_zero_when_nothing_matches(converted):
    body = converted(CSV, query="?city__exact=Berlin").get_json()

    assert body["total"] == 0
    assert body["rows"] == []


# Phrase: "`total` counts filtered rows before pagination." -- context: `columns` still
# describes the table.
def test_columns_are_unaffected_by_filtering(converted):
    body = converted(CSV, query="?city__exact=Oslo").get_json()

    assert body["columns"] == ["name", "score", "city"]


# Phrase: "`<column>__<comparator>=<value>`" -- context: `rowid` keeps the source row number
# across a filter.
def test_rowid_survives_filtering(converted):
    body = converted(CSV, query="?city__exact=Paris&_shape=objects").get_json()

    assert [row["rowid"] for row in body["rows"]] == [1, 4]


# Phrase: "Control params (names beginning with `_`) are not filters."
def test_control_params_are_not_filters(converted):
    body = converted(CSV, query="?_size=2&_sort=name").get_json()

    assert [row[0] for row in body["rows"]] == ["ada", "alan"]
    assert body["total"] == 4


# Phrase: "Control params (names beginning with `_`) are not filters." -- context: an unknown
# underscore parameter is neither a filter nor an error (AMBIGUITIES T27).
def test_underscore_parameter_with_a_comparator_is_ignored(converted):
    response = converted(CSV, query="?_hidden__exact=nope")

    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 4


# Phrase: "Params without `_` and without `__` are ignored as filters."
def test_plain_params_are_ignored(converted):
    response = converted(CSV, query="?name=ada&limit=1")

    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 4


# Phrase: "Params without `_` and without `__` are ignored as filters." -- context: an ignored
# param may repeat without being a duplicate filter key.
def test_repeated_ignored_param_is_not_an_error(converted):
    assert converted(CSV, query="?name=ada&name=grace").status_code == 200
