"""Recursive casting inside nested values and the --on-type-error policies."""

from conftest import array, cell, mapping, rows_of, struct


def _nested_cell(run, make_jsonl, make_schema, declared, value, *extra):
    """Cast one nested cell and return the text it renders to.

    The cell is read back with the tool's own escape character, which the
    output dialect applies to the backslashes of JSON escaping (T55).
    """
    make_jsonl("a.jsonl", [{"id": 1, "v": value}])
    make_schema("s.json", [("id", "int"), ("v", declared)])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", *extra, "a.jsonl")
    return cell(rows_of(proc.stdout, escapechar="\\"), "v")


# Spec: "Nested values cast recursively to declared types"
def test_struct_fields_are_cast_to_their_declared_types(run, make_jsonl, make_schema):
    declared = struct(("age", "int"), ("score", "float"), ("ok", "bool"))
    assert _nested_cell(run, make_jsonl, make_schema, declared, {"age": "007", "score": "1.50", "ok": "1"}) == (
        '{"age":7,"score":1.5,"ok":true}'
    )


# Spec: "Primitive casting rules, temporal normalization, null handling apply
# recursively inside nested values"
def test_casting_reaches_every_level_of_nesting(run, make_jsonl, make_schema):
    declared = array(mapping(struct(("n", "int"))))
    assert _nested_cell(run, make_jsonl, make_schema, declared, [{"k": {"n": "5"}}]) == '[{"k":{"n":5}}]'


# Spec: "On cast failure within nested structures: `coerce-null`: set
# field/element to JSON `null`"
def test_coerce_null_nulls_only_the_failing_field(run, make_jsonl, make_schema):
    declared = struct(("age", "int"), ("name", "string"))
    assert _nested_cell(run, make_jsonl, make_schema, declared, {"age": "abc", "name": "ann"}) == (
        '{"age":null,"name":"ann"}'
    )


# Spec: "On cast failure within nested structures: `coerce-null`: set
# field/element to JSON `null`"
# Context: the same holds for an element of an array.
def test_coerce_null_nulls_only_the_failing_element(run, make_jsonl, make_schema):
    assert _nested_cell(run, make_jsonl, make_schema, array("int"), [1, "abc", 3]) == "[1,null,3]"


# Spec: "`keep-string`: set to original unparsed JSON string or stringified form"
def test_keep_string_keeps_the_failing_scalar_as_text(run, make_jsonl, make_schema):
    declared = struct(("age", "int"), ("name", "string"))
    assert _nested_cell(
        run, make_jsonl, make_schema, declared, {"age": "abc", "name": "ann"}, "--on-type-error", "keep-string"
    ) == '{"age":"abc","name":"ann"}'


# Spec: "`keep-string`: set to original unparsed JSON string or stringified form"
# Context: see AMBIGUITIES T61 - a subtree that cannot be cast is kept as its
# own JSON text.
def test_keep_string_keeps_a_failing_subtree_as_json_text(run, make_jsonl, make_schema):
    declared = struct(("age", "int"))
    assert _nested_cell(
        run, make_jsonl, make_schema, declared, {"age": {"x": 1}}, "--on-type-error", "keep-string"
    ) == '{"age":"{\\"x\\":1}"}'


# Spec: "`fail`: emit `ERR 4 cannot cast "<val>" to <type> in field "<path>"
# (file=... line=...)`"
def test_fail_reports_the_value_type_path_and_position(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "user": {"age": "abc"}}])
    make_schema("s.json", [("id", "int"), ("user", struct(("age", "int")))])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "fail", "a.jsonl", expect_ok=False,
    )
    assert proc.returncode == 4
    assert 'ERR 4 cannot cast "abc" to int in field "user.age"' in proc.stderr
    assert "file=a.jsonl" in proc.stderr and "line=1" in proc.stderr


# Spec: "`fail`: emit `ERR 4 ... in field "<path>"`"
# Context: the path of an array element carries its index.
def test_fail_names_an_array_element_by_index(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "items": [{"qty": 1}, {"qty": "x"}]}])
    make_schema("s.json", [("id", "int"), ("items", array(struct(("qty", "int"))))])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "fail", "a.jsonl", expect_ok=False,
    )
    assert 'in field "items.1.qty"' in proc.stderr


# Spec: "`fail`: emit `ERR 4 ... in field "<path>"`"
# Context: a map value is named by its bracketed key.
def test_fail_names_a_map_value_by_its_key(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "attrs": {"n": "x"}}])
    make_schema("s.json", [("id", "int"), ("attrs", mapping("int"))])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "fail", "a.jsonl", expect_ok=False,
    )
    assert 'in field "attrs[\"n\"]"' in proc.stderr


# Spec: "`fail`: emit `ERR 4 cannot cast ...`"
# Context: see AMBIGUITIES T47 - a flat column's cast failure reports the same way.
def test_fail_on_a_flat_column_reports_err_four(make_csv, make_schema, run):
    make_csv("a.csv", "id,v\n1,abc\n")
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--on-type-error", "fail", "a.csv", expect_ok=False,
    )
    assert proc.returncode == 4
    assert 'ERR 4 cannot cast "abc" to int in field "v"' in proc.stderr


# Spec: "Primitive casting rules ... null handling apply recursively inside
# nested values"
# Context: a JSON null inside a struct is a null, not a cast failure.
def test_json_nulls_inside_nested_values_stay_null(run, make_jsonl, make_schema):
    declared = struct(("age", "int"))
    assert _nested_cell(run, make_jsonl, make_schema, declared, {"age": None}, "--on-type-error", "fail") == (
        '{"age":null}'
    )


# Spec: "Nested values cast recursively to declared types"
# Context: see AMBIGUITIES T57 - a value of the wrong shape for its declared
# kind is one cast failure for the whole subtree.
def test_a_value_of_the_wrong_shape_is_a_single_failure(run, make_jsonl, make_schema):
    assert _nested_cell(run, make_jsonl, make_schema, struct(("name", "string")), [1, 2]) == ""
    assert _nested_cell(run, make_jsonl, make_schema, array("int"), {"a": 1}) == ""


# Spec: "Nested values cast recursively to declared types"
# Context: see AMBIGUITIES T58 - input fields the struct does not declare are dropped.
def test_undeclared_struct_fields_are_dropped(run, make_jsonl, make_schema):
    declared = struct(("name", "string"))
    assert _nested_cell(run, make_jsonl, make_schema, declared, {"name": "ann", "extra": 1}) == '{"name":"ann"}'


# Spec: "For `json` type: accept any JSON value without casting"
# Context: nothing inside a json column can fail, even under `fail`.
def test_json_columns_never_fail(run, make_jsonl, make_schema):
    assert _nested_cell(
        run, make_jsonl, make_schema, "json", {"a": [1, "x", None]}, "--on-type-error", "fail"
    ) == '{"a":[1,"x",null]}'


# Spec: "Primitive casting rules ... apply recursively inside nested values"
# Context: see AMBIGUITIES T68 - the JSONL rule that an integral float is an
# integer holds inside nested values too.
def test_integral_floats_cast_to_int_inside_nested_values(run, make_jsonl, make_schema):
    assert _nested_cell(run, make_jsonl, make_schema, array("int"), [2.0, 3.0]) == "[2,3]"
