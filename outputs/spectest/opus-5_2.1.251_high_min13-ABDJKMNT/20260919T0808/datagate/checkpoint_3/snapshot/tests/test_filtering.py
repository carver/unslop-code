"""Spec section: Column-Level Filtering - the filter form, comparators and behaviour."""

import pytest

from tests.conftest import TEAMS_CSV

#: `value` mixes integers, a decimal, text and an empty cell for numeric comparators.
MIXED_CSV = "label,value\na,10\nb,2.5\nc,apple\nd,\ne,-3\n"


def names(payload):
    return [row[0] for row in payload["rows"]]


def labels(payload):
    return [row[0] for row in payload["rows"]]


# Phrase: "`GET /datasets/<id>` accepts filter params in this form:
# `<column>__<comparator>=<value>`"
def test_a_filter_param_selects_rows(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?team__exact=blue")
    assert names(payload) == ["ada", "alan"]


# Phrase: "accepts filter params" - a request without any filter still returns every row.
def test_no_filter_returns_every_row(dataset):
    assert len(dataset(TEAMS_CSV)["rows"]) == 4


# Phrase: "Control params (names beginning with `_`) are not filters." - a control keeps
# doing its own job next to a filter.
def test_control_params_are_not_treated_as_filters(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?_size=1&team__exact=red")
    assert names(payload) == ["grace"]


# Phrase: "Control params (names beginning with `_`) are not filters." - an unrecognised
# `_` name is not a filter either, so it is ignored rather than a 400 (T28).
def test_unknown_control_params_are_ignored(endpoint):
    response = endpoint(TEAMS_CSV)("?_unrelated=1&_size__exact=nonsense")
    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 4


# Phrase: "`exact`: case-sensitive string equality."
def test_exact_matches_the_whole_value(dataset):
    assert names(dataset(TEAMS_CSV, dataset_query="?name__exact=ada")) == ["ada"]


# Phrase: "`exact`: case-sensitive string equality." - a differing case does not match.
def test_exact_is_case_sensitive(dataset):
    assert dataset(TEAMS_CSV, dataset_query="?name__exact=Ada")["rows"] == []


# Phrase: "`exact`: ... string equality." - equality, not a substring test.
def test_exact_does_not_match_substrings(dataset):
    assert dataset(TEAMS_CSV, dataset_query="?name__exact=ad")["rows"] == []


# Phrase: "`exact`: case-sensitive string equality." - stored numbers compare by their
# text (T25).
def test_exact_matches_a_numeric_cell_by_its_text(dataset):
    assert names(dataset(TEAMS_CSV, dataset_query="?age__exact=36")) == ["ada"]


# Phrase: "`exact`: case-sensitive string equality." - an empty value selects empty
# cells (T29).
def test_exact_with_an_empty_value_selects_empty_cells(dataset):
    assert labels(dataset(MIXED_CSV, dataset_query="?value__exact=")) == ["d"]


# Phrase: "`contains`: case-sensitive substring."
def test_contains_matches_a_substring(dataset):
    assert names(dataset(TEAMS_CSV, dataset_query="?name__contains=a")) == [
        "ada",
        "grace",
        "alan",
    ]


# Phrase: "`contains`: case-sensitive substring." - case must agree.
def test_contains_is_case_sensitive(dataset):
    assert dataset(TEAMS_CSV, dataset_query="?name__contains=AD")["rows"] == []


# Phrase: "`contains`: ... substring." - a full value is a substring of itself.
def test_contains_matches_the_whole_value(dataset):
    assert names(dataset(TEAMS_CSV, dataset_query="?name__contains=grace")) == ["grace"]


# Phrase: "`contains`: case-sensitive substring." - the empty substring matches every
# row (T29).
def test_contains_with_an_empty_value_matches_everything(dataset):
    assert len(dataset(TEAMS_CSV, dataset_query="?name__contains=")["rows"]) == 4


# Phrase: "`less`: numeric strict less (`float` parse on stored and filter values)."
def test_less_keeps_smaller_numbers(dataset):
    assert names(dataset(TEAMS_CSV, dataset_query="?age__less=41")) == ["ada", "edsger"]


# Phrase: "`less`: numeric *strict* less" - the boundary value is excluded.
def test_less_is_strict(dataset):
    assert "grace" not in names(dataset(TEAMS_CSV, dataset_query="?age__less=45"))


# Phrase: "(`float` parse on stored and filter values)" - a decimal filter value against
# integer cells.
def test_less_parses_a_decimal_filter_value(dataset):
    assert names(dataset(TEAMS_CSV, dataset_query="?age__less=36.5")) == ["ada", "edsger"]


# Phrase: "(`float` parse on stored and filter values)" - comparison is numeric, not
# lexicographic: "100" is not less than "9".
def test_less_compares_numerically_not_lexicographically(dataset):
    payload = dataset("n,tag\n9,a\n100,b\n", dataset_query="?n__less=10")
    assert [row[0] for row in payload["rows"]] == [9]


# Phrase: "`greater`: numeric strict greater."
def test_greater_keeps_larger_numbers(dataset):
    assert names(dataset(TEAMS_CSV, dataset_query="?age__greater=41")) == ["grace"]


# Phrase: "`greater`: numeric *strict* greater." - the boundary value is excluded.
def test_greater_is_strict(dataset):
    assert "ada" not in names(dataset(TEAMS_CSV, dataset_query="?age__greater=36"))


# Phrase: "(`float` parse on stored and filter values)" - negative stored values order
# below zero.
def test_greater_handles_negative_stored_values(dataset):
    assert labels(dataset(MIXED_CSV, dataset_query="?value__greater=0")) == ["a", "b"]


# Phrase: "Rows with non-numeric stored values are not matched for numeric comparators."
def test_less_skips_non_numeric_cells(dataset):
    assert labels(dataset(MIXED_CSV, dataset_query="?value__less=1000")) == ["a", "b", "e"]


# Phrase: "Rows with non-numeric stored values are not matched for numeric comparators."
def test_greater_skips_non_numeric_cells(dataset):
    assert labels(dataset(MIXED_CSV, dataset_query="?value__greater=-1000")) == [
        "a",
        "b",
        "e",
    ]


# Phrase: "Rows with non-numeric stored values are not matched" - an empty cell is not
# numeric either.
def test_empty_cells_are_not_numeric(dataset):
    assert "d" not in labels(dataset(MIXED_CSV, dataset_query="?value__greater=-1000"))


# Phrase: "Multiple filters are ANDed." - across two columns.
def test_multiple_filters_are_anded(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?team__exact=blue&age__greater=40")
    assert names(payload) == ["alan"]


# Phrase: "Multiple filters are ANDed." - two comparators on one column form a range
# (T30).
def test_two_comparators_on_one_column_are_anded(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?age__greater=30&age__less=45")
    assert names(payload) == ["ada", "alan"]


# Phrase: "Multiple filters are ANDed." - no row satisfying both means no rows.
def test_conflicting_filters_select_nothing(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?team__exact=blue&team__contains=red")
    assert payload["rows"] == [] and payload["total"] == 0


# Phrase: "Column matching is exact and case-sensitive." - the right spelling works.
def test_column_matching_is_exact(dataset):
    assert names(dataset(TEAMS_CSV, dataset_query="?team__exact=red")) == [
        "grace",
        "edsger",
    ]


# Phrase: "Filtering precedes sorting." - the sort orders only the surviving rows.
def test_filtering_precedes_sorting(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?team__exact=red&_sort=age")
    assert names(payload) == ["edsger", "grace"]


# Phrase: "Filtering precedes sorting." - stability is preserved among the kept rows.
def test_sorting_after_filtering_is_stable(dataset):
    body = "name,team,age\nada,blue,36\nzoe,blue,36\nkay,red,36\n"
    payload = dataset(body, dataset_query="?team__exact=blue&_sort=age")
    assert names(payload) == ["ada", "zoe"]


# Phrase: "Pagination runs on filtered+sorted results." - `_size` caps the filtered page.
def test_pagination_applies_to_filtered_rows(dataset):
    body = "n,tag\n" + "".join(f"{i},{'even' if i % 2 == 0 else 'odd'}\n" for i in range(20))
    payload = dataset(body, dataset_query="?tag__exact=even&_size=3")
    assert [row[0] for row in payload["rows"]] == [0, 2, 4]


# Phrase: "Pagination runs on filtered+sorted results." - `_offset` skips filtered rows,
# not source rows.
def test_offset_skips_filtered_rows(dataset):
    body = "n,tag\n" + "".join(f"{i},{'even' if i % 2 == 0 else 'odd'}\n" for i in range(20))
    payload = dataset(body, dataset_query="?tag__exact=even&_size=2&_offset=3")
    assert [row[0] for row in payload["rows"]] == [6, 8]


# Phrase: "Pagination runs on filtered+sorted results." - the sort runs before the slice.
def test_pagination_follows_filtering_then_sorting(dataset):
    body = "n,tag\n" + "".join(f"{i},{'even' if i % 2 == 0 else 'odd'}\n" for i in range(20))
    payload = dataset(body, dataset_query="?tag__exact=even&_sort_desc=n&_size=2")
    assert [row[0] for row in payload["rows"]] == [18, 16]


# Phrase: "`total` counts filtered rows before pagination."
def test_total_counts_filtered_rows(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?team__exact=blue")
    assert payload["total"] == 2


# Phrase: "`total` counts filtered rows *before pagination*."
def test_total_ignores_the_page_size(dataset):
    body = "n,tag\n" + "".join(f"{i},{'even' if i % 2 == 0 else 'odd'}\n" for i in range(20))
    payload = dataset(body, dataset_query="?tag__exact=even&_size=2")
    assert payload["total"] == 10 and len(payload["rows"]) == 2


# Phrase: "`total` counts filtered rows" - filtering everything out leaves a zero total.
def test_total_is_zero_when_nothing_matches(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?name__exact=nobody")
    assert payload["total"] == 0 and payload["rows"] == []


# Phrase: "Filtering precedes sorting." - rowids still name source rows (T16).
def test_rowids_survive_filtering(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?team__exact=red&_shape=objects")
    assert [row["rowid"] for row in payload["rows"]] == [2, 4]


# Phrase: "Params without `_` and without `__` are ignored as filters." - a bare column
# name selects nothing and fails nothing.
def test_a_param_without_a_comparator_is_ignored(endpoint):
    response = endpoint(TEAMS_CSV)("?name=ada")
    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 4


# Phrase: "Params without `_` and without `__` are ignored as filters." - including names
# that match no column at all.
def test_an_unrelated_param_is_ignored(endpoint):
    response = endpoint(TEAMS_CSV)("?callback=render&page=2")
    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 4


# Phrase: "Params without `_` and without `__` are ignored" - being ignored, they may
# repeat without tripping the duplicate rule.
def test_ignored_params_may_repeat(endpoint):
    assert endpoint(TEAMS_CSV)("?name=ada&name=grace").status_code == 200


# Phrase: "Filtering precedes sorting." + "Pagination runs on filtered+sorted results" -
# filters compose with the response shaping controls.
@pytest.mark.parametrize("query", ["&_shape=objects", "&_total=hide", "&_rowid=hide"])
def test_filters_compose_with_shape_controls(endpoint, query):
    response = endpoint(TEAMS_CSV)(f"?team__exact=blue{query}")
    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 2
