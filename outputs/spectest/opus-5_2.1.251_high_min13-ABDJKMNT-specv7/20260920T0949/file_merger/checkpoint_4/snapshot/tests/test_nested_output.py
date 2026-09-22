"""Canonical JSON encoding of nested cells, and when a cell is null instead."""

from conftest import array, cell, mapping, rows_of, struct


# Spec: "serialize nested value as canonical JSON: Minified (no spaces)"
def test_output_json_is_minified(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "ann", "age": 30}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string"), ("age", "int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert " " not in cell(rows_of(proc.stdout), "user")


# Spec: "Struct fields in schema-declared order"
def test_struct_fields_follow_the_schema_order(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"age": 30, "name": "ann"}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string"), ("age", "int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "user") == '{"name":"ann","age":30}'


# Spec: "Map keys sorted lexicographically"
def test_map_keys_are_sorted(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "attrs": {"zz": "1", "aa": "2", "Ab": "3"}}])
    make_schema("s.json", [("id", "int"), ("attrs", mapping("string"))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "attrs") == '{"Ab":"3","aa":"2","zz":"1"}'


# Spec: "Map keys sorted lexicographically"
# Context: see AMBIGUITIES T53 - an object inside a `json` column sorts too.
def test_json_object_keys_are_sorted(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "flex": {"b": 1, "a": {"d": 2, "c": 3}}}])
    make_schema("s.json", [("id", "int"), ("flex", "json")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "flex") == '{"a":{"c":3,"d":2},"b":1}'


# Spec: "Arrays preserve original element order after casting"
def test_arrays_keep_their_input_order(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "ns": [3, 1, 2]}])
    make_schema("s.json", [("id", "int"), ("ns", array("int"))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "ns") == "[3,1,2]"


# Spec: "Timestamps inside nested values normalized to UTC `Z`; `date` stays
# `YYYY-MM-DD`"
def test_temporal_values_inside_nested_values_are_normalised(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "when": {"ts": "2024-07-01T12:00:00+02:00", "day": "2024-07-01"}}])
    make_schema("s.json", [("id", "int"), ("when", struct(("ts", "timestamp"), ("day", "date")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "when") == '{"ts":"2024-07-01T10:00:00Z","day":"2024-07-01"}'


# Spec: "All struct fields included (even when null) with explicit `null` values"
def test_missing_struct_fields_are_emitted_as_null(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "ann"}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string"), ("age", "int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "user") == '{"name":"ann","age":null}'


# Spec: "If entire column value is null -> emit CSV null literal"
def test_a_wholly_null_nested_cell_uses_the_null_literal(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": None}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "user") == ""


# Spec: "If entire column value is null -> emit CSV null literal"
# Context: the literal is the configured one, and it does not reach inside the JSON.
def test_the_configured_null_literal_applies_only_to_the_whole_cell(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": None, "other": {"name": None}}])
    make_schema(
        "s.json",
        [("id", "int"), ("user", struct(("name", "string"))), ("other", struct(("name", "string")))],
    )
    rows = rows_of(
        run("--output", "-", "--key", "id", "--schema", "s.json", "--csv-null-literal", "NULL", "a.jsonl").stdout
    )
    assert cell(rows, "user") == "NULL"
    assert cell(rows, "other") == '{"name":null}'


# Spec: "If entire column value is null -> emit CSV null literal"
# Context: a column the record never carried is null as well.
def test_a_missing_nested_column_is_null(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "user") == ""


# Spec: "Arrays preserve original element order after casting"
# Context: a null element keeps its place rather than dropping out.
def test_null_array_elements_keep_their_place(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "ns": [1, None, 3]}])
    make_schema("s.json", [("id", "int"), ("ns", array("int"))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "ns") == "[1,null,3]"


# Spec: "Minified (no spaces), UTF-8, RFC 8259 JSON escaping"
# Context: see AMBIGUITIES T55 - the output dialect then escapes the backslashes
# the JSON escaping introduced, so the cell is read back with that dialect.
def test_json_strings_use_rfc_8259_escaping(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": 'a"b\\c\nd\te'}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout, escapechar="\\"), "user") == '{"name":"a\\"b\\\\c\\nd\\te"}'


# Spec: "Minified (no spaces), UTF-8, RFC 8259 JSON escaping"
# Context: see AMBIGUITIES T52 - UTF-8 means non-ASCII characters are written
# as themselves rather than as \uXXXX escapes.
def test_non_ascii_text_is_written_as_utf8(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "café"}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "user") == '{"name":"café"}'


# Spec: "This JSON is the CSV cell content for nested columns"
# Context: the cell is quoted by the output dialect, so it survives a read back.
def test_the_json_cell_is_quoted_by_the_output_dialect(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "a,b"}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert '"{""name"":""a,b""}"' in proc.stdout
    assert cell(rows_of(proc.stdout), "user") == '{"name":"a,b"}'


# Spec: "For `json` type: accept any JSON value without casting; normalize only"
def test_json_columns_are_normalised_but_not_cast(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "flex": {"n": "007", "d": "2024-07-01T12:00:00+02:00"}}])
    make_schema("s.json", [("id", "int"), ("flex", "json")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "flex") == '{"d":"2024-07-01T12:00:00+02:00","n":"007"}'


# Spec: "Output remains CSV with nested columns as canonical JSON"
# Context: the header still lists every resolved column, nested ones included.
def test_header_lists_nested_columns_like_any_other(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "ann"}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert rows_of(proc.stdout)[0] == ["id", "user"]
