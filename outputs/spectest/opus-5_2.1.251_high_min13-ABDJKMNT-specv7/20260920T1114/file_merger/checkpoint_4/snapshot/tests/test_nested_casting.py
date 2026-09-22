"""Spec section: Casting & Validation — recursive casts inside nested values."""

from conftest import column
from nested_helpers import INT, array, mapping, struct, write_schema


PERSON = {"name": "user", "type": struct(("age", "int"), ("seen", "timestamp"))}


# Phrase: "Nested values cast recursively to declared types"
# Context: Casting & Validation.
def test_struct_fields_are_cast_recursively(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, PERSON])
    jsonl_file("a.jsonl", [{"id": 1, "user": {"age": "36", "seen": "2024-07-01"}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "user") == ['{"age":36,"seen":null}']


# Phrase: "Primitive casting rules, temporal normalization, null handling apply recursively"
# Context: Casting & Validation. Timestamps inside nested values become UTC Z.
def test_temporal_values_are_normalised_inside_nested(jsonl_file, run_tool):
    write_schema(
        jsonl_file,
        [INT, {"name": "xs", "type": array("timestamp")}, {"name": "d", "type": array("date")}],
    )
    jsonl_file(
        "a.jsonl",
        [{"id": 1, "xs": ["2024-07-01T05:00:00+02:00"], "d": ["2024-07-01"]}],
    )
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ['["2024-07-01T03:00:00Z"]']
    assert column(result.stdout, "d") == ['["2024-07-01"]']


# Phrase: "coerce-null: set field/element to JSON null"
# Context: On cast failure within nested structures.
def test_coerce_null_nulls_the_failing_element(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("int")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": [1, "nope", 3]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ["[1,null,3]"]


# Phrase: "keep-string: set to original unparsed JSON string or stringified form"
# Context: On cast failure within nested structures.
def test_keep_string_keeps_the_failing_element_as_text(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("int")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": [1, "nope", {"a": 1}]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "keep-string", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ['[1,"nope","{\\"a\\":1}"]']


# Phrase: 'fail: emit ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)'
# Context: On cast failure within nested structures.
def test_fail_names_the_value_type_path_and_origin(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, PERSON])
    jsonl_file(
        "a.jsonl",
        [{"id": 1, "user": {"age": 1}}, {"id": 2, "user": {"age": "old"}}],
    )
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert result.returncode == 4
    assert 'ERR 4 cannot cast "old" to int in field "user.age"' in result.stderr
    assert "file=a.jsonl" in result.stderr
    assert "line=2" in result.stderr


# Phrase: 'in field "<path>"'
# Context: On cast failure within nested structures. Array elements index into the path.
def test_failure_path_uses_array_indices(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("int")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": [1, "nope"]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert result.returncode == 4
    assert 'in field "xs.1"' in result.stderr


# Phrase: 'in field "<path>"'
# Context: On cast failure within nested structures. Map entries use bracketed keys.
def test_failure_path_uses_map_keys(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "m", "type": mapping("int")}])
    jsonl_file("a.jsonl", [{"id": 1, "m": {"a": "nope"}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert result.returncode == 4
    assert 'in field "m[\"a\"]"' in result.stderr


# Phrase: "For json type: accept any JSON value without casting; normalize only"
# Context: Casting & Validation. Numbers and strings keep their JSON shape.
def test_json_columns_are_not_cast(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "p", "type": "json"}])
    jsonl_file("a.jsonl", [{"id": 1, "p": {"n": "12", "f": 1.5, "b": False}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "p") == ['{"b":false,"f":1.5,"n":"12"}']


# Phrase: "null handling apply recursively inside nested values"
# Context: Casting & Validation. Explicit JSON nulls survive the cast.
def test_nulls_inside_nested_values_are_kept(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("string")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": ["a", None]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ['["a",null]']


# Phrase: "Nested values cast recursively to declared types"
# Context: Casting & Validation. A struct where an array is declared fails to cast.
def test_shape_mismatch_is_a_cast_failure(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("int")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": {"a": 1}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == [""]


# Phrase: "struct: ordered list of named fields"
# Context: Casting & Validation. Ambiguity T57: unknown input fields are dropped.
def test_undeclared_struct_fields_are_dropped(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "s", "type": struct(("a", "int"))}])
    jsonl_file("a.jsonl", [{"id": 1, "s": {"a": 1, "b": 2}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "s") == ['{"a":1}']
