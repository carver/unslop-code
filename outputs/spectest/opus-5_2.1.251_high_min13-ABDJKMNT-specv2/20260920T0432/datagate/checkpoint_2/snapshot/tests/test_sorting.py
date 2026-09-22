"""Sorting controls: `_sort`, `_sort_desc` and their interaction with paging."""

PEOPLE = "name,age\ngrace,45\nada,36\nalan,41\n"
TEAMS = "name,team\nada,blue\ngrace,red\nalan,blue\nlin,red\n"


# Spec: "`_sort=<column>` sorts ascending by `<column>`."
# Context: a text column.
def test_sort_ascending_by_text_column(reader):
    payload = reader(PEOPLE)({"_sort": "name"}).get_json()
    assert payload["rows"] == [["ada", 36], ["alan", 41], ["grace", 45]]


# Spec: "`_sort=<column>` sorts ascending by `<column>`."
# Context: a numeric column orders by value, not by its text spelling.
def test_sort_ascending_is_numeric_for_numbers(reader):
    payload = reader("n\tlabel\n2\ta\n10\tb\n9\tc\n")({"_sort": "n"}).get_json()
    assert payload["rows"] == [[2, "a"], [9, "c"], [10, "b"]]


# Spec: "`_sort_desc=<column>` sorts descending by `<column>`."
# Context: the reverse of the ascending order on the same column.
def test_sort_desc_reverses_the_order(reader):
    payload = reader(PEOPLE)({"_sort_desc": "age"}).get_json()
    assert payload["rows"] == [["grace", 45], ["alan", 41], ["ada", 36]]


# Spec: "If both are present, `_sort_desc` wins."
# Context: two valid columns named at once.
def test_sort_desc_wins_over_sort(reader):
    payload = reader(PEOPLE)({"_sort": "name", "_sort_desc": "age"}).get_json()
    assert payload["rows"] == [["grace", 45], ["alan", 41], ["ada", 36]]


# Spec: "If both are present, `_sort_desc` wins."
# Context: the losing `_sort` is ignored outright, including its value
# (AMBIGUITIES T12).
def test_losing_sort_value_is_ignored(reader):
    payload = reader(PEOPLE)({"_sort": "nope", "_sort_desc": "name"}).get_json()
    assert payload["rows"] == [["grace", 45], ["alan", 41], ["ada", 36]]


# Spec: "Sorting is stable"
# Context: rows tied on the sort column keep their source order, ascending...
def test_ascending_sort_is_stable(reader):
    payload = reader(TEAMS)({"_sort": "team"}).get_json()
    assert payload["rows"] == [
        ["ada", "blue"],
        ["alan", "blue"],
        ["grace", "red"],
        ["lin", "red"],
    ]


# Spec: "Sorting is stable"
# Context: ...and descending, where ties must not be reversed either.
def test_descending_sort_is_stable(reader):
    payload = reader(TEAMS)({"_sort_desc": "team"}).get_json()
    assert payload["rows"] == [
        ["grace", "red"],
        ["lin", "red"],
        ["ada", "blue"],
        ["alan", "blue"],
    ]


# Spec: "Sorting is ... applied before pagination."
# Context: the window is cut out of the sorted dataset, not sorted after cutting.
def test_sorting_precedes_pagination(reader):
    body = "n,label\n" + "".join(f"{i},row{i}\n" for i in range(20))
    payload = reader(body)({"_sort_desc": "n", "_offset": "1", "_size": "2"}).get_json()
    assert payload["rows"] == [[18, "row18"], [17, "row17"]]
    assert payload["total"] == 20


# Spec: "`_sort=<column>` sorts ascending by `<column>`."
# Context: a column mixing numbers and text still orders totally, with numbers
# ahead of text (AMBIGUITIES T13).
def test_mixed_type_column_sorts_numbers_before_text(reader):
    payload = reader("v,i\n10,a\napple,b\n3,c\n,d\n")({"_sort": "v"}).get_json()
    assert payload["rows"] == [[3, "c"], [10, "a"], ["", "d"], ["apple", "b"]]


# Spec: "Empty values or unknown columns return `HTTP 400`."
# Context: both sort parameters, each with an unknown column and an empty value.
def test_bad_sort_column_is_400(reader):
    read = reader(PEOPLE)
    for name in ("_sort", "_sort_desc"):
        for value in ("nope", "", "Name"):
            response = read({name: value})
            assert response.status_code == 400, (name, value)
            body = response.get_json()
            assert body["ok"] is False
            assert isinstance(body["error"], str) and body["error"]


# Spec: "`rowid` is not in `columns`." / "unknown columns return HTTP 400"
# Context: `rowid` is not a sortable column unless the source has one
# (AMBIGUITIES T16).
def test_rowid_is_not_a_sortable_column(reader):
    assert reader(PEOPLE)({"_sort": "rowid"}).status_code == 400
