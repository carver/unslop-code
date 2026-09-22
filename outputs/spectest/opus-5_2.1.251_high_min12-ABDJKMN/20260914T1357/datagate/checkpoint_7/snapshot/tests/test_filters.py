"""Spec tests for column-level filtering on /datasets/<id>.

Each section quotes the spec phrase (and its context) that it covers.
"""
import os
import subprocess
import sys

import pytest

from conftest import ROOT, DATAGATE, Client, free_port, wait_for_port


# name,age,city — `age` is numeric, `score` mixes numbers and text.
PEOPLE = (
    "name,age,city\n"
    "ada,36,London\n"
    "grace,45,New York\n"
    "lin,29,london\n"
    "Ada,50,Paris\n"
)
MIXED = "label,score\na,10\nb,n/a\nc,2.5\nd,\ne,100\n"
MANY = "n,tag\n" + "".join("%d,%s\n" % (i, "even" if i % 2 == 0 else "odd")
                           for i in range(120))


@pytest.fixture
def ds(server, csv_url):
    """Convert a CSV body; return its /datasets/<id> endpoint path."""
    def make(body, name="flt"):
        url = csv_url(body, name=name)
        status, _, data = server.convert(url)
        assert status == 200, data
        return data["endpoint"]
    return make


def assert_error(status, data):
    """Spec: `{"ok": false, "error": "<message>"}` with status 400."""
    assert status == 400, data
    assert data is not None
    assert data["ok"] is False
    assert isinstance(data["error"], str) and data["error"].strip()


def names(payload):
    """The `name` column of a lists-shaped payload, in order."""
    return [row[0] for row in payload["rows"]]


# ==========================================================================
# Spec: "`GET /datasets/<id>` accepts filter params in this form:
#        `<column>__<comparator>=<value>`"
# ==========================================================================
def test_filter_param_is_accepted(server, ds):
    endpoint = ds(PEOPLE, name="accept")
    status, _, data = server.get(endpoint + "?name__exact=ada")
    assert status == 200, data
    assert data["ok"] is True


# Spec: the filtered response keeps the normal envelope.
def test_filtered_response_envelope(server, ds):
    endpoint = ds(PEOPLE, name="envelope")
    data = server.get(endpoint + "?name__exact=ada")[2]
    assert data["ok"] is True
    assert data["columns"] == ["name", "age", "city"]
    assert data["rows"] == [["ada", 36, "London"]]
    assert "total" in data and "query_ms" in data


# Spec: "<column>__<comparator>=<value>" — the filter selects rows, it does not
# change the reported columns.
def test_filter_selects_rows_only(server, ds):
    endpoint = ds(PEOPLE, name="rows-only")
    data = server.get(endpoint + "?city__exact=Paris")[2]
    assert data["columns"] == ["name", "age", "city"]
    assert names(data) == ["Ada"]


# ==========================================================================
# Spec: "Control params (names beginning with `_`) are not filters."
# ==========================================================================
@pytest.mark.parametrize("query", [
    "?_size=2", "?_offset=1", "?_shape=objects", "?_sort=name",
    "?_sort_desc=age", "?_rowid=hide", "?_total=hide",
])
def test_control_params_are_not_filters(server, ds, query):
    endpoint = ds(PEOPLE, name="controls")
    status, _, data = server.get(endpoint + query)
    assert status == 200, data
    assert data["ok"] is True


# Spec: "Control params (names beginning with `_`) are not filters." — an
# unknown `_`-prefixed name is not parsed as a filter either (no 400).
@pytest.mark.parametrize("query", ["?_unknown=1", "?_name=ada", "?_=x"])
def test_underscore_params_are_never_filters(server, ds, query):
    endpoint = ds(PEOPLE, name="underscore")
    status, _, data = server.get(endpoint + query)
    assert status == 200, data
    assert len(data["rows"]) == 4


# ==========================================================================
# Spec: "### Comparators — `exact`: case-sensitive string equality."
# ==========================================================================
def test_exact_matches_equal_strings(server, ds):
    endpoint = ds(PEOPLE, name="exact")
    data = server.get(endpoint + "?city__exact=London")[2]
    assert names(data) == ["ada"]


# Spec: "`exact`: case-sensitive string equality." — case must match.
def test_exact_is_case_sensitive(server, ds):
    endpoint = ds(PEOPLE, name="exact-case")
    assert names(server.get(endpoint + "?name__exact=ada")[2]) == ["ada"]
    assert names(server.get(endpoint + "?name__exact=Ada")[2]) == ["Ada"]
    assert server.get(endpoint + "?name__exact=ADA")[2]["rows"] == []


# Spec: "string equality" — not a substring match.
def test_exact_is_not_a_substring_match(server, ds):
    endpoint = ds(PEOPLE, name="exact-sub")
    assert server.get(endpoint + "?city__exact=Lond")[2]["rows"] == []


# Spec: "`exact`: ... string equality" — a value no row carries selects nothing.
def test_exact_with_no_match_returns_empty_rows(server, ds):
    endpoint = ds(PEOPLE, name="exact-none")
    data = server.get(endpoint + "?name__exact=nobody")[2]
    assert data["rows"] == []
    assert data["ok"] is True


# ==========================================================================
# Spec: "`contains`: case-sensitive substring."
# ==========================================================================
def test_contains_matches_substring(server, ds):
    endpoint = ds(PEOPLE, name="contains")
    data = server.get(endpoint + "?city__contains=ondon")[2]
    assert names(data) == ["ada", "lin"]


# Spec: "`contains`: case-sensitive substring." — case must match.
def test_contains_is_case_sensitive(server, ds):
    endpoint = ds(PEOPLE, name="contains-case")
    assert names(server.get(endpoint + "?city__contains=London")[2]) == ["ada"]
    assert names(server.get(endpoint + "?city__contains=london")[2]) == ["lin"]
    assert server.get(endpoint + "?city__contains=LONDON")[2]["rows"] == []


# Spec: "substring" — a whole-value match is also a substring.
def test_contains_matches_whole_value(server, ds):
    endpoint = ds(PEOPLE, name="contains-whole")
    assert names(server.get(endpoint + "?city__contains=Paris")[2]) == ["Ada"]


# ==========================================================================
# Spec: "`less`: numeric strict less (`float` parse on stored and filter
#        values)."
# ==========================================================================
def test_less_selects_smaller_numbers(server, ds):
    endpoint = ds(PEOPLE, name="less")
    data = server.get(endpoint + "?age__less=40")[2]
    assert names(data) == ["ada", "lin"]


# Spec: "numeric strict less" — equal values are excluded.
def test_less_is_strict(server, ds):
    endpoint = ds(PEOPLE, name="less-strict")
    assert names(server.get(endpoint + "?age__less=36")[2]) == ["lin"]


# Spec: "`float` parse on stored and filter values" — the comparison is
# numeric, not lexicographic.
def test_less_compares_numerically_not_as_text(server, ds):
    endpoint = ds("id,n\na,9\nb,10\nc,100\n", name="less-numeric")
    data = server.get(endpoint + "?n__less=20")[2]
    assert data["rows"] == [["a", 9], ["b", 10]]


# Spec: "`float` parse ... on filter values" — a float filter value against
# integer cells.
def test_less_accepts_float_filter_value(server, ds):
    endpoint = ds(PEOPLE, name="less-float")
    assert names(server.get(endpoint + "?age__less=36.5")[2]) == ["ada", "lin"]


# ==========================================================================
# Spec: "`greater`: numeric strict greater."
# ==========================================================================
def test_greater_selects_larger_numbers(server, ds):
    endpoint = ds(PEOPLE, name="greater")
    assert names(server.get(endpoint + "?age__greater=40")[2]) == ["grace", "Ada"]


# Spec: "numeric strict greater" — equal values are excluded.
def test_greater_is_strict(server, ds):
    endpoint = ds(PEOPLE, name="greater-strict")
    assert names(server.get(endpoint + "?age__greater=45")[2]) == ["Ada"]


# Spec: "`float` parse on stored ... values" — decimal cells compare.
def test_greater_on_decimal_cells(server, ds):
    endpoint = ds("id,v\na,1.5\nb,2.5\nc,10.25\n", name="greater-dec")
    data = server.get(endpoint + "?v__greater=2")[2]
    assert data["rows"] == [["b", 2.5], ["c", 10.25]]


# ==========================================================================
# Spec: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# ==========================================================================
@pytest.mark.parametrize("comparator", ["less", "greater"])
@pytest.mark.parametrize("value", ["abc", "", "1,5", "12px", "None", "1.2.3"])
def test_non_numeric_filter_value_is_400(server, ds, comparator, value):
    endpoint = ds(PEOPLE, name="numeric-400")
    status, _, data = server.get(
        endpoint + "?age__%s=%s" % (comparator, value))
    assert_error(status, data)


# Spec: "non-numeric filter values return `HTTP 400`" — the same value is fine
# for the string comparators.
def test_non_numeric_value_is_fine_for_string_comparators(server, ds):
    endpoint = ds(PEOPLE, name="numeric-ok")
    assert server.get(endpoint + "?name__exact=abc")[0] == 200
    assert server.get(endpoint + "?name__contains=abc")[0] == 200


# ==========================================================================
# Spec: "Rows with non-numeric stored values are not matched for numeric
#        comparators."
# ==========================================================================
@pytest.mark.parametrize("comparator,value,expected", [
    ("less", "1000", ["a", "c", "e"]),
    ("greater", "-1000", ["a", "c", "e"]),
])
def test_non_numeric_cells_are_not_matched(server, ds, comparator, value,
                                           expected):
    endpoint = ds(MIXED, name="nonnum-cells")
    data = server.get(endpoint + "?score__%s=%s" % (comparator, value))[2]
    assert names(data) == expected


# Spec: "not matched" — empty cells are non-numeric too.
def test_empty_cells_are_not_matched_by_numeric_comparators(server, ds):
    endpoint = ds(MIXED, name="nonnum-empty")
    data = server.get(endpoint + "?score__greater=-1")[2]
    assert "d" not in names(data)


# ==========================================================================
# Spec: "### Filter behavior — Multiple filters are ANDed."
# ==========================================================================
def test_multiple_filters_are_anded(server, ds):
    endpoint = ds(PEOPLE, name="and")
    data = server.get(endpoint + "?age__greater=30&city__contains=ondon")[2]
    assert names(data) == ["ada"]


# Spec: "Multiple filters are ANDed." — two comparators on one column form a
# range (see AMBIGUITIES T42).
def test_two_comparators_on_one_column_and_together(server, ds):
    endpoint = ds(PEOPLE, name="and-range")
    data = server.get(endpoint + "?age__greater=30&age__less=46")[2]
    assert names(data) == ["ada", "grace"]


# Spec: "ANDed" — a conjunction nothing satisfies returns no rows.
def test_anded_filters_can_select_nothing(server, ds):
    endpoint = ds(PEOPLE, name="and-empty")
    data = server.get(endpoint + "?name__exact=ada&city__exact=Paris")[2]
    assert data["rows"] == []
    assert data["total"] == 0


# ==========================================================================
# Spec: "Duplicate filter keys are invalid (`HTTP 400`)."
# ==========================================================================
@pytest.mark.parametrize("query", [
    "?name__exact=ada&name__exact=grace",
    "?name__exact=ada&name__exact=ada",
    "?age__less=40&age__less=50",
    "?city__contains=o&city__contains=n",
])
def test_duplicate_filter_key_is_400(server, ds, query):
    endpoint = ds(PEOPLE, name="dup")
    status, _, data = server.get(endpoint + query)
    assert_error(status, data)


# ==========================================================================
# Spec: "Column matching is exact and case-sensitive."
# ==========================================================================
def test_unknown_filter_column_is_400(server, ds):
    endpoint = ds(PEOPLE, name="unknown-col")
    status, _, data = server.get(endpoint + "?nope__exact=x")
    assert_error(status, data)


# Spec: "Column matching is exact and case-sensitive."
@pytest.mark.parametrize("key", ["Name__exact", "NAME__exact", "nam__exact",
                                 "name___exact", " name__exact"])
def test_column_matching_is_exact_and_case_sensitive(server, ds, key):
    endpoint = ds(PEOPLE, name="col-case")
    status, _, data = server.get(endpoint + "?%s=ada" % key.replace(" ", "%20"))
    assert_error(status, data)


# ==========================================================================
# Spec: "Filtering precedes sorting."
# ==========================================================================
def test_filtering_precedes_sorting(server, ds):
    endpoint = ds(PEOPLE, name="sort-after")
    data = server.get(endpoint + "?age__greater=30&_sort=age")[2]
    assert names(data) == ["ada", "grace", "Ada"]


# Spec: "Filtering precedes sorting." — descending too.
def test_filtering_precedes_descending_sort(server, ds):
    endpoint = ds(PEOPLE, name="sort-desc-after")
    data = server.get(endpoint + "?age__less=46&_sort_desc=age")[2]
    assert names(data) == ["grace", "ada", "lin"]


# Spec: "Filtering precedes sorting." — rows removed by the filter cannot
# reappear at the top of a sort.
def test_sort_only_orders_surviving_rows(server, ds):
    endpoint = ds(PEOPLE, name="sort-survivors")
    data = server.get(endpoint + "?city__exact=Paris&_sort=name")[2]
    assert names(data) == ["Ada"]
    assert data["total"] == 1


# ==========================================================================
# Spec: "Pagination runs on filtered+sorted results."
# ==========================================================================
def test_pagination_runs_on_filtered_results(server, ds):
    endpoint = ds(MANY, name="page-filtered")
    data = server.get(endpoint + "?tag__exact=even&_size=3")[2]
    assert data["rows"] == [[0, "even"], [2, "even"], [4, "even"]]


# Spec: "Pagination runs on filtered+sorted results." — offset counts filtered
# rows, not source rows.
def test_offset_counts_filtered_rows(server, ds):
    endpoint = ds(MANY, name="page-offset")
    data = server.get(endpoint + "?tag__exact=odd&_offset=2&_size=2")[2]
    assert data["rows"] == [[5, "odd"], [7, "odd"]]


# Spec: "filtered+sorted results" — the page is cut after sorting.
def test_pagination_runs_after_sorting(server, ds):
    endpoint = ds(MANY, name="page-sorted")
    data = server.get(endpoint + "?tag__exact=even&_sort_desc=n&_size=2")[2]
    assert data["rows"] == [[118, "even"], [116, "even"]]


# Spec: "Pagination runs on filtered+sorted results." — the default page size
# still applies to the filtered set.
def test_default_page_size_applies_to_filtered_rows(server, ds):
    endpoint = ds(MANY, name="page-default")
    data = server.get(endpoint + "?n__greater=-1")[2]
    assert len(data["rows"]) == 100
    assert data["total"] == 120


# ==========================================================================
# Spec: "`total` counts filtered rows before pagination."
# ==========================================================================
def test_total_counts_filtered_rows(server, ds):
    endpoint = ds(MANY, name="total-filtered")
    data = server.get(endpoint + "?tag__exact=even")[2]
    assert data["total"] == 60


# Spec: "`total` counts filtered rows before pagination." — pagination does not
# shrink it.
@pytest.mark.parametrize("query", ["&_size=1", "&_offset=50", "&_size=2&_offset=4",
                                   "&_offset=500"])
def test_total_is_before_pagination(server, ds, query):
    endpoint = ds(MANY, name="total-before-page")
    data = server.get(endpoint + "?tag__exact=odd" + query)[2]
    assert data["total"] == 60


# Spec: "`total` counts filtered rows" — zero when nothing matches.
def test_total_is_zero_when_nothing_matches(server, ds):
    endpoint = ds(MANY, name="total-zero")
    data = server.get(endpoint + "?tag__exact=none")[2]
    assert data["total"] == 0
    assert data["rows"] == []


# Spec: "`total` counts filtered rows" — and is unaffected by sorting/shape.
def test_filtered_total_with_sort_and_shape(server, ds):
    endpoint = ds(MANY, name="total-shape")
    data = server.get(
        endpoint + "?tag__exact=even&_sort=n&_shape=objects&_size=1")[2]
    assert data["total"] == 60
    assert data["rows"][0]["tag"] == "even"


# ==========================================================================
# Spec: "Query timeout returns `HTTP 400`."
# ==========================================================================
def _spawn_with_timeout(port, timeout_ms, tag="timeout"):
    """Start datagate with an exhausted query budget (see AMBIGUITIES T36)."""
    env = dict(os.environ, DATAGATE_QUERY_TIMEOUT_MS=str(timeout_ms))
    log = open(os.path.join(ROOT, "tests", "_%s.log" % tag), "ab")
    return subprocess.Popen(
        [sys.executable, DATAGATE, "start", "--port", str(port),
         "--address", "127.0.0.1"],
        cwd=ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL, env=env,
    )


@pytest.fixture
def timed_out_server(csv_url):
    port = free_port()
    proc = _spawn_with_timeout(port, 0)
    assert wait_for_port("127.0.0.1", port), "datagate did not start"
    yield Client("http://127.0.0.1:%d" % port)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_query_timeout_is_400(timed_out_server, csv_url):
    url = csv_url(PEOPLE, name="timeout")
    endpoint = timed_out_server.convert(url)[2]["endpoint"]
    status, _, data = timed_out_server.get(endpoint + "?age__greater=1")
    assert_error(status, data)


# Spec: "Query timeout returns `HTTP 400`." — an ordinary query does not.
def test_normal_query_does_not_time_out(server, ds):
    endpoint = ds(MANY, name="no-timeout")
    assert server.get(endpoint + "?tag__exact=even")[0] == 200


# ==========================================================================
# Spec: "### Error Handling" table — every listed condition answers 400 with
#        `{"ok": false, "error": "<message>"}`.
# ==========================================================================
@pytest.mark.parametrize("query", [
    "?name__startswith=ada",     # invalid comparator
    "?name__EXACT=ada",          # comparator matching is case-sensitive
    "?name__=ada",               # empty comparator
    "?age__less=abc",            # comparator target not numeric
    "?age__greater=abc",         # comparator target not numeric
    "?nope__exact=x",            # unknown filter column
    "?name__exact=a&name__exact=b",  # duplicate filter key
])
def test_error_conditions_use_the_error_envelope(server, ds, query):
    endpoint = ds(PEOPLE, name="errors")
    status, headers, data = server.get(endpoint + query)
    assert_error(status, data)
    assert "json" in headers.get("Content-Type", "").lower()
    assert set(data) == {"ok", "error"}


# Spec: the error table lists the invalid comparator set
# (`exact|contains|less|greater`) — those four, and only those, are valid.
@pytest.mark.parametrize("comparator", ["exact", "contains", "less", "greater"])
def test_the_four_comparators_are_valid(server, ds, comparator):
    endpoint = ds(PEOPLE, name="valid-comparators")
    value = "1" if comparator in ("less", "greater") else "x"
    status, _, data = server.get(
        endpoint + "?age__%s=%s" % (comparator, value))
    assert status == 200, data


@pytest.mark.parametrize("comparator", [
    "equals", "eq", "like", "lt", "gt", "lte", "gte", "in", "Exact", "Contains",
])
def test_other_comparators_are_invalid(server, ds, comparator):
    endpoint = ds(PEOPLE, name="invalid-comparators")
    status, _, data = server.get(endpoint + "?age__%s=1" % comparator)
    assert_error(status, data)


# Spec: a filter error must not be confused with an unknown dataset id.
def test_unknown_dataset_is_still_404_with_filters(server):
    status, _, data = server.get("/datasets/no-such-id?nope__exact=1")
    assert status == 404
    assert data["ok"] is False


# ==========================================================================
# Spec: "Params without `_` and without `__` are ignored as filters."
# ==========================================================================
@pytest.mark.parametrize("query", [
    "?name=ada", "?age=36", "?nope=1", "?limit=1", "?sort=name", "?q=ada",
])
def test_params_without_underscores_are_ignored(server, ds, query):
    endpoint = ds(PEOPLE, name="ignored")
    status, _, data = server.get(endpoint + query)
    assert status == 200, data
    assert len(data["rows"]) == 4
    assert data["total"] == 4


# Spec: "ignored as filters" — an ignored param does not turn a valid filter
# into an error, and does not affect its result.
def test_ignored_params_do_not_disturb_real_filters(server, ds):
    endpoint = ds(PEOPLE, name="ignored-mixed")
    data = server.get(endpoint + "?name=grace&city__exact=Paris&zzz=1")[2]
    assert names(data) == ["Ada"]
    assert data["total"] == 1


# Spec: "ignored as filters" — an unknown column name without `__` is ignored
# rather than rejected.
def test_unknown_param_without_comparator_is_not_an_error(server, ds):
    endpoint = ds(PEOPLE, name="ignored-unknown")
    assert server.get(endpoint + "?unknown_column=42")[0] == 200
