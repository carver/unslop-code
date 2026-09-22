"""Spec section: Column-Level Filtering.

Every test is labelled with the minimal spec phrase it exercises.
"""
import pytest

from conftest import convert_ok

# name/city exercise the string comparators; score mixes ints, decimals,
# negatives and one non-numeric cell for the numeric comparators.
PEOPLE = (
    "name,city,score\n"
    "Alice,Paris,30\n"
    "bob,paris,7\n"
    "Carol,London,12.5\n"
    "Dave,Tokyo,n/a\n"
    "alice,Paris,-3\n"
)

# A header whose column name itself contains the `__` separator.
UNDERSCORES = "a__b,v\nkeep,1\ndrop,2\n"

# A dataset with an empty cell, for empty-value filters.
GAPS = "name,city\nAlice,Paris\nNobody,\n"

# 250 numbered rows for pagination arithmetic over a filtered set.
BIG = "n\n" + "".join(f"{i}\n" for i in range(250))


def endpoint_for(gate, origin, path, body):
    return convert_ok(gate, origin.add(path, body))


@pytest.fixture(scope="module")
def people_ep(gate, origin):
    return endpoint_for(gate, origin, "/flt-people.csv", PEOPLE)


@pytest.fixture(scope="module")
def under_ep(gate, origin):
    return endpoint_for(gate, origin, "/flt-underscores.csv", UNDERSCORES)


@pytest.fixture(scope="module")
def gaps_ep(gate, origin):
    return endpoint_for(gate, origin, "/flt-gaps.csv", GAPS)


@pytest.fixture(scope="module")
def big_ep(gate, origin):
    return endpoint_for(gate, origin, "/flt-big.csv", BIG)


def ok(gate, endpoint, query):
    """Send a raw query string (so repeats survive) and require 200."""
    resp = gate.get(f"{endpoint}?{query}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def bad(gate, endpoint, query):
    """Send a raw query string and require the documented 400 envelope."""
    resp = gate.get(f"{endpoint}?{query}")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]
    return body


def names(body):
    """`name` column values of a `lists`-shaped response, in order."""
    idx = body["columns"].index("name")
    return [row[idx] for row in body["rows"]]


# ---------------------------------------------------------------------------
# Phrase: "`GET /datasets/<id>` accepts filter params in this form:
#          `<column>__<comparator>=<value>`"
# Context: section preamble -- the shape of a filter parameter.
# ---------------------------------------------------------------------------
def test_filter_param_form_is_accepted(gate, people_ep):
    body = ok(gate, people_ep, "city__exact=Paris")
    assert body["ok"] is True
    assert names(body) == ["Alice", "alice"]


def test_filter_response_keeps_the_standard_envelope(gate, people_ep):
    body = ok(gate, people_ep, "city__exact=Paris")
    assert body["columns"] == ["name", "city", "score"]
    assert isinstance(body["rows"], list)
    assert isinstance(body["total"], int)
    assert isinstance(body["query_ms"], (int, float))


# ---------------------------------------------------------------------------
# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: control names must never be read as `<column>__<comparator>`.
# ---------------------------------------------------------------------------
def test_control_params_are_not_filters(gate, people_ep):
    body = ok(gate, people_ep, "_size=2&_shape=objects")
    assert len(body["rows"]) == 2
    assert body["total"] == 5  # no filtering happened


def test_underscore_prefixed_unknown_param_is_not_a_filter(gate, people_ep):
    # Begins with `_`, so it is a control name, not a filter -- no 400 for an
    # unknown column and no filtering. See AMBIGUITIES T29.
    body = ok(gate, people_ep, "_nope__exact=zzz")
    assert body["total"] == 5


def test_controls_and_filters_combine(gate, people_ep):
    body = ok(gate, people_ep, "city__exact=Paris&_shape=objects")
    assert [row["name"] for row in body["rows"]] == ["Alice", "alice"]
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# Phrase: "`exact`: case-sensitive string equality."
# Context: comparator table.
# ---------------------------------------------------------------------------
def test_exact_matches_whole_value(gate, people_ep):
    assert names(ok(gate, people_ep, "name__exact=Alice")) == ["Alice"]


def test_exact_is_case_sensitive(gate, people_ep):
    assert names(ok(gate, people_ep, "name__exact=ALICE")) == []
    assert names(ok(gate, people_ep, "name__exact=alice")) == ["alice"]


def test_exact_is_equality_not_substring(gate, people_ep):
    assert names(ok(gate, people_ep, "name__exact=Ali")) == []


def test_exact_on_a_numeric_column_compares_as_text(gate, people_ep):
    # Stored values are typed numbers; `exact` is string equality against
    # their textual form. See AMBIGUITIES T27.
    assert names(ok(gate, people_ep, "score__exact=30")) == ["Alice"]
    assert names(ok(gate, people_ep, "score__exact=12.5")) == ["Carol"]
    assert names(ok(gate, people_ep, "score__exact=n/a")) == ["Dave"]


def test_exact_with_empty_value_matches_nothing_here(gate, people_ep):
    assert names(ok(gate, people_ep, "name__exact=")) == []


# ---------------------------------------------------------------------------
# Phrase: "`contains`: case-sensitive substring."
# Context: comparator table.
# ---------------------------------------------------------------------------
def test_contains_matches_substrings(gate, people_ep):
    assert names(ok(gate, people_ep, "city__contains=Pari")) == ["Alice", "alice"]


def test_contains_is_case_sensitive(gate, people_ep):
    assert names(ok(gate, people_ep, "city__contains=PAR")) == []
    assert names(ok(gate, people_ep, "city__contains=par")) == ["bob"]


def test_contains_matches_the_whole_value_too(gate, people_ep):
    assert names(ok(gate, people_ep, "city__contains=London")) == ["Carol"]


def test_contains_on_a_numeric_column_uses_text(gate, people_ep):
    assert names(ok(gate, people_ep, "score__contains=2")) == ["Carol"]


# ---------------------------------------------------------------------------
# Phrase: "`less`: numeric strict less (`float` parse on stored and filter
#          values)."
# Context: comparator table.
# ---------------------------------------------------------------------------
def test_less_is_numeric_and_strict(gate, people_ep):
    assert names(ok(gate, people_ep, "score__less=12.5")) == ["bob", "alice"]


def test_less_excludes_the_boundary_value(gate, people_ep):
    assert names(ok(gate, people_ep, "score__less=-3")) == []


def test_less_parses_stored_and_filter_values_as_floats(gate, people_ep):
    # "7" < "12.5" numerically, even though "7" > "12.5" as text.
    assert names(ok(gate, people_ep, "score__less=7.5")) == ["bob", "alice"]
    assert names(ok(gate, people_ep, "score__less=30.0")) == ["bob", "Carol", "alice"]


# ---------------------------------------------------------------------------
# Phrase: "`greater`: numeric strict greater."
# Context: comparator table.
# ---------------------------------------------------------------------------
def test_greater_is_numeric_and_strict(gate, people_ep):
    assert names(ok(gate, people_ep, "score__greater=12.5")) == ["Alice"]


def test_greater_includes_everything_above(gate, people_ep):
    assert names(ok(gate, people_ep, "score__greater=-100")) == [
        "Alice",
        "bob",
        "Carol",
        "alice",
    ]


# ---------------------------------------------------------------------------
# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# Context: numeric comparator validation.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "score__less=abc",
    "score__greater=abc",
    "score__less=",
    "score__greater=",
    "score__less=12,5",
    "score__greater=one",
])
def test_non_numeric_filter_value_is_rejected(gate, people_ep, query):
    bad(gate, people_ep, query)


def test_numeric_filter_value_forms_that_float_accepts(gate, people_ep):
    # `float` parse, taken literally: exponents and surrounding space are
    # accepted. See AMBIGUITIES T30.
    assert names(ok(gate, people_ep, "score__greater=1e1")) == ["Alice", "Carol"]
    assert names(ok(gate, people_ep, "score__less=%20-1%20")) == ["alice"]


# ---------------------------------------------------------------------------
# Phrase: "Rows with non-numeric stored values are not matched for numeric
#          comparators."
# Context: the "n/a" score row.
# ---------------------------------------------------------------------------
def test_non_numeric_stored_values_never_match_less(gate, people_ep):
    assert "Dave" not in names(ok(gate, people_ep, "score__less=1000000"))


def test_non_numeric_stored_values_never_match_greater(gate, people_ep):
    assert "Dave" not in names(ok(gate, people_ep, "score__greater=-1000000"))


def test_non_numeric_stored_values_are_skipped_not_an_error(gate, people_ep):
    body = ok(gate, people_ep, "score__greater=-1000000")
    assert body["ok"] is True
    assert body["total"] == 4


def test_text_column_under_numeric_comparator_matches_nothing(gate, people_ep):
    assert names(ok(gate, people_ep, "name__less=99")) == []


# ---------------------------------------------------------------------------
# Phrase: "Multiple filters are ANDed."
# Context: filter behavior.
# ---------------------------------------------------------------------------
def test_multiple_filters_are_anded(gate, people_ep):
    assert names(ok(gate, people_ep, "city__exact=Paris&score__greater=0")) == ["Alice"]


def test_two_filters_on_the_same_column_are_anded(gate, people_ep):
    assert names(ok(gate, people_ep, "score__greater=0&score__less=13")) == [
        "bob",
        "Carol",
    ]


def test_anded_filters_can_produce_no_rows(gate, people_ep):
    both = ok(gate, people_ep, "city__exact=Paris&city__contains=Par")
    assert names(both) == ["Alice", "alice"]
    empty = ok(gate, people_ep, "city__exact=Paris&name__exact=Carol")
    assert empty["rows"] == []
    assert empty["total"] == 0


# ---------------------------------------------------------------------------
# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
# Context: filter behavior.
# ---------------------------------------------------------------------------
def test_duplicate_filter_key_is_rejected(gate, people_ep):
    bad(gate, people_ep, "city__exact=Paris&city__exact=London")


def test_duplicate_filter_key_with_identical_values_is_rejected(gate, people_ep):
    # Identical repeats are still repeats. See AMBIGUITIES T31.
    bad(gate, people_ep, "city__exact=Paris&city__exact=Paris")


def test_same_column_different_comparators_is_not_a_duplicate(gate, people_ep):
    body = ok(gate, people_ep, "city__exact=Paris&city__contains=Par")
    assert names(body) == ["Alice", "alice"]


# ---------------------------------------------------------------------------
# Phrase: "Column matching is exact and case-sensitive."
# Context: filter behavior.
# ---------------------------------------------------------------------------
def test_column_match_is_case_sensitive(gate, people_ep):
    bad(gate, people_ep, "City__exact=Paris")
    bad(gate, people_ep, "NAME__contains=A")


def test_column_match_is_not_a_prefix_match(gate, people_ep):
    bad(gate, people_ep, "nam__exact=Alice")
    bad(gate, people_ep, "names__exact=Alice")


def test_column_name_containing_the_separator(gate, under_ep):
    # `a__b__exact` splits at the last `__`. See AMBIGUITIES T26.
    body = ok(gate, under_ep, "a__b__exact=keep")
    assert body["rows"] == [["keep", 1]]


# ---------------------------------------------------------------------------
# Phrase: "Filtering precedes sorting."
# Context: filter behavior.
# ---------------------------------------------------------------------------
def test_filtering_precedes_sorting(gate, people_ep):
    body = ok(gate, people_ep, "city__contains=ar&_sort=name")
    assert names(body) == ["Alice", "alice", "bob"]


def test_filtering_precedes_descending_sorting(gate, people_ep):
    body = ok(gate, people_ep, "score__greater=0&_sort_desc=score")
    assert names(body) == ["Alice", "Carol", "bob"]


# ---------------------------------------------------------------------------
# Phrase: "Pagination runs on filtered+sorted results."
# Context: filter behavior.
# ---------------------------------------------------------------------------
def test_pagination_applies_to_the_filtered_sorted_set(gate, people_ep):
    body = ok(gate, people_ep, "score__greater=0&_sort=score&_size=1&_offset=1")
    assert names(body) == ["Carol"]


def test_offset_past_the_filtered_set_is_empty(gate, people_ep):
    body = ok(gate, people_ep, "city__exact=Paris&_offset=2")
    assert body["rows"] == []
    assert body["total"] == 2


def test_pagination_over_a_large_filtered_set(gate, big_ep):
    body = ok(gate, big_ep, "n__greater=199&_size=5&_offset=2")
    assert body["rows"] == [[202], [203], [204], [205], [206]]
    assert body["total"] == 50


# ---------------------------------------------------------------------------
# Phrase: "`total` counts filtered rows before pagination."
# Context: filter behavior.
# ---------------------------------------------------------------------------
def test_total_counts_filtered_rows(gate, people_ep):
    assert ok(gate, people_ep, "city__exact=Paris")["total"] == 2


def test_total_ignores_the_pagination_window(gate, people_ep):
    body = ok(gate, people_ep, "score__greater=-1000000&_size=1")
    assert len(body["rows"]) == 1
    assert body["total"] == 4


def test_total_hide_still_works_with_filters(gate, people_ep):
    body = ok(gate, people_ep, "city__exact=Paris&_total=hide")
    assert "total" not in body


# ---------------------------------------------------------------------------
# Phrase: "Query timeout returns `HTTP 400`."
# Context: filter behavior + error table.
# ---------------------------------------------------------------------------
def test_normal_filter_query_does_not_time_out(gate, big_ep):
    assert ok(gate, big_ep, "n__greater=0")["total"] == 249


def test_query_timeout_returns_400(fresh_gate, origin):
    """A zero-length query budget makes every dataset query time out.

    The spec gives no knob for the budget, so the implementation exposes one
    only for testing. See AMBIGUITIES T32.
    """
    from conftest import free_port

    g = fresh_gate(
        port=free_port(),
        address="127.0.0.1",
        env={"DATAGATE_QUERY_TIMEOUT_MS": "0"},
    )
    endpoint = convert_ok(g, origin.add("/flt-timeout.csv", PEOPLE))
    resp = g.get(f"{endpoint}?city__exact=Paris")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# ---------------------------------------------------------------------------
# Phrase: error table -- "Invalid comparator (`exact|contains|less|greater`)
#          | 400 | `{"ok": false, "error": "<message>"}`"
# Context: Error Handling.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "name__eq=Alice",
    "name__EXACT=Alice",
    "name__Contains=A",
    "name__lt=3",
    "name__=Alice",
    "name__exact__extra=Alice",
])
def test_invalid_comparator_is_rejected(gate, people_ep, query):
    bad(gate, people_ep, query)


def test_error_envelope_shape_for_invalid_comparator(gate, people_ep):
    resp = gate.get(f"{people_ep}?name__eq=Alice")
    assert resp.status_code == 400
    assert resp.json() == {"ok": False, "error": resp.json()["error"]}
    assert set(resp.json()) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: error table -- "Comparator target not numeric (`__less`/`__greater`)
#          | 400"
# Context: Error Handling.
# ---------------------------------------------------------------------------
def test_error_envelope_shape_for_non_numeric_target(gate, people_ep):
    body = bad(gate, people_ep, "score__less=abc")
    assert set(body) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: error table -- "Unknown filter column | 400"
# Context: Error Handling.
# ---------------------------------------------------------------------------
def test_unknown_filter_column_is_rejected(gate, people_ep):
    body = bad(gate, people_ep, "nope__exact=1")
    assert set(body) == {"ok", "error"}


def test_unknown_column_rejected_for_every_comparator(gate, people_ep):
    for comparator in ("exact", "contains", "less", "greater"):
        bad(gate, people_ep, f"nope__{comparator}=1")


def test_rowid_is_not_a_filterable_column(gate, people_ep):
    # `rowid` is response metadata, not a data column. See AMBIGUITIES T28.
    bad(gate, people_ep, "rowid__exact=2")


# ---------------------------------------------------------------------------
# Phrase: error table -- "Duplicate filter key | 400"
# Context: Error Handling.
# ---------------------------------------------------------------------------
def test_error_envelope_shape_for_duplicate_key(gate, people_ep):
    body = bad(gate, people_ep, "name__exact=Alice&name__exact=bob")
    assert set(body) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: closing rule.
# ---------------------------------------------------------------------------
def test_plain_param_is_ignored(gate, people_ep):
    body = ok(gate, people_ep, "foo=bar")
    assert body["total"] == 5


def test_plain_param_is_ignored_even_if_it_names_a_column(gate, people_ep):
    body = ok(gate, people_ep, "name=Alice")
    assert body["total"] == 5


def test_repeated_plain_param_is_not_a_duplicate_filter(gate, people_ep):
    body = ok(gate, people_ep, "foo=bar&foo=baz")
    assert body["total"] == 5


def test_single_underscore_in_the_middle_is_not_a_separator(gate, people_ep):
    # One underscore is neither a control prefix nor the `__` separator.
    body = ok(gate, people_ep, "name_exact=Alice")
    assert body["total"] == 5


def test_ignored_params_do_not_disturb_real_filters(gate, people_ep):
    body = ok(gate, people_ep, "foo=bar&city__exact=Paris")
    assert names(body) == ["Alice", "alice"]


# ---------------------------------------------------------------------------
# Phrase: whole-section integration -- filtering, sorting, pagination, total.
# Context: the four behaviors in one request.
# ---------------------------------------------------------------------------
def test_filter_sort_paginate_and_count_together(gate, big_ep):
    body = ok(gate, big_ep, "n__contains=1&n__less=120&_sort_desc=n&_size=3")
    assert body["rows"] == [[119], [118], [117]]
    assert body["total"] == 39


# ---------------------------------------------------------------------------
# Phrase: "`contains`: case-sensitive substring." / "`exact`: ... equality."
# Context: an empty filter value is still a filter. See AMBIGUITIES T34.
# ---------------------------------------------------------------------------
def test_empty_contains_value_matches_every_row(gate, people_ep):
    assert ok(gate, people_ep, "city__contains=")["total"] == 5


def test_empty_exact_value_matches_only_empty_cells(gate, gaps_ep):
    assert names(ok(gate, gaps_ep, "city__exact=")) == ["Nobody"]
