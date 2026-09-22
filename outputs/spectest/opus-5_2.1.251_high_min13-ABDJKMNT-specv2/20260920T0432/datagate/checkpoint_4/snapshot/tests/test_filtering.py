"""Column-level filtering: `<column>__<comparator>=<value>` on a dataset read."""

from gateway import budget

PEOPLE = "name,age,city\nada,36,London\ngrace,45,Baltimore\nalan,41,london\nlin,29,Taipei\n"
# `abc` and the empty cell stay text, so they are the non-numeric stored values.
SCORES = "label,score\na,10\nb,abc\nc,2.5\nd,\n"

ADA = ["ada", 36, "London"]
GRACE = ["grace", 45, "Baltimore"]
ALAN = ["alan", 41, "london"]
LIN = ["lin", 29, "Taipei"]


def rows_of(response):
    return response.get_json()["rows"]


def assert_rejected(response):
    """A filtering failure: 400 carrying the error envelope."""
    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]


# Spec: "`GET /datasets/<id>` accepts filter params in this form:
# `<column>__<comparator>=<value>`"
# Context: a filter keeps only the rows it matches.
def test_filter_param_selects_matching_rows(reader):
    assert rows_of(reader(PEOPLE)({"name__exact": "ada"})) == [ADA]


# Spec: "Control params (names beginning with `_`) are not filters."
# Context: a control keeps working alongside filtering and is never read as a
# column condition.
def test_control_params_are_not_filters(reader):
    assert rows_of(reader(PEOPLE)({"_size": "2"})) == [ADA, GRACE]


# Spec: "Control params (names beginning with `_`) are not filters."
# Context: a name that begins with `_` is a control even when it carries `__`,
# so it is not an unknown-column filter (AMBIGUITIES T18).
def test_underscore_prefixed_filter_shape_is_not_a_filter(reader):
    assert rows_of(reader(PEOPLE)({"_age__less": "40"})) == [ADA, GRACE, ALAN, LIN]


# Spec: "`exact`: case-sensitive string equality."
# Context: a value differing only in case does not match.
def test_exact_is_case_sensitive(reader):
    read = reader(PEOPLE)
    assert rows_of(read({"city__exact": "london"})) == [ALAN]
    assert rows_of(read({"city__exact": "LONDON"})) == []


# Spec: "`exact`: case-sensitive string equality."
# Context: equality is whole-value, not prefix or substring.
def test_exact_matches_the_whole_value(reader):
    assert rows_of(reader(PEOPLE)({"name__exact": "ad"})) == []


# Spec: "`exact`: case-sensitive string equality."
# Context: a stored number compares as the text it renders to
# (AMBIGUITIES T17).
def test_exact_matches_a_numeric_cell_by_its_rendering(reader):
    assert rows_of(reader(PEOPLE)({"age__exact": "36"})) == [ADA]


# Spec: "`exact`: case-sensitive string equality."
# Context: an empty filter value matches the rows whose cell is empty.
def test_exact_matches_empty_cells(reader):
    assert rows_of(reader(SCORES)({"score__exact": ""})) == [["d", ""]]


# Spec: "`contains`: case-sensitive substring."
# Context: a substring anywhere in the value matches, and case must agree.
def test_contains_is_a_case_sensitive_substring(reader):
    read = reader(PEOPLE)
    assert rows_of(read({"city__contains": "Lon"})) == [ADA]
    assert rows_of(read({"city__contains": "on"})) == [ADA, ALAN]


# Spec: "`contains`: case-sensitive substring."
# Context: a stored number is searched as its rendering (AMBIGUITIES T17).
def test_contains_searches_numeric_cells_as_text(reader):
    assert rows_of(reader(PEOPLE)({"age__contains": "4"})) == [GRACE, ALAN]


# Spec: "`less`: numeric strict less"
# Context: rows below the bound are kept and the bound itself is not.
def test_less_is_strict(reader):
    read = reader(PEOPLE)
    assert rows_of(read({"age__less": "41"})) == [ADA, LIN]
    assert rows_of(read({"age__less": "29"})) == []


# Spec: "`greater`: numeric strict greater."
# Context: rows above the bound are kept and the bound itself is not.
def test_greater_is_strict(reader):
    read = reader(PEOPLE)
    assert rows_of(read({"age__greater": "41"})) == [GRACE]
    assert rows_of(read({"age__greater": "45"})) == []


# Spec: "numeric strict less (`float` parse on stored and filter values)"
# Context: both sides parse as floats, so a fractional bound and an exponent
# spelling compare by value rather than by text.
def test_numeric_comparators_compare_by_float_value(reader):
    read = reader(SCORES)
    assert rows_of(read({"score__less": "2.6"})) == [["c", 2.5]]
    assert rows_of(read({"score__greater": "2.50"})) == [["a", 10]]
    assert rows_of(read({"score__less": "1e1"})) == [["c", 2.5]]


# Spec: "For `less`/`greater`, non-numeric filter values return `HTTP 400`."
# Context: text, an empty value and a number Python's `float` rejects.
def test_non_numeric_filter_value_is_400(reader):
    read = reader(PEOPLE)
    for comparator in ("less", "greater"):
        for value in ("abc", "", "4,5", "36px", "0x10"):
            assert_rejected(read({f"age__{comparator}": value}))


# Spec: "Rows with non-numeric stored values are not matched for numeric
# comparators."
# Context: `abc` and the empty cell fall out of both numeric comparators, even
# against bounds that every number satisfies.
def test_non_numeric_stored_values_never_match(reader):
    read = reader(SCORES)
    assert rows_of(read({"score__greater": "-1000000"})) == [["a", 10], ["c", 2.5]]
    assert rows_of(read({"score__less": "1000000"})) == [["a", 10], ["c", 2.5]]


# Spec: "Multiple filters are ANDed."
# Context: two filters on different columns keep only the rows matching both.
def test_multiple_filters_are_anded(reader):
    read = reader(PEOPLE)
    assert rows_of(read({"city__contains": "on", "age__less": "40"})) == [ADA]
    assert rows_of(read({"city__contains": "on", "age__greater": "50"})) == []


# Spec: "Multiple filters are ANDed."
# Context: two different comparators on one column bound it from both sides,
# and are not a duplicate key (AMBIGUITIES T21).
def test_two_comparators_on_one_column_are_anded(reader):
    query = {"age__greater": "30", "age__less": "45"}
    assert rows_of(reader(PEOPLE)(query)) == [ADA, ALAN]


# Spec: "Duplicate filter keys are invalid (`HTTP 400`)."
# Context: the same `<column>__<comparator>` twice, with differing and with
# identical values.
def test_duplicate_filter_key_is_400(reader):
    read = reader(PEOPLE)
    assert_rejected(read("age__less=40&age__less=50"))
    assert_rejected(read("age__less=40&age__less=40"))
    assert_rejected(read("name__exact=ada&name__exact=lin"))


# Spec: "Column matching is exact and case-sensitive."
# Context: a column spelled in the wrong case, and a prefix of a real column,
# are unknown columns.
def test_column_matching_is_exact_and_case_sensitive(reader):
    read = reader(PEOPLE)
    assert_rejected(read({"Name__exact": "ada"}))
    assert_rejected(read({"nam__exact": "ada"}))
    assert_rejected(read({"age__less": "40", "AGE__greater": "10"}))


# Spec: "| Unknown filter column | 400 |"
# Context: a well-formed filter naming a column the dataset does not have.
def test_unknown_filter_column_is_400(reader):
    assert_rejected(reader(PEOPLE)({"height__greater": "1"}))


# Spec: "| Invalid comparator (`exact|contains|less|greater`) | 400 |"
# Context: an unsupported comparator word, and a supported one miscased
# (AMBIGUITIES T25).
def test_invalid_comparator_is_400(reader):
    read = reader(PEOPLE)
    for comparator in ("lt", "equals", "LESS", "Exact", "", "iexact"):
        assert_rejected(read({f"age__{comparator}": "40"}))


# Spec: "`rowid` is not in `columns`." / "| Unknown filter column | 400 |"
# Context: `rowid` is not a filterable column unless the source has one
# (AMBIGUITIES T23).
def test_rowid_is_not_a_filterable_column(reader):
    assert_rejected(reader(PEOPLE)({"rowid__greater": "2"}))


# Spec: "Filtering precedes sorting."
# Context: the surviving rows are sorted among themselves, so the sort order is
# unaffected by rows the filter removed.
def test_filtering_precedes_sorting(reader):
    query = {"age__less": "45", "_sort_desc": "age"}
    assert rows_of(reader(PEOPLE)(query)) == [ALAN, ADA, LIN]


# Spec: "Pagination runs on filtered+sorted results."
# Context: the window is cut from the filtered rows in sorted order, not from
# the whole dataset.
def test_pagination_runs_on_filtered_and_sorted_rows(reader):
    query = {"age__less": "45", "_sort": "age", "_size": "1", "_offset": "1"}
    assert rows_of(reader(PEOPLE)(query)) == [ADA]


# Spec: "Pagination runs on filtered+sorted results."
# Context: an offset past the filtered row count returns nothing, even though
# the dataset still holds rows there.
def test_offset_past_the_filtered_rows_returns_nothing(reader):
    assert rows_of(reader(PEOPLE)({"age__less": "40", "_offset": "2"})) == []


# Spec: "`total` counts filtered rows before pagination."
# Context: a filter narrows `total`, and a window inside it does not.
def test_total_counts_filtered_rows(reader):
    payload = reader(PEOPLE)({"age__less": "45", "_size": "1"}).get_json()
    assert payload["total"] == 3
    assert len(payload["rows"]) == 1


# Spec: "`total` counts filtered rows before pagination."
# Context: a filter matching nothing.
def test_total_is_zero_when_nothing_matches(reader):
    payload = reader(PEOPLE)({"name__exact": "nobody"}).get_json()
    assert payload["total"] == 0
    assert payload["rows"] == []


# Spec: "`total` counts filtered rows before pagination."
# Context: filtering does not renumber rows — `rowid` stays the source row
# (AMBIGUITIES T24).
def test_filtering_keeps_source_rowids(reader):
    query = {"age__greater": "40", "_shape": "objects"}
    payload = reader(PEOPLE)(query).get_json()
    assert [row["rowid"] for row in payload["rows"]] == [3, 4]


# Spec: "Query timeout returns `HTTP 400`."
# Context: a read whose time budget is already spent (AMBIGUITIES T22).
def test_query_timeout_is_400(reader, monkeypatch):
    read = reader(PEOPLE)
    monkeypatch.setattr(budget, "QUERY_BUDGET_SECONDS", 0.0)
    assert_rejected(read({"age__less": "100"}))


# Spec: "Params without `_` and without `__` are ignored as filters."
# Context: a bare column name and an unrelated word neither filter nor fail.
def test_params_without_a_comparator_are_ignored(reader):
    read = reader(PEOPLE)
    assert rows_of(read({"age": "36"})) == [ADA, GRACE, ALAN, LIN]
    assert rows_of(read({"limit": "1", "city": "nowhere"})) == [ADA, GRACE, ALAN, LIN]


# Spec: "Params without `_` and without `__` are ignored as filters."
# Context: a single interior `_` is not a comparator separator, so the param is
# ignored rather than rejected (AMBIGUITIES T18).
def test_single_underscore_param_is_ignored(reader):
    assert rows_of(reader(PEOPLE)({"age_less": "40"})) == [ADA, GRACE, ALAN, LIN]


# Spec: "`<column>__<comparator>=<value>`"
# Context: a column name that itself contains `__` splits on the last separator
# (AMBIGUITIES T19).
def test_column_name_may_contain_the_separator(reader):
    read = reader("first__name,age\nada,36\nlin,29\n")
    assert rows_of(read({"first__name__exact": "ada"})) == [["ada", 36]]


# Spec: "Params without `_` and without `__` are ignored as filters."
# Context: a param that does carry `__` is read as a filter, so a column name
# with no comparator after it fails on the comparator (AMBIGUITIES T19).
def test_separator_without_a_comparator_is_rejected(reader):
    read = reader("first__name,age\nada,36\nlin,29\n")
    assert_rejected(read({"first__name": "ada"}))


# Spec: "| Condition | Status | Response |" with `{"ok": false, "error": "<message>"}`
# Context: every filtering failure answers with the same envelope and no data.
def test_filter_errors_carry_the_error_envelope(reader):
    read = reader(PEOPLE)
    for query in ({"age__nope": "1"}, {"age__less": "x"}, {"nope__exact": "1"}):
        body = read(query).get_json()
        assert set(body) == {"ok", "error"}
