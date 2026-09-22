"""Spec section: Column-Level Filtering.

One test section per spec phrase, each tagged with the phrase and the context it
is being read in.  `table` converts a CSV once and returns a callable that issues
repeated `GET /datasets/<id>` queries against it.
"""
import pytest

# name/qty/price cover: mixed case text, an integer column with one non-numeric
# cell, and a decimal column.
CSV = (
    "name,qty,price\n"
    "widget,3,9.5\n"
    "Gadget,10,2.25\n"
    "gizmo,n/a,7\n"
    "widgetron,7,1.5\n"
)


@pytest.fixture()
def table(client, convert, origin):
    """Ingest a CSV body once; return a `query(query_string)` callable."""

    def _table(body=CSV):
        url = origin.add(body)
        status, payload = convert(source=url)
        assert status == 200, payload
        endpoint = payload["endpoint"]

        def query(query_string=None):
            resp = client.get(endpoint, query_string=query_string or {})
            return resp.status_code, resp.get_json()

        return query

    return _table


def names(body):
    """The `name` column of a lists-shaped response, in response order."""
    index = body["columns"].index("name")
    return [row[index] for row in body["rows"]]


def assert_error(status, body):
    assert status == 400
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# ============================================================ filter form ====

# Phrase: "`GET /datasets/<id>` accepts filter params in this form:
#          `<column>__<comparator>=<value>`"
# Context: a well-formed filter param is accepted and narrows `rows`.
def test_filter_param_is_accepted(table):
    query = table()
    status, body = query("name__exact=widget")
    assert status == 200
    assert body["ok"] is True
    assert names(body) == ["widget"]


# Phrase: "<column>__<comparator>=<value>"
# Context: no filter params at all -> every row is returned, as before.
def test_no_filters_returns_all_rows(table):
    query = table()
    _, body = query()
    assert names(body) == ["widget", "Gadget", "gizmo", "widgetron"]


# Phrase: "<column>__<comparator>=<value>"
# Context: filtering leaves the rest of the success envelope intact.
def test_filtered_response_keeps_envelope(table):
    query = table()
    status, body = query("qty__greater=0")
    assert status == 200
    assert set(body) >= {"ok", "columns", "rows", "query_ms"}
    assert body["columns"] == ["name", "qty", "price"]


# Phrase: "<column>__<comparator>=<value>"
# Context: a filter matching nothing is a success with an empty `rows`.
def test_filter_matching_nothing_is_empty_success(table):
    query = table()
    status, body = query("name__exact=absent")
    assert status == 200
    assert body["ok"] is True
    assert body["rows"] == []


# Phrase: "<column>__<comparator>=<value>"
# Context: the value may be empty; it then matches empty cells only.
# See AMBIGUITIES T34 (empty *value* is well-formed; empty column/comparator is not).
def test_empty_filter_value_matches_empty_cells(table):
    query = table("name,note\nalpha,\nbeta,hi\n")
    _, body = query("note__exact=")
    assert names(body) == ["alpha"]


# Phrase: "<column>__<comparator>=<value>"
# Context: filters apply identically under `_shape=objects`.
def test_filters_apply_under_objects_shape(table):
    query = table()
    _, body = query("name__exact=Gadget&_shape=objects")
    assert body["rows"] == [
        {"name": "Gadget", "qty": 10, "price": 2.25, "rowid": 3}
    ]


# ========================================================= control params ====

# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: the existing control params keep working alongside filters.
def test_control_params_are_not_filters(table):
    query = table()
    status, body = query("_size=2&_shape=lists")
    assert status == 200
    assert len(body["rows"]) == 2


# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: a `_`-prefixed name is never parsed as <column>__<comparator>, even
# when it contains `__` (AMBIGUITIES T32).
def test_underscore_prefixed_name_with_double_underscore_is_not_a_filter(table):
    query = table()
    status, body = query("_nosuch__exact=zzz")
    assert status == 200
    assert len(body["rows"]) == 4


# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: a column whose own name starts with `_` is therefore not filterable.
def test_underscore_named_column_is_not_filterable(table):
    query = table("_x,y\n1,2\n3,4\n")
    status, body = query("_x__exact=1")
    assert status == 200
    assert len(body["rows"]) == 2


# ============================================================ comparators ====

# Phrase: "`exact`: case-sensitive string equality."
# Context: equality, not substring - a strict prefix does not match.
def test_exact_is_full_string_equality(table):
    query = table()
    _, body = query("name__exact=widget")
    assert names(body) == ["widget"]


# Phrase: "`exact`: case-sensitive string equality."
# Context: case-sensitive - a differently-cased value matches nothing.
def test_exact_is_case_sensitive(table):
    query = table()
    _, body = query("name__exact=gadget")
    assert body["rows"] == []
    _, body = query("name__exact=Gadget")
    assert names(body) == ["Gadget"]


# Phrase: "`exact`: case-sensitive string equality."
# Context: numeric cells compare as their stringified value (AMBIGUITIES T30).
def test_exact_matches_numeric_cell_by_string(table):
    query = table()
    _, body = query("qty__exact=10")
    assert names(body) == ["Gadget"]


# Phrase: "`exact`: case-sensitive string equality."
# Context: string equality, so a numerically-equal but differently-written value
# does not match (AMBIGUITIES T30).
def test_exact_does_not_compare_numerically(table):
    query = table()
    _, body = query("qty__exact=10.0")
    assert body["rows"] == []


# Phrase: "`contains`: case-sensitive substring."
# Context: matches every row whose cell contains the value anywhere.
def test_contains_matches_substring(table):
    query = table()
    _, body = query("name__contains=widget")
    assert names(body) == ["widget", "widgetron"]


# Phrase: "`contains`: case-sensitive substring."
# Context: case-sensitive - lowercase value misses the capitalised cell.
def test_contains_is_case_sensitive(table):
    query = table()
    _, body = query("name__contains=adget")
    assert names(body) == ["Gadget"]
    _, body = query("name__contains=Adget")
    assert body["rows"] == []


# Phrase: "`contains`: case-sensitive substring."
# Context: a whole-cell value is a substring of itself.
def test_contains_matches_whole_value(table):
    query = table()
    _, body = query("name__contains=gizmo")
    assert names(body) == ["gizmo"]


# Phrase: "`contains`: case-sensitive substring."
# Context: an empty value is a substring of everything.
def test_contains_empty_value_matches_all(table):
    query = table()
    _, body = query("name__contains=")
    assert len(body["rows"]) == 4


# Phrase: "`less`: numeric strict less (`float` parse on stored and filter values)."
# Context: strictly less - the boundary value itself is excluded.
def test_less_is_strict(table):
    query = table()
    _, body = query("qty__less=3")
    assert body["rows"] == []
    _, body = query("qty__less=4")
    assert names(body) == ["widget"]


# Phrase: "`less`: numeric strict less (`float` parse on stored and filter values)."
# Context: both sides are float-parsed, so int cells and decimal filters mix.
def test_less_parses_both_sides_as_float(table):
    query = table()
    _, body = query("qty__less=7.5")
    assert names(body) == ["widget", "widgetron"]


# Phrase: "`less`: numeric strict less"
# Context: comparison is numeric, not lexicographic ("10" < "7" as text).
def test_less_is_numeric_not_lexicographic(table):
    query = table()
    _, body = query("qty__less=9")
    assert names(body) == ["widget", "widgetron"]


# Phrase: "`greater`: numeric strict greater."
# Context: strictly greater - the boundary value itself is excluded.
def test_greater_is_strict(table):
    query = table()
    _, body = query("qty__greater=10")
    assert body["rows"] == []
    _, body = query("qty__greater=7")
    assert names(body) == ["Gadget"]


# Phrase: "`greater`: numeric strict greater."
# Context: decimal column, decimal filter value.
def test_greater_on_decimal_column(table):
    query = table()
    _, body = query("price__greater=2.25")
    assert names(body) == ["widget", "gizmo"]


# Phrase: "`greater`: numeric strict greater."
# Context: negative numbers parse and order correctly on both sides.
def test_greater_handles_negative_values(table):
    query = table("name,v\na,-5\nb,0\nc,4\n")
    _, body = query("v__greater=-1")
    assert names(body) == ["b", "c"]


# Phrase: "`less`: numeric strict less"
# Context: negative filter value against negative stored values.
def test_less_handles_negative_values(table):
    query = table("name,v\na,-5\nb,0\nc,4\n")
    _, body = query("v__less=-1")
    assert names(body) == ["a"]


# =================================================== numeric value parsing ====

# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# Context: `less` with a word for a value.
def test_less_with_non_numeric_value_is_400(table):
    query = table()
    assert_error(*query("qty__less=abc"))


# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# Context: `greater` with a word for a value.
def test_greater_with_non_numeric_value_is_400(table):
    query = table()
    assert_error(*query("qty__greater=abc"))


# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# Context: an empty value is not a number either.
def test_numeric_comparator_with_empty_value_is_400(table):
    query = table()
    assert_error(*query("qty__less="))


# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# Context: a partially-numeric value is still non-numeric.
@pytest.mark.parametrize("value", ["3abc", "1,000", "$5", "5%", "", " ", "--3", "1.2.3"])
def test_assorted_non_numeric_values_are_400(table, value):
    query = table()
    assert_error(*query({"qty__less": value}))


# Phrase: "(`float` parse on stored and filter values)"
# Context: exponent and sign forms `float` accepts are valid filter values.
@pytest.mark.parametrize("value", ["1e3", "+5", "-5", "5.", ".5", " 5 "])
def test_float_parsable_values_are_accepted(table, value):
    query = table()
    status, _ = query({"qty__less": value})
    assert status == 200


# Phrase: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# Context: the non-numeric-value check does not apply to `exact`/`contains`.
def test_string_comparators_accept_non_numeric_values(table):
    query = table()
    status, body = query("qty__exact=n/a")
    assert status == 200
    assert names(body) == ["gizmo"]


# Phrase: "Rows with non-numeric stored values are not matched for numeric comparators."
# Context: `less` skips the row whose stored cell is text.
def test_non_numeric_stored_value_not_matched_by_less(table):
    query = table()
    _, body = query("qty__less=1000")
    assert names(body) == ["widget", "Gadget", "widgetron"]
    assert "gizmo" not in names(body)


# Phrase: "Rows with non-numeric stored values are not matched for numeric comparators."
# Context: `greater` skips it too - it is excluded, not treated as 0 or as huge.
def test_non_numeric_stored_value_not_matched_by_greater(table):
    query = table()
    _, body = query("qty__greater=-1000")
    assert names(body) == ["widget", "Gadget", "widgetron"]


# Phrase: "Rows with non-numeric stored values are not matched for numeric comparators."
# Context: an empty stored cell is non-numeric, so it is never matched.
def test_empty_stored_cell_not_matched_by_numeric_comparator(table):
    query = table("name,v\na,1\nb,\nc,3\n")
    _, body = query("v__less=100")
    assert names(body) == ["a", "c"]


# Phrase: "Rows with non-numeric stored values are not matched for numeric comparators."
# Context: a non-numeric stored value is never an error - only the filter value is.
def test_non_numeric_stored_value_is_not_an_error(table):
    query = table()
    status, _ = query("qty__less=5")
    assert status == 200


# ========================================================= AND / duplicates ====

# Phrase: "Multiple filters are ANDed."
# Context: two filters on different columns; only rows matching both survive.
def test_multiple_filters_are_anded(table):
    query = table()
    _, body = query("name__contains=widget&qty__greater=5")
    assert names(body) == ["widgetron"]


# Phrase: "Multiple filters are ANDed."
# Context: two different comparators on the *same* column form a range
# (AMBIGUITIES T36: that is not a duplicate key).
def test_range_on_one_column_is_anded(table):
    query = table()
    status, body = query("qty__greater=3&qty__less=10")
    assert status == 200
    assert names(body) == ["widgetron"]


# Phrase: "Multiple filters are ANDed."
# Context: contradictory filters yield no rows rather than an error.
def test_contradictory_filters_yield_no_rows(table):
    query = table()
    status, body = query("qty__greater=100&qty__less=1")
    assert status == 200
    assert body["rows"] == []


# Phrase: "Multiple filters are ANDed."
# Context: three filters at once, mixing string and numeric comparators.
def test_three_filters_anded(table):
    query = table()
    _, body = query("name__contains=widget&qty__greater=1&price__less=5")
    assert names(body) == ["widgetron"]


# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
# Context: the same column+comparator supplied twice.
def test_duplicate_filter_key_is_400(table):
    query = table()
    assert_error(*query("qty__less=5&qty__less=9"))


# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
# Context: duplicated with an identical value is still a duplicate key.
def test_duplicate_filter_key_with_same_value_is_400(table):
    query = table()
    assert_error(*query("name__exact=widget&name__exact=widget"))


# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
# Context: a string comparator duplicated.
def test_duplicate_contains_key_is_400(table):
    query = table()
    assert_error(*query("name__contains=w&name__contains=g"))


# Phrase: "Duplicate filter keys are invalid (`HTTP 400`)."
# Context: the duplicate is rejected even though each copy is individually valid.
def test_duplicate_is_rejected_not_last_wins(table):
    query = table()
    status, _ = query("name__exact=widget&name__exact=gizmo")
    assert status == 400


# ======================================================== column matching ====

# Phrase: "Column matching is exact and case-sensitive."
# Context: a differently-cased column name is unknown, not a match.
def test_column_match_is_case_sensitive(table):
    query = table()
    assert_error(*query("Name__exact=widget"))


# Phrase: "Column matching is exact and case-sensitive."
# Context: a prefix of a real column name is not a match.
def test_column_match_is_exact_not_prefix(table):
    query = table()
    assert_error(*query("nam__exact=widget"))


# Phrase: "Column matching is exact and case-sensitive."
# Context: surrounding whitespace is not stripped from the column part.
def test_column_match_does_not_strip_whitespace(table):
    query = table()
    assert_error(*query({" name__exact": "widget"}))


# Phrase: "Unknown filter column | 400"
# Context: a column name that appears in no header at all.
def test_unknown_column_is_400(table):
    query = table()
    assert_error(*query("nosuch__exact=1"))


# Phrase: "Unknown filter column | 400"
# Context: unknown columns are rejected for numeric comparators too.
def test_unknown_column_with_numeric_comparator_is_400(table):
    query = table()
    assert_error(*query("nosuch__less=1"))


# Phrase: "Column matching is exact and case-sensitive."
# Context: a header that itself contains `__` is filterable; the key splits on
# the *last* `__` (AMBIGUITIES T29).
def test_column_containing_double_underscore_is_filterable(table):
    query = table("user__id,name\n7,alpha\n8,beta\n")
    status, body = query("user__id__exact=7")
    assert status == 200
    assert names(body) == ["alpha"]


# ======================================================= invalid comparator ====

# Phrase: "Invalid comparator (`exact|contains|less|greater`) | 400"
# Context: a comparator outside the closed vocabulary.
def test_unknown_comparator_is_400(table):
    query = table()
    assert_error(*query("name__like=widget"))


# Phrase: "Invalid comparator (`exact|contains|less|greater`) | 400"
# Context: comparator names are case-sensitive too.
@pytest.mark.parametrize("comparator", ["EXACT", "Exact", "Contains", "LESS", "Greater"])
def test_comparator_is_case_sensitive(table, comparator):
    query = table()
    assert_error(*query({"name__%s" % comparator: "widget"}))


# Phrase: "Invalid comparator (`exact|contains|less|greater`) | 400"
# Context: near-misses of the four names.
@pytest.mark.parametrize("comparator", ["eq", "gt", "lt", "lte", "gte", "startswith",
                                        "exact_", "exactly", "containss"])
def test_near_miss_comparators_are_400(table, comparator):
    query = table()
    assert_error(*query({"name__%s" % comparator: "widget"}))


# Phrase: "Invalid comparator (`exact|contains|less|greater`) | 400"
# Context: an empty comparator part (AMBIGUITIES T34).
def test_empty_comparator_is_400(table):
    query = table()
    assert_error(*query("name__=widget"))


# Phrase: "Control params (names beginning with `_`) are not filters."
# Context: a key with an empty column part necessarily begins with `_`, so the
# control-prefix gate claims it first and it is ignored (AMBIGUITIES T32/T34).
def test_empty_column_key_is_ignored(table):
    query = table()
    status, body = query("__exact=widget")
    assert status == 200
    assert len(body["rows"]) == 4


# Phrase: "Invalid comparator ... | Unknown filter column"
# Context: both defects at once - still a single 400 envelope (AMBIGUITIES T31).
def test_unknown_column_and_bad_comparator_is_400(table):
    query = table()
    assert_error(*query("nosuch__nope=1"))


# ============================================ ordering / pagination / total ====

# Phrase: "Filtering precedes sorting."
# Context: the surviving rows are sorted among themselves.
def test_filtering_precedes_sorting(table):
    query = table()
    _, body = query("qty__greater=0&_sort=qty")
    assert names(body) == ["widget", "widgetron", "Gadget"]


# Phrase: "Filtering precedes sorting."
# Context: descending sort over the filtered set.
def test_filtering_precedes_descending_sort(table):
    query = table()
    _, body = query("price__less=8&_sort_desc=price")
    assert names(body) == ["gizmo", "Gadget", "widgetron"]


# Phrase: "Pagination runs on filtered+sorted results."
# Context: `_size` caps the *filtered* set, not the raw table - the page is the
# first N of the filtered+sorted rows, not the filtered subset of the first N.
def test_pagination_applies_after_filtering_and_sorting(table):
    query = table()
    _, body = query("qty__greater=0&_sort=qty&_size=2")
    assert names(body) == ["widget", "widgetron"]


# Phrase: "Pagination runs on filtered+sorted results."
# Context: `_offset` counts within the filtered+sorted set.
def test_offset_counts_within_filtered_results(table):
    query = table()
    _, body = query("qty__greater=0&_sort=qty&_offset=1")
    assert names(body) == ["widgetron", "Gadget"]


# Phrase: "Pagination runs on filtered+sorted results."
# Context: an offset past the filtered count yields an empty page, not an error.
def test_offset_past_filtered_count_is_empty(table):
    query = table()
    status, body = query("qty__greater=0&_offset=50")
    assert status == 200
    assert body["rows"] == []


# Phrase: "Pagination runs on filtered+sorted results."
# Context: a filtered page still respects the 100-row default cap.
def test_default_page_size_applies_to_filtered_results(table):
    body_csv = "name,v\n" + "".join("r%d,%d\n" % (i, i) for i in range(250))
    query = table(body_csv)
    _, body = query("v__greater=-1")
    assert len(body["rows"]) == 100
    assert names(body)[0] == "r0"


# Phrase: "`total` counts filtered rows before pagination."
# Context: total is the filtered count, not the table size.
def test_total_counts_filtered_rows(table):
    query = table()
    _, body = query("qty__greater=0")
    assert body["total"] == 3


# Phrase: "`total` counts filtered rows before pagination."
# Context: total ignores `_size`/`_offset`.
def test_total_ignores_pagination(table):
    query = table()
    _, body = query("qty__greater=0&_size=1&_offset=1")
    assert body["total"] == 3
    assert len(body["rows"]) == 1


# Phrase: "`total` counts filtered rows before pagination."
# Context: zero matches gives total 0.
def test_total_zero_when_nothing_matches(table):
    query = table()
    _, body = query("name__exact=absent")
    assert body["total"] == 0


# Phrase: "`total` counts filtered rows before pagination."
# Context: `_total=hide` still suppresses the key when filtering.
def test_total_can_still_be_hidden(table):
    query = table()
    _, body = query("qty__greater=0&_total=hide")
    assert "total" not in body


# Phrase: "Filtering precedes sorting." / rowid carries the source row number.
# Context: `rowid` stays the source-file row number after filtering.
def test_rowid_survives_filtering(table):
    query = table()
    _, body = query("name__exact=widgetron&_shape=objects")
    assert body["rows"][0]["rowid"] == 5


# ================================================== non-filter parameters ====

# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: a bare column name is not a filter and does not narrow the result.
def test_param_without_double_underscore_is_ignored(table):
    query = table()
    status, body = query("name=widget")
    assert status == 200
    assert len(body["rows"]) == 4


# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: an unknown bare param is ignored rather than a 400.
def test_unknown_bare_param_is_ignored(table):
    query = table()
    status, body = query("nosuchthing=1")
    assert status == 200
    assert len(body["rows"]) == 4


# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: a bare param that collides with a comparator name is still ignored.
def test_bare_comparator_named_param_is_ignored(table):
    query = table()
    status, body = query("exact=widget&contains=x&less=1&greater=2")
    assert status == 200
    assert len(body["rows"]) == 4


# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: ignored means *ignored*, so repeating one is not a duplicate-key 400.
def test_repeated_ignored_param_is_not_a_duplicate(table):
    query = table()
    status, body = query("junk=1&junk=2")
    assert status == 200
    assert len(body["rows"]) == 4


# Phrase: "Params without `_` and without `__` are ignored as filters."
# Context: ignored params coexist with real filters.
def test_ignored_param_alongside_real_filter(table):
    query = table()
    _, body = query("junk=1&name__exact=gizmo")
    assert names(body) == ["gizmo"]


# ================================================================ timeout ====

# Phrase: "Query timeout returns `HTTP 400`."
# Context: the query budget (AMBIGUITIES T35: `DATAGATE_QUERY_TIMEOUT` seconds)
# is exceeded while evaluating the request.
def test_query_timeout_is_400(app, client, convert, origin):
    url = origin.add(CSV)
    status, payload = convert(source=url)
    assert status == 200
    app.config["DATAGATE_QUERY_TIMEOUT"] = 0.0
    resp = client.get(payload["endpoint"], query_string="name__contains=widget")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# Phrase: "Query timeout returns `HTTP 400`."
# Context: the default budget is generous enough that ordinary queries pass.
def test_default_timeout_does_not_fire(table):
    body_csv = "name,v\n" + "".join("r%d,%d\n" % (i, i) for i in range(2000))
    query = table(body_csv)
    status, _ = query("v__greater=10&_sort=v")
    assert status == 200


# ========================================================= error envelope ====

# Phrase: '| <condition> | 400 | {"ok": false, "error": "<message>"}'
# Context: every filter error uses the same envelope and status, with exactly
# the two documented keys.
@pytest.mark.parametrize(
    "query_string",
    [
        "name__like=widget",       # invalid comparator
        "qty__less=abc",           # comparator target not numeric
        "nosuch__exact=1",         # unknown filter column
        "qty__less=1&qty__less=2",  # duplicate filter key
    ],
)
def test_filter_errors_share_the_envelope(table, query_string):
    query = table()
    status, body = query(query_string)
    assert status == 400
    assert body == {"ok": False, "error": body.get("error")}
    assert isinstance(body["error"], str) and body["error"]


# Phrase: '{"ok": false, "error": "<message>"}'
# Context: a filter error response carries no rows/columns/total.
def test_filter_error_has_no_data_keys(table):
    query = table()
    _, body = query("nosuch__exact=1")
    assert "rows" not in body and "columns" not in body and "total" not in body


# Phrase: "Unknown dataset id" (prior section) vs filter errors
# Context: an unknown dataset still 404s even when the filter is also invalid
# (AMBIGUITIES T28/T37 precedence chain).
def test_unknown_dataset_beats_filter_error(client):
    resp = client.get("/datasets/deadbeef", query_string="nosuch__exact=1")
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False
