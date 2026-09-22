"""Spec section: Column-Level Filtering.

`GET /datasets/<id>` accepts `<column>__<comparator>=<value>` filter params.
"""

import pytest

import datagate

# A deliberately mixed table: `name` is text, `age` is numeric, `note` mixes
# numeric-looking and non-numeric cells inside one column, and `City` differs
# from `city` only by case so that case-sensitive column matching is testable.
MIXED = (
    "name,age,note,City\n"
    "alice,30,7,Rome\n"
    "Alice,4,x,rome\n"
    "bob,12,,Oslo\n"
    "carol,7,3.5,Rome\n"
)

# Simple two-column numeric table for ordering/pagination interplay.
NUMS = "i,v\n3,c\n1,a\n2,b\n5,e\n4,d\n"


@pytest.fixture
def endpoint(convert, client):
    """Ingest a CSV once and return `get(query_string) -> response`."""

    def _endpoint(path, body=MIXED, **kwargs):
        response = convert(path, body, **kwargs)
        assert response.status_code == 200, response.get_data(as_text=True)
        url = response.get_json()["endpoint"]

        def get(query=None):
            return client.get(url, query_string=query or {})

        return get

    return _endpoint


def names(payload):
    """The `name` column of a `lists`-shaped payload, in response order."""
    index = payload["columns"].index("name")
    return [row[index] for row in payload["rows"]]


def numbered(count, prefix="i,v\n"):
    """`count` data rows: i = 0..count-1, v = 2*i."""
    return prefix + "".join("{},{}\n".format(i, i * 2) for i in range(count))


# ==========================================================================
# Phrase: "`GET /datasets/<id>` accepts filter params in this form:
#          `<column>__<comparator>=<value>`"
# ==========================================================================


# Phrase: the endpoint accepts a well-formed filter param at all.
def test_wellformed_filter_is_accepted(endpoint):
    response = endpoint("/f-accept.csv")({"name__exact": "bob"})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# Phrase: "<column>__<comparator>=<value>" -- the filter selects rows.
# Context: only matching rows come back; `columns` is unchanged.
def test_filter_selects_rows(endpoint):
    payload = endpoint("/f-select.csv")({"name__exact": "bob"}).get_json()
    assert names(payload) == ["bob"]
    assert payload["columns"] == ["name", "age", "note", "City"]


# Phrase: "<column>__<comparator>=<value>"
# Context: a filter matching nothing is a success with an empty `rows`.
def test_filter_matching_nothing_is_empty_success(endpoint):
    response = endpoint("/f-none.csv")({"name__exact": "nobody"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["rows"] == []
    assert payload["total"] == 0


# Phrase: "<column>__<comparator>=<value>"
# Context: T26 -- the split is on the LAST `__`, so a column whose own name
# contains `__` is still addressable.
def test_column_name_containing_double_underscore(endpoint):
    body = "a__b,c\nkeep,1\ndrop,2\n"
    payload = endpoint("/f-dunder.csv", body)({"a__b__exact": "keep"}).get_json()
    assert payload["rows"] == [["keep", 1]]


# Phrase: "<column>__<comparator>=<value>"
# Context: filtering leaves `rowid` bound to the source row, not the position
# in the filtered page.
def test_filter_preserves_rowid(endpoint):
    payload = endpoint("/f-rowid.csv")(
        {"name__exact": "carol", "_shape": "objects"}
    ).get_json()
    assert payload["rows"] == [
        {"rowid": 4, "name": "carol", "age": 7, "note": 3.5, "City": "Rome"}
    ]


# ==========================================================================
# Phrase: "Control params (names beginning with `_`) are not filters."
# ==========================================================================


# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: the documented controls keep working alongside a filter.
def test_controls_are_not_treated_as_filters(endpoint):
    response = endpoint("/f-ctl.csv")({"_size": "2", "_shape": "objects"})
    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 2


# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: T34 -- a leading `_` wins even when the name also contains `__`,
# so this is an unrecognised control and is ignored, not an unknown column.
def test_underscore_prefixed_name_with_dunder_is_not_a_filter(endpoint):
    response = endpoint("/f-ctl-dunder.csv")({"_nope__exact": "zzz"})
    assert response.status_code == 200
    assert len(response.get_json()["rows"]) == 4


# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: a real column named `_x` is therefore not filterable; the param is
# ignored rather than applied.
def test_underscore_column_is_not_filterable(endpoint):
    body = "_x,y\np,1\nq,2\n"
    payload = endpoint("/f-uscore-col.csv", body)({"_x__exact": "p"}).get_json()
    assert payload["total"] == 2


# ==========================================================================
# Comparators -- Phrase: "`exact`: case-sensitive string equality."
# ==========================================================================


# Phrase: "`exact`: case-sensitive string equality."
def test_exact_matches_whole_value(endpoint):
    payload = endpoint("/f-exact.csv")({"name__exact": "alice"}).get_json()
    assert names(payload) == ["alice"]


# Phrase: "`exact`: ... string equality" -- a prefix is not equality.
def test_exact_rejects_partial_value(endpoint):
    payload = endpoint("/f-exact-part.csv")({"name__exact": "ali"}).get_json()
    assert payload["rows"] == []


# Phrase: "`exact`: case-sensitive string equality."
# Context: `alice` and `Alice` are distinct rows; only the exact case matches.
def test_exact_is_case_sensitive(endpoint):
    lower = endpoint("/f-exact-lc.csv")({"name__exact": "alice"}).get_json()
    upper = endpoint("/f-exact-uc.csv")({"name__exact": "Alice"}).get_json()
    assert names(lower) == ["alice"]
    assert names(upper) == ["Alice"]


# Phrase: "`exact`: ... string equality."
# Context: T25 -- a cell inferred as a JSON number is compared by its text.
def test_exact_matches_numeric_cell_by_text(endpoint):
    payload = endpoint("/f-exact-num.csv")({"age__exact": "30"}).get_json()
    assert names(payload) == ["alice"]


# Phrase: "`exact`: ... string equality" -- so `30` and `30.0` differ.
def test_exact_numeric_text_is_not_numeric_equality(endpoint):
    payload = endpoint("/f-exact-num2.csv")({"age__exact": "30.0"}).get_json()
    assert payload["rows"] == []


# Phrase: "`exact`" with an empty value.
# Context: T35 -- empty is a real cell value (bob's `note`), not an error.
def test_exact_empty_value_matches_blank_cell(endpoint):
    response = endpoint("/f-exact-empty.csv")({"note__exact": ""})
    assert response.status_code == 200
    assert names(response.get_json()) == ["bob"]


# ==========================================================================
# Phrase: "`contains`: case-sensitive substring."
# ==========================================================================


# Phrase: "`contains`: ... substring."
def test_contains_matches_substring(endpoint):
    payload = endpoint("/f-contains.csv")({"name__contains": "li"}).get_json()
    assert names(payload) == ["alice", "Alice"]


# Phrase: "`contains`: case-sensitive substring."
def test_contains_is_case_sensitive(endpoint):
    payload = endpoint("/f-contains-cs.csv")({"City__contains": "Rom"}).get_json()
    assert names(payload) == ["alice", "carol"]


# Phrase: "`contains`: ... substring" -- a whole value is also a substring.
def test_contains_matches_full_value(endpoint):
    payload = endpoint("/f-contains-full.csv")({"name__contains": "bob"}).get_json()
    assert names(payload) == ["bob"]


# Phrase: "`contains`" against a numeric cell (T25: compared as text).
def test_contains_matches_numeric_cell_by_text(endpoint):
    payload = endpoint("/f-contains-num.csv")({"age__contains": "1"}).get_json()
    assert names(payload) == ["bob"]


# Phrase: "`contains`" with an empty value (T35): every row contains "".
def test_contains_empty_value_matches_everything(endpoint):
    response = endpoint("/f-contains-empty.csv")({"name__contains": ""})
    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# ==========================================================================
# Phrase: "`less`: numeric strict less (`float` parse on stored and filter
#          values)." / "`greater`: numeric strict greater."
# ==========================================================================


# Phrase: "`less`: numeric strict less".
def test_less_selects_smaller_values(endpoint):
    payload = endpoint("/f-less.csv")({"age__less": "12"}).get_json()
    assert sorted(names(payload)) == ["Alice", "carol"]


# Phrase: "`less`: numeric STRICT less" -- the boundary value is excluded.
def test_less_is_strict(endpoint):
    payload = endpoint("/f-less-strict.csv")({"age__less": "4"}).get_json()
    assert payload["rows"] == []


# Phrase: "`greater`: numeric strict greater".
def test_greater_selects_larger_values(endpoint):
    payload = endpoint("/f-greater.csv")({"age__greater": "12"}).get_json()
    assert names(payload) == ["alice"]


# Phrase: "`greater`: numeric STRICT greater" -- the boundary is excluded.
def test_greater_is_strict(endpoint):
    payload = endpoint("/f-greater-strict.csv")({"age__greater": "30"}).get_json()
    assert payload["rows"] == []


# Phrase: "numeric strict less" -- comparison is numeric, not lexicographic.
# Context: lexicographically "12" > "4"; numerically 4 < 12.
def test_numeric_comparison_is_not_lexicographic(endpoint):
    payload = endpoint("/f-num-order.csv")({"age__less": "8"}).get_json()
    assert sorted(names(payload)) == ["Alice", "carol"]


# Phrase: "(`float` parse on stored and filter values)".
# Context: a fractional filter value against integer cells.
def test_float_filter_value_against_integer_cells(endpoint):
    payload = endpoint("/f-float-filter.csv")({"age__less": "7.5"}).get_json()
    assert sorted(names(payload)) == ["Alice", "carol"]


# Phrase: "(`float` parse on stored and filter values)".
# Context: a fractional stored value (`note` 3.5) compared to an integer.
def test_float_stored_value(endpoint):
    payload = endpoint("/f-float-stored.csv")({"note__less": "4"}).get_json()
    assert names(payload) == ["carol"]


# Phrase: "(`float` parse on ... filter values)" -- signs are accepted.
def test_negative_filter_value(endpoint):
    body = "n,v\nneg,-5\nzero,0\npos,5\n"
    payload = endpoint("/f-neg.csv", body)({"v__less": "0"}).get_json()
    assert payload["rows"] == [["neg", -5]]


# ==========================================================================
# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# ==========================================================================


@pytest.mark.parametrize("comparator", ["less", "greater"])
@pytest.mark.parametrize("value", ["abc", "", "1,5", "12px", "--3", "1.2.3"])
# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
def test_non_numeric_filter_value_is_400(endpoint, comparator, value):
    response = endpoint("/f-nan-{}-{}.csv".format(comparator, value.encode("utf-8").hex()))(
        {"age__{}".format(comparator): value}
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# Phrase: "non-numeric filter values return `HTTP 400`."
# Context: the check applies even when the column exists and has numeric cells.
def test_non_numeric_filter_value_400_beats_empty_result(endpoint):
    response = endpoint("/f-nan-vs-empty.csv")({"age__less": "abc"})
    assert response.status_code == 400


# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# Context: the rule is scoped to the numeric comparators -- `exact`/`contains`
# accept any text.
@pytest.mark.parametrize("comparator", ["exact", "contains"])
def test_non_numeric_value_is_fine_for_string_comparators(endpoint, comparator):
    response = endpoint("/f-str-ok-{}.csv".format(comparator))(
        {"name__{}".format(comparator): "abc"}
    )
    assert response.status_code == 200


# Phrase: "(`float` parse ...)" / T30 -- `float()` accepts `nan` and `inf`, so
# they are numeric filter values; `nan` simply matches nothing.
def test_float_parseable_specials_are_numeric(endpoint):
    response = endpoint("/f-nan-value.csv")({"age__less": "nan"})
    assert response.status_code == 200
    assert response.get_json()["rows"] == []


# Phrase: "(`float` parse ...)" / T30 -- `inf` parses and matches every
# numeric cell under `less`.
def test_infinite_filter_value_matches_all_numeric(endpoint):
    response = endpoint("/f-inf-value.csv")({"age__less": "inf"})
    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# ==========================================================================
# Phrase: "Rows with non-numeric stored values are not matched for numeric
#          comparators."
# ==========================================================================


# Phrase: "Rows with non-numeric stored values are not matched".
# Context: `note` holds 7, "x", "" and 3.5; only the numeric cells can match.
def test_non_numeric_stored_values_excluded_by_less(endpoint):
    payload = endpoint("/f-stored-less.csv")({"note__less": "1000"}).get_json()
    assert sorted(names(payload)) == ["alice", "carol"]


# Phrase: "Rows with non-numeric stored values are not matched" -- `greater`.
def test_non_numeric_stored_values_excluded_by_greater(endpoint):
    payload = endpoint("/f-stored-greater.csv")({"note__greater": "-1000"}).get_json()
    assert sorted(names(payload)) == ["alice", "carol"]


# Phrase: "Rows with non-numeric stored values are not matched".
# Context: an all-text column yields an empty result, never a 500.
def test_numeric_comparator_on_text_column_is_empty(endpoint):
    response = endpoint("/f-text-col.csv")({"name__greater": "0"})
    assert response.status_code == 200
    assert response.get_json()["rows"] == []


# Phrase: "Rows with non-numeric stored values are not matched".
# Context: excluded rows are excluded from `total` too.
def test_non_numeric_stored_values_excluded_from_total(endpoint):
    payload = endpoint("/f-stored-total.csv")({"note__greater": "-1000"}).get_json()
    assert payload["total"] == 2


# ==========================================================================
# Phrase: "Multiple filters are ANDed."
# ==========================================================================


# Phrase: "Multiple filters are ANDed."
def test_two_filters_are_anded(endpoint):
    payload = endpoint("/f-and.csv")(
        {"City__exact": "Rome", "age__greater": "10"}
    ).get_json()
    assert names(payload) == ["alice"]


# Phrase: "Multiple filters are ANDed" -- an AND with no overlap is empty.
def test_anded_filters_with_no_overlap(endpoint):
    payload = endpoint("/f-and-empty.csv")(
        {"name__exact": "bob", "City__exact": "Rome"}
    ).get_json()
    assert payload["rows"] == []


# Phrase: "Multiple filters are ANDed."
# Context: T29 -- two different comparators on ONE column form a range and are
# ANDed rather than being rejected as duplicates.
def test_two_comparators_on_one_column_form_a_range(endpoint):
    response = endpoint("/f-range.csv")({"age__greater": "5", "age__less": "20"})
    assert response.status_code == 200
    assert names(response.get_json()) == ["bob", "carol"]


# Phrase: "Multiple filters are ANDed" -- three at once.
def test_three_filters_are_anded(endpoint):
    payload = endpoint("/f-and3.csv")(
        {"name__contains": "a", "age__less": "10", "City__exact": "Rome"}
    ).get_json()
    assert names(payload) == ["carol"]


# ==========================================================================
# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
# ==========================================================================


# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
def test_duplicate_filter_key_is_400(endpoint):
    response = endpoint("/f-dup.csv")({"name__exact": ["alice", "bob"]})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Duplicate filter keys are invalid" -- T29: identical values too.
def test_duplicate_filter_key_identical_values_is_400(endpoint):
    response = endpoint("/f-dup-same.csv")({"name__exact": ["alice", "alice"]})
    assert response.status_code == 400


# Phrase: "Duplicate filter keys are invalid" -- also for numeric comparators.
def test_duplicate_numeric_filter_key_is_400(endpoint):
    response = endpoint("/f-dup-num.csv")({"age__less": ["5", "9"]})
    assert response.status_code == 400


# Phrase: "Duplicate filter keys are invalid".
# Context: the duplicate is rejected even when one occurrence is empty.
def test_duplicate_filter_key_with_empty_occurrence_is_400(endpoint):
    response = endpoint("/f-dup-empty.csv")({"name__contains": ["a", ""]})
    assert response.status_code == 400


# ==========================================================================
# Phrase: "Column matching is exact and case-sensitive."
# ==========================================================================


# Phrase: "Column matching is ... case-sensitive."
# Context: `City` exists, `city` does not -> unknown filter column.
def test_column_match_is_case_sensitive(endpoint):
    response = endpoint("/f-col-case.csv")({"city__exact": "Rome"})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "Column matching is exact" -- no prefix/substring matching.
def test_column_match_is_not_a_prefix_match(endpoint):
    response = endpoint("/f-col-prefix.csv")({"nam__exact": "bob"})
    assert response.status_code == 400


# Phrase: "Column matching is exact" -- no whitespace tolerance.
def test_column_match_does_not_strip_whitespace(endpoint):
    response = endpoint("/f-col-space.csv")({" name__exact": "bob"})
    assert response.status_code == 400


# Phrase: "Column matching is exact and case-sensitive."
# Context: a column whose header really does contain a space is matchable.
def test_column_with_space_in_header_is_matchable(endpoint):
    body = "first name,v\nzed,1\nann,2\n"
    payload = endpoint("/f-col-hdr-space.csv", body)(
        {"first name__exact": "ann"}
    ).get_json()
    assert payload["rows"] == [["ann", 2]]


# Phrase: "Unknown filter column" -- T31: `rowid` is not a column.
def test_rowid_is_not_a_filterable_column(endpoint):
    response = endpoint("/f-rowid-col.csv")({"rowid__greater": "1"})
    assert response.status_code == 400


# ==========================================================================
# Phrase: "Filtering precedes sorting."
# ==========================================================================


# Phrase: "Filtering precedes sorting."
# Context: the surviving rows are sorted among themselves.
def test_filter_then_sort(endpoint):
    payload = endpoint("/f-sort.csv", NUMS)(
        {"v__contains": "", "_sort": "i"}
    ).get_json()
    assert [row[0] for row in payload["rows"]] == [1, 2, 3, 4, 5]


# Phrase: "Filtering precedes sorting."
# Context: sorting a filtered subset yields the subset in order, not the
# full-table order truncated.
def test_sort_applies_to_filtered_subset(endpoint):
    payload = endpoint("/f-sort-subset.csv", NUMS)(
        {"i__less": "4", "_sort_desc": "i"}
    ).get_json()
    assert [row[0] for row in payload["rows"]] == [3, 2, 1]


# Phrase: "Filtering precedes sorting."
# Context: rows removed by the filter cannot reappear because of the sort.
def test_filter_survives_descending_sort(endpoint):
    payload = endpoint("/f-sort-desc.csv")(
        {"City__exact": "Rome", "_sort_desc": "age"}
    ).get_json()
    assert names(payload) == ["alice", "carol"]


# ==========================================================================
# Phrase: "Pagination runs on filtered+sorted results."
# ==========================================================================


# Phrase: "Pagination runs on filtered+sorted results."
# Context: `_size` slices the filtered set, so a page can be full even though
# the filter removed most of the table.
def test_size_pages_the_filtered_set(endpoint):
    payload = endpoint("/f-page-size.csv", numbered(60))(
        {"i__greater": "49", "_size": "3"}
    ).get_json()
    assert [row[0] for row in payload["rows"]] == [50, 51, 52]


# Phrase: "Pagination runs on filtered+sorted results."
# Context: `_offset` counts within the filtered set, not the source table.
def test_offset_counts_within_filtered_set(endpoint):
    payload = endpoint("/f-page-offset.csv", numbered(60))(
        {"i__greater": "49", "_offset": "2", "_size": "2"}
    ).get_json()
    assert [row[0] for row in payload["rows"]] == [52, 53]


# Phrase: "Pagination runs on filtered+sorted results."
# Context: filter, then sort, then page -- all three composed.
def test_filter_sort_and_page_compose(endpoint):
    payload = endpoint("/f-page-all.csv", numbered(60))(
        {"i__less": "10", "_sort_desc": "i", "_size": "3", "_offset": "1"}
    ).get_json()
    assert [row[0] for row in payload["rows"]] == [8, 7, 6]


# Phrase: "Pagination runs on filtered+sorted results."
# Context: an offset past the end of the filtered set gives an empty page.
def test_offset_past_filtered_end_is_empty(endpoint):
    payload = endpoint("/f-page-past.csv")(
        {"City__exact": "Rome", "_offset": "5"}
    ).get_json()
    assert payload["rows"] == []
    assert payload["total"] == 2


# Phrase: "Pagination runs on filtered+sorted results."
# Context: the default 100-row page applies to the filtered set.
def test_default_page_applies_to_filtered_set(endpoint):
    payload = endpoint("/f-page-default.csv", numbered(250))(
        {"i__greater": "9"}
    ).get_json()
    assert len(payload["rows"]) == 100
    assert payload["rows"][0][0] == 10


# ==========================================================================
# Phrase: "`total` counts filtered rows before pagination."
# ==========================================================================


# Phrase: "`total` counts filtered rows before pagination."
def test_total_counts_filtered_rows(endpoint):
    payload = endpoint("/f-total.csv")({"City__contains": "Rome"}).get_json()
    assert payload["total"] == 2


# Phrase: "`total` counts filtered rows BEFORE pagination."
def test_total_ignores_size_and_offset(endpoint):
    payload = endpoint("/f-total-page.csv", numbered(250))(
        {"i__greater": "9", "_size": "5", "_offset": "3"}
    ).get_json()
    assert payload["total"] == 240
    assert len(payload["rows"]) == 5


# Phrase: "`total` counts filtered rows" -- and stays an integer.
def test_total_is_integer(endpoint):
    payload = endpoint("/f-total-int.csv")({"age__greater": "0"}).get_json()
    assert isinstance(payload["total"], int)
    assert not isinstance(payload["total"], bool)


# Phrase: "`total` counts filtered rows" -- `_total=hide` still hides it.
def test_total_hidden_still_hidden_with_filters(endpoint):
    payload = endpoint("/f-total-hide.csv")(
        {"age__greater": "0", "_total": "hide"}
    ).get_json()
    assert "total" not in payload


# ==========================================================================
# Phrase: "Query timeout returns `HTTP 400`."
# ==========================================================================


# Phrase: "Query timeout returns `HTTP 400`."
# Context: T32 -- the budget is the module-level `QUERY_TIMEOUT` (seconds).
def test_query_timeout_returns_400(endpoint, monkeypatch):
    get = endpoint("/f-timeout.csv", numbered(500))
    monkeypatch.setattr(datagate, "QUERY_TIMEOUT", 0.0)
    response = get({"i__greater": "1"})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# Phrase: "Query timeout returns `HTTP 400`."
# Context: the timeout applies to an unfiltered query too.
def test_query_timeout_without_filters(endpoint, monkeypatch):
    get = endpoint("/f-timeout-plain.csv", numbered(500))
    monkeypatch.setattr(datagate, "QUERY_TIMEOUT", 0.0)
    assert get().status_code == 400


# Phrase: "Query timeout returns `HTTP 400`."
# Context: a generous budget does not trip on an ordinary query.
def test_no_timeout_under_normal_budget(endpoint, monkeypatch):
    get = endpoint("/f-timeout-ok.csv", numbered(500))
    monkeypatch.setattr(datagate, "QUERY_TIMEOUT", 30.0)
    response = get({"i__greater": "1"})
    assert response.status_code == 200
    assert response.get_json()["total"] == 498


# ==========================================================================
# Error handling -- Phrase: the error envelope
#   `{"ok": false, "error": "<message>"}` with status 400.
# ==========================================================================


ERROR_CASES = {
    # Phrase: "Invalid comparator (`exact|contains|less|greater`)".
    "invalid_comparator": {"name__nope": "x"},
    # Phrase: invalid comparator -- comparator names are case-sensitive.
    "comparator_case": {"name__EXACT": "alice"},
    # Phrase: invalid comparator -- an empty comparator suffix.
    "empty_comparator": {"name__": "alice"},
    # Phrase: "Comparator target not numeric (`__less`/`__greater`)".
    "not_numeric_less": {"age__less": "abc"},
    "not_numeric_greater": {"age__greater": "abc"},
    # Phrase: "Unknown filter column".
    "unknown_column": {"nosuch__exact": "x"},
}


@pytest.mark.parametrize("case", sorted(ERROR_CASES))
# Phrase: every documented condition is 400 with `{"ok": false, "error": ...}`.
def test_error_envelope(endpoint, case):
    response = endpoint("/f-err-{}.csv".format(case))(ERROR_CASES[case])
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    assert "rows" not in payload and "columns" not in payload


# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: T34 -- `__exact=x` begins with `_`, so it never reaches the filter
# grammar at all; it is an unrecognised control and is ignored.
def test_empty_column_name_param_is_ignored(endpoint):
    response = endpoint("/f-err-empty-col.csv")({"__exact": "x"})
    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# Phrase: "Duplicate filter key | 400 | {"ok": false, "error": "<message>"}".
def test_duplicate_key_error_envelope(endpoint):
    response = endpoint("/f-err-dup.csv")({"age__less": ["1", "2"]})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# Phrase: "Invalid comparator (`exact|contains|less|greater`)".
# Context: T27 -- when both the comparator and the column are unknown, the
# comparator is reported first.
def test_invalid_comparator_reported_before_unknown_column(endpoint):
    response = endpoint("/f-err-both.csv")({"nosuch__nope": "x"})
    assert response.status_code == 400
    assert "nope" in response.get_json()["error"]


# Phrase: "Unknown filter column".
# Context: the column check runs even when the comparator is valid and the
# value would be fine.
def test_unknown_column_with_valid_comparator(endpoint):
    for comparator, value in (
        ("exact", "x"),
        ("contains", "x"),
        ("less", "1"),
        ("greater", "1"),
    ):
        response = endpoint("/f-err-col-{}.csv".format(comparator))(
            {"nosuch__{}".format(comparator): value}
        )
        assert response.status_code == 400, comparator


# Phrase: error responses carry the standard CORS header like any response.
def test_error_response_has_cors_header(endpoint):
    response = endpoint("/f-err-cors.csv")({"name__nope": "x"})
    assert response.headers["Access-Control-Allow-Origin"] == "*"


# ==========================================================================
# Phrase: "Params without `_` and without `__` are ignored as filters."
# ==========================================================================


# Phrase: "Params without `_` and without `__` are ignored as filters."
def test_plain_param_is_ignored(endpoint):
    response = endpoint("/f-ign.csv")({"foo": "bar"})
    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: even when the name collides with a real column, a param with no
# comparator suffix is not a filter.
def test_bare_column_name_param_is_ignored(endpoint):
    response = endpoint("/f-ign-col.csv")({"name": "bob"})
    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: T28 -- a single embedded `_` is not a filter marker either.
def test_single_underscore_param_is_ignored(endpoint):
    response = endpoint("/f-ign-us.csv")({"foo_bar": "1"})
    assert response.status_code == 200
    assert response.get_json()["total"] == 4


# Phrase: "Params without ... `__` are ignored as filters."
# Context: an ignored param does not count towards duplicate detection either.
def test_repeated_ignored_param_is_not_a_duplicate(endpoint):
    response = endpoint("/f-ign-dup.csv")({"foo": ["1", "2"]})
    assert response.status_code == 200


# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: ignored params sit alongside real filters without disturbing them.
def test_ignored_param_alongside_filter(endpoint):
    payload = endpoint("/f-ign-mix.csv")(
        {"foo": "bar", "name__exact": "bob"}
    ).get_json()
    assert names(payload) == ["bob"]
