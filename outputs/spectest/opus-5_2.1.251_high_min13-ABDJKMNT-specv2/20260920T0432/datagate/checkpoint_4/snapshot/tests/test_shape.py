"""Response shape (`_shape`), `rowid`, and the visibility toggles."""

PEOPLE = "name,age\ngrace,45\nada,36\nalan,41\n"


# Spec: "`_shape=lists` (default): `rows` is arrays."
# Context: no `_shape` parameter, and the explicit default value.
def test_lists_is_the_default_shape(reader):
    read = reader(PEOPLE)
    for query in ({}, {"_shape": "lists"}):
        rows = read(query).get_json()["rows"]
        assert rows == [["grace", 45], ["ada", 36], ["alan", 41]], query


# Spec: "`_shape=objects`: `rows` is objects"
# Context: each row is keyed by its column names.
def test_objects_shape_keys_rows_by_column(reader):
    rows = reader(PEOPLE)({"_shape": "objects"}).get_json()["rows"]
    assert [{k: v for k, v in row.items() if k != "rowid"} for row in rows] == [
        {"name": "grace", "age": 45},
        {"name": "ada", "age": 36},
        {"name": "alan", "age": 41},
    ]


# Spec: "includes `rowid` (1-based source-file row number, starting at the
# header)"
# Context: the header is row 1, so the first data row is row 2 (AMBIGUITIES T11).
def test_rowid_counts_from_the_header(reader):
    rows = reader(PEOPLE)({"_shape": "objects"}).get_json()["rows"]
    assert [row["rowid"] for row in rows] == [2, 3, 4]


# Spec: "`rowid` (1-based source-file row number...)"
# Context: `rowid` names the source row, so sorting and paging carry it along.
def test_rowid_follows_the_source_row_through_sorting(reader):
    rows = reader(PEOPLE)({"_shape": "objects", "_sort": "name"}).get_json()["rows"]
    assert [(row["name"], row["rowid"]) for row in rows] == [
        ("ada", 3),
        ("alan", 4),
        ("grace", 2),
    ]


# Spec: "`rowid` is not in `columns`."
# Context: the columns list still describes the source header only.
def test_rowid_is_absent_from_columns(reader):
    payload = reader(PEOPLE)({"_shape": "objects"}).get_json()
    assert payload["columns"] == ["name", "age"]


# Spec: "`_shape=lists` (default): `rows` is arrays."
# Context: `rowid` belongs to the objects shape; arrays hold cell values only.
def test_lists_shape_carries_no_rowid(reader):
    rows = reader(PEOPLE)({"_shape": "lists"}).get_json()["rows"]
    assert rows == [["grace", 45], ["ada", 36], ["alan", 41]]


# Spec: "| `_shape` not `lists`/`objects` | 400 |"
# Context: any other value, including an empty one.
def test_unknown_shape_is_400(reader):
    read = reader(PEOPLE)
    for value in ("array", "", "Objects", "object"):
        response = read({"_shape": value})
        assert response.status_code == 400, value
        assert response.get_json()["ok"] is False


# Spec: "`_rowid=hide` removes `rowid`."
# Context: the objects shape, where `rowid` would otherwise appear.
def test_rowid_hide_removes_rowid(reader):
    rows = reader(PEOPLE)({"_shape": "objects", "_rowid": "hide"}).get_json()["rows"]
    assert rows == [
        {"name": "grace", "age": 45},
        {"name": "ada", "age": 36},
        {"name": "alan", "age": 41},
    ]


# Spec: "`_rowid=hide` removes `rowid`."
# Context: under the lists shape there is no `rowid` to remove, and asking for
# its removal is still accepted (AMBIGUITIES T15).
def test_rowid_hide_is_accepted_under_lists(reader):
    response = reader(PEOPLE)({"_rowid": "hide"})
    assert response.status_code == 200
    assert response.get_json()["rows"] == [["grace", 45], ["ada", 36], ["alan", 41]]


# Spec: "`_total=hide` removes `total`."
# Context: the key is gone entirely, not null or zero.
def test_total_hide_removes_total(reader):
    payload = reader(PEOPLE)({"_total": "hide"}).get_json()
    assert "total" not in payload
    assert set(payload) == {"ok", "columns", "rows", "query_ms"}


# Spec: "Each toggle is valid only with value `hide`; any other value is
# `HTTP 400`."
# Context: every non-`hide` value of either toggle, including an empty one.
def test_non_hide_toggle_values_are_400(reader):
    read = reader(PEOPLE)
    for name in ("_rowid", "_total"):
        for value in ("show", "", "true", "1", "Hide"):
            response = read({name: value})
            assert response.status_code == 400, (name, value)
            body = response.get_json()
            assert body["ok"] is False
            assert isinstance(body["error"], str) and body["error"]


# Spec: "Any repeated control parameter (`_size`, `_offset`, `_shape`, `_sort`,
# `_sort_desc`, `_rowid`, `_total`) is `HTTP 400`."
# Context: each control listed, repeated with values that are valid on their own.
def test_repeated_control_parameter_is_400(reader):
    read = reader(PEOPLE)
    repeats = {
        "_size": ["1", "2"],
        "_offset": ["0", "1"],
        "_shape": ["lists", "objects"],
        "_sort": ["name", "age"],
        "_sort_desc": ["name", "age"],
        "_rowid": ["hide", "hide"],
        "_total": ["hide", "hide"],
    }
    for name, values in repeats.items():
        response = read({name: values})
        assert response.status_code == 400, name
        assert response.get_json()["ok"] is False


# Spec: "Any repeated control parameter ... is `HTTP 400`."
# Context: the rule names the control parameters; other query parameters are
# not controls and stay ignored.
def test_repeated_non_control_parameter_is_fine(reader):
    response = reader(PEOPLE)({"other": ["a", "b"], "_size": "1"})
    assert response.status_code == 200
    assert response.get_json()["rows"] == [["grace", 45]]
