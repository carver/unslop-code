"""Schema files that declare the nested kinds: struct, array<T> and map<string,T>."""

from conftest import array, cell, mapping, rows_of, struct


# Spec: "struct: ordered list of named fields (names unique within struct)"
def test_struct_column_declares_named_fields(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "ann", "age": 30}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string"), ("age", "int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "user") == '{"name":"ann","age":30}'


# Spec: "array<T>: homogeneous element type T (can be nested)"
def test_array_column_casts_every_element_to_the_element_type(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "ns": ["1", 2, "3"]}])
    make_schema("s.json", [("id", "int"), ("ns", array("int"))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "ns") == "[1,2,3]"


# Spec: "map<string,T>: string keys only; value type T can be nested or primitive"
def test_map_column_casts_every_value_to_the_value_type(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "attrs": {"country": "US", "city": "NYC"}}])
    make_schema("s.json", [("id", "int"), ("attrs", mapping("string"))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "attrs") == '{"city":"NYC","country":"US"}'


# Spec: the example schema's "items" column - an array whose element is a struct
def test_array_of_struct_matches_the_spec_example(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "items": [{"sku": "a", "qty": 2}, {"sku": "b", "qty": 3}]}])
    make_schema("s.json", [("id", "int"), ("items", array(struct(("sku", "string"), ("qty", "int"))))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "items") == '[{"sku":"a","qty":2},{"sku":"b","qty":3}]'


# Spec: the example schema's "user" column - a struct holding a map field
def test_struct_holding_a_map_matches_the_spec_example(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "ann", "age": 30, "prefs": {"b": "2", "a": "1"}}}])
    make_schema(
        "s.json",
        [
            ("id", "int"),
            ("user", struct(("name", "string"), ("age", "int"), ("prefs", mapping("string")))),
        ],
    )
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "user") == '{"name":"ann","age":30,"prefs":{"a":"1","b":"2"}}'


# Spec: "value type T can be nested or primitive"
def test_map_of_array_nests_further(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "m": {"k": [1, 2]}}])
    make_schema("s.json", [("id", "int"), ("m", mapping(array("int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "m") == '{"k":[1,2]}'


# Spec: "array<T>: homogeneous element type T (can be nested)"
def test_array_of_array_nests_further(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "grid": [[1, 2], [3]]}])
    make_schema("s.json", [("id", "int"), ("grid", array(array("int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "grid") == "[[1,2],[3]]"


# Spec: "struct: ordered list of named fields (names unique within struct)"
# Context: a repeated field name makes the declaration ill-formed.
def test_duplicate_struct_field_names_are_rejected(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"name": "ann"}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("name", "string"), ("name", "int")))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl", expect_ok=False)
    assert proc.returncode != 0
    assert "name" in proc.stderr


# Spec: "map<string,T>: string keys only"
def test_map_with_a_non_string_key_type_is_rejected(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "m": {"k": "v"}}])
    make_schema("s.json", [("id", "int"), ("m", mapping("string", key="int"))])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl", expect_ok=False)
    assert proc.returncode != 0


# Spec: "unknown types error deterministically"
# Context: see AMBIGUITIES T49 - an unknown type keeps the bad-schema exit code 1.
def test_unknown_type_name_is_an_error(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    make_schema("s.json", [("id", "int"), ("v", "blob")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl", expect_ok=False)
    assert proc.returncode == 1
    assert "blob" in proc.stderr


# Spec: "Primitive types unchanged: `string`, `int`, `float`, `bool`, `date`, `timestamp`"
def test_primitive_columns_still_work_beside_nested_ones(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "flag": True, "user": {"name": "ann"}}])
    make_schema("s.json", [("id", "int"), ("flag", "bool"), ("user", struct(("name", "string")))])
    rows = rows_of(run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl").stdout)
    assert cell(rows, "flag") == "true"
    assert cell(rows, "user") == '{"name":"ann"}'


# Spec: "`list<T>`->`array<T>`" implies types may also be written as text generics.
# Context: see AMBIGUITIES T51.
def test_types_may_be_written_as_text_generics(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "ns": [1, 2], "m": {"b": 2, "a": 1}}])
    make_schema("s.json", [("id", "int"), ("ns", "array<int>"), ("m", "map<string,int>")])
    rows = rows_of(run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl").stdout)
    assert cell(rows, "ns") == "[1,2]"
    assert cell(rows, "m") == '{"a":1,"b":2}'
