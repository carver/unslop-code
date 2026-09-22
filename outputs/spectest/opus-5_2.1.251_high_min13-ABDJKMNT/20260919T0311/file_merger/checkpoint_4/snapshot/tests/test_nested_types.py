"""Nested type declarations in `--schema`: struct, array<T> and map<string,T>."""
from conftest import column, table

STRUCT = {"struct": {"fields": [{"name": "name", "type": "string"},
                                {"name": "age", "type": "int"}]}}


# Phrase: "struct: ordered list of named fields"
# Context: the declared field order is the order the cell's JSON carries.
def test_struct_column_emits_fields_in_declared_order(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"age": 30, "name": "ada"}}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "user", "type": STRUCT}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"name":"ada","age":30}']


# Phrase: "array<T>: homogeneous element type T (can be nested)"
# Context: an array of structs, the spec's own `items` column.
def test_array_of_structs_casts_every_element(run, jsonl_file, json_file):
    items = {"array": {"element": {"struct": {"fields": [
        {"name": "sku", "type": "string"}, {"name": "qty", "type": "int"}]}}}}
    data = jsonl_file("a.jsonl", [{"id": 1, "items": [{"sku": "a", "qty": "2"},
                                                      {"sku": "b", "qty": 3}]}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "items", "type": items}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "items") == ['[{"sku":"a","qty":2},{"sku":"b","qty":3}]']


# Phrase: "map<string,T>: string keys only; value type T can be nested or primitive"
# Context: a map whose values are themselves arrays.
def test_map_of_arrays(run, jsonl_file, json_file):
    attrs = {"map": {"key": "string", "value": {"array": {"element": "int"}}}}
    data = jsonl_file("a.jsonl", [{"id": 1, "attrs": {"b": [1, 2], "a": [3]}}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "attrs", "type": attrs}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "attrs") == ['{"a":[3],"b":[1,2]}']


# Phrase: "struct ... (names unique within struct)"
# Context: T48 - a duplicate field name makes the schema unusable (exit 3).
def test_duplicate_struct_field_names_are_a_schema_error(run, jsonl_file, json_file):
    duped = {"struct": {"fields": [{"name": "a", "type": "int"},
                                   {"name": "a", "type": "string"}]}}
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"a": 1}}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "user", "type": duped}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 3, res.stderr


# Phrase: "map<string,T>: string keys only"
# Context: T49 - any other declared key type is rejected while resolving the schema.
def test_map_with_non_string_key_is_a_schema_error(run, jsonl_file, json_file):
    attrs = {"map": {"key": "int", "value": "string"}}
    data = jsonl_file("a.jsonl", [{"id": 1, "attrs": {"a": "b"}}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "attrs", "type": attrs}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 3, res.stderr


# Phrase: "unknown types error deterministically"
# Context: a type name that is neither primitive, nested kind nor alias.
def test_unknown_type_name_exits_3(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "widget"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 3, res.stderr


# Phrase: "list<T>->array<T>"
# Context: T47 - the generic spelling of a nested type is also accepted as a string.
def test_generic_string_spellings_of_nested_types(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "tags": ["x", "y"], "m": {"k": 2}}])
    schema = json_file("s.json", {"columns": [
        {"name": "id", "type": "int"},
        {"name": "tags", "type": "list<string>"},
        {"name": "m", "type": "map<string,int>"}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == ["1", '["x","y"]', '{"k":2}']


# Phrase: "array<T> ... (can be nested)"
# Context: arrays of arrays keep both levels' ordering.
def test_array_of_arrays(run, jsonl_file, json_file):
    nested = {"array": {"element": {"array": {"element": "int"}}}}
    data = jsonl_file("a.jsonl", [{"id": 1, "grid": [[2, 1], [3]]}])
    schema = json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                              {"name": "grid", "type": nested}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "grid") == ["[[2,1],[3]]"]


# Phrase: "Primitive types unchanged: string, int, float, bool, date, timestamp"
# Context: a struct of every primitive, each normalized by its own rules.
def test_primitive_rules_apply_inside_a_struct(run, jsonl_file, json_file):
    fields = [{"name": "s", "type": "string"}, {"name": "i", "type": "int"},
              {"name": "f", "type": "float"}, {"name": "b", "type": "bool"},
              {"name": "d", "type": "date"}, {"name": "t", "type": "timestamp"}]
    row = {"id": 1, "all": {"s": "x", "i": "7", "f": "1.5", "b": "TRUE",
                            "d": "2024-07-01", "t": "2024-07-01T05:00:00+02:00"}}
    data = jsonl_file("a.jsonl", [row])
    schema = json_file("s.json", {"columns": [
        {"name": "id", "type": "int"},
        {"name": "all", "type": {"struct": {"fields": fields}}}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "all") == [
        '{"s":"x","i":7,"f":1.5,"b":true,"d":"2024-07-01","t":"2024-07-01T03:00:00Z"}'
    ]
