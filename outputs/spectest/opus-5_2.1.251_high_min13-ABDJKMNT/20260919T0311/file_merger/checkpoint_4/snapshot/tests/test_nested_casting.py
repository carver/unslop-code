"""Recursive casting inside nested values, and `--on-type-error` at depth."""
from conftest import column

USER = {"struct": {"fields": [{"name": "name", "type": "string"},
                              {"name": "age", "type": "int"}]}}


def _schema(json_file, type_):
    return json_file("s.json", {"columns": [{"name": "id", "type": "int"},
                                            {"name": "user", "type": type_}]})


# Phrase: "Nested values cast recursively to declared types"
# Context: a string inside a struct becomes the declared int.
def test_leaves_are_cast_to_their_declared_type(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": 7, "age": "30"}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"name":"7","age":30}']


# Phrase: "coerce-null: set field/element to JSON null"
# Context: only the offending field is nulled; its siblings survive.
def test_coerce_null_nulls_one_field(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada", "age": "old"}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER),
              "--on-type-error", "coerce-null", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"name":"ada","age":null}']


# Phrase: "keep-string: set to original unparsed JSON string or stringified form"
# Context: the field keeps the text it arrived as, inside the JSON cell.
def test_keep_string_keeps_the_field_text(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada", "age": "old"}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER),
              "--on-type-error", "keep-string", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"name":"ada","age":"old"}']


# Phrase: "keep-string: ... or stringified form"
# Context: T55 - a whole subtree that cannot cast is kept as its JSON text.
def test_keep_string_stringifies_a_failed_subtree(run, jsonl_file, json_file):
    array_of_ints = {"array": {"element": "int"}}
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"a": 1}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, array_of_ints),
              "--on-type-error", "keep-string", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['"{\\"a\\":1}"']


# Phrase: 'fail: emit ERR 4 cannot cast "<val>" to <type> in field "<path>"
#          (file=... line=...)'
# Context: the message names the dotted path of the failing leaf, not the column.
def test_fail_message_shape(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada", "age": "old"}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER),
              "--on-type-error", "fail", data)
    assert res.returncode == 4
    assert res.stderr.startswith('ERR 4 cannot cast "old" to int in field "user.age" (file=')
    assert res.stderr.rstrip().endswith("line=1)")


# Phrase: 'in field "<path>"'
# Context: an array element's path carries its index.
def test_fail_message_names_an_array_index(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": [1, "x"]}])
    res = run("--output", "-", "--key", "id", "--schema",
              _schema(json_file, {"array": {"element": "int"}}),
              "--on-type-error", "fail", data)
    assert res.returncode == 4
    assert 'in field "user.1"' in res.stderr


# Phrase: 'in field "<path>"'
# Context: a map value's path carries its bracketed key.
def test_fail_message_names_a_map_key(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"k": "x"}}])
    res = run("--output", "-", "--key", "id", "--schema",
              _schema(json_file, {"map": {"key": "string", "value": "int"}}),
              "--on-type-error", "fail", data)
    assert res.returncode == 4
    assert 'in field "user[\"k\"]"' in res.stderr


# Phrase: "For json type: accept any JSON value without casting; normalize only"
# Context: values that would fail every primitive cast pass through untouched.
def test_json_type_never_fails_a_cast(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"age": "old", "n": [1, None]}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, "json"),
              "--on-type-error", "fail", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"age":"old","n":[1,null]}']


# Phrase: "Primitive casting rules, temporal normalization, null handling apply
#          recursively inside nested values"
# Context: a timestamp two levels down is still normalized to UTC.
def test_temporal_normalization_applies_at_depth(run, jsonl_file, json_file):
    type_ = {"array": {"element": {"struct": {"fields": [{"name": "t", "type": "timestamp"},
                                                         {"name": "d", "type": "date"}]}}}}
    data = jsonl_file("a.jsonl", [{"id": 1, "user": [{"t": "2024-03-01T10:00:00-05:00",
                                                      "d": "2024-03-01"}]}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, type_), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['[{"t":"2024-03-01T15:00:00Z","d":"2024-03-01"}]']


# Phrase: "null handling apply recursively inside nested values"
# Context: an explicit JSON null needs no cast and stays null.
def test_explicit_nulls_survive_casting(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": None, "age": None}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER),
              "--on-type-error", "fail", data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"name":null,"age":null}']


# Phrase: "Nested values cast recursively to declared types"
# Context: a field the struct does not declare is not part of the column's value.
def test_undeclared_struct_fields_are_dropped(run, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada", "age": 1, "extra": 9}}])
    res = run("--output", "-", "--key", "id", "--schema", _schema(json_file, USER), data)
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "user") == ['{"name":"ada","age":1}']
