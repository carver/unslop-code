"""Canonical JSON encoding of nested columns in the output CSV."""
from conftest import column, lines

USER = {"struct": {"fields": [{"name": "name", "type": "string"},
                              {"name": "age", "type": "int"}]}}


def _schema(json_file, type_, name="v"):
    return json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                            {"name": name, "type": type_}]})


# Phrase: "If entire column value is null -> emit CSV null literal"
# Context: a missing nested column value, against a non-empty null literal.
def test_whole_null_column_uses_the_null_literal(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1}, {"id": 2, "v": None}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER),
              "--csv-null-literal", "NULL", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "v") == ["NULL", "NULL"]


# Phrase: "All struct fields included (even when null) with explicit null values"
# Context: a struct that is present but empty still spells out its fields.
def test_absent_struct_fields_are_explicit_nulls(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER),
              "--csv-null-literal", "NULL", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "v") == ['{"name":null,"age":null}']


# Phrase: "Minified (no spaces)"
# Context: the raw output line, before any CSV parsing, carries no whitespace.
def test_output_json_is_minified(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"name": "a b", "age": 1}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER), data)
    assert res.returncode == 0, res.stderr
    assert lines(res.stdout)[1] == '1,"{""name"":""a b"",""age"":1}"'


# Phrase: "Struct fields in schema-declared order"
# Context: the input object's own key order is discarded.
def test_struct_order_follows_the_schema(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"age": 2, "name": "a"}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER), data)
    assert column(res.stdout, "v") == ['{"name":"a","age":2}']


# Phrase: "Map keys sorted lexicographically"
# Context: sorting is by code point, so uppercase sorts before lowercase.
def test_map_keys_are_sorted(run, jsonl_file, json_file):
    type_ = {"map": {"key": "string", "value": "int"}}
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"b": 1, "A": 2, "a": 3, "é": 4}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, type_), data)
    assert column(res.stdout, "v") == ['{"A":2,"a":3,"b":1,"é":4}']


# Phrase: "Arrays preserve original element order after casting"
# Context: an unsorted array of ints stays unsorted.
def test_array_order_is_preserved(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [3, 1, 2]}])
    res = run("--output", "-", "--key", "id", "--schema",
              _schema(json_file, {"array": {"element": "int"}}), data)
    assert column(res.stdout, "v") == ["[3,1,2]"]


# Phrase: "UTF-8, RFC 8259 JSON escaping"
# Context: non-ASCII stays as UTF-8 text, while control characters are escaped.
def test_json_escaping(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"k": "café\t\"x\"\\"}}])
    res = run("--output", "-", "--key", "id", "--schema",
              _schema(json_file, {"map": {"key": "string", "value": "string"}}), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "v") == ['{"k":"café\\t\\"x\\"\\\\"}']


# Phrase: "Timestamps inside nested values normalized to UTC Z; date stays
#          YYYY-MM-DD"
# Context: both temporal types side by side inside one map.
def test_temporal_rendering_inside_nested(run, jsonl_file, json_file):
    type_ = {"struct": {"fields": [{"name": "t", "type": "timestamp"},
                                   {"name": "d", "type": "date"}]}}
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"t": "2024-07-01", "d": "2024-07-01"}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, type_), data)
    assert column(res.stdout, "v") == ['{"t":"2024-07-01T00:00:00Z","d":"2024-07-01"}']


# Phrase: "This JSON is the CSV cell content for nested columns"
# Context: the cell is quoted by the ordinary CSV rules, and nothing else changes.
def test_nested_cell_is_quoted_by_csv_rules(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": ["a,b"]}])
    res = run("--output", "-", "--key", "id", "--schema",
              _schema(json_file, {"array": {"element": "string"}}), data)
    assert lines(res.stdout) == ["id,v", '1,"[""a,b""]"']


# Phrase: "Otherwise, serialize nested value as canonical JSON"
# Context: an empty struct-less container is still JSON, not the null literal.
def test_empty_containers_are_not_null(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": []}, {"id": 2, "v": {}}])
    schema = json_file("s.json", {"columns": [
        {"name": "id", "type": "int"},
        {"name": "v", "type": {"array": {"element": "int"}}}]})
    res = run("--output", "-", "--key", "id", "--schema", schema, data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "v")[0] == "[]"
