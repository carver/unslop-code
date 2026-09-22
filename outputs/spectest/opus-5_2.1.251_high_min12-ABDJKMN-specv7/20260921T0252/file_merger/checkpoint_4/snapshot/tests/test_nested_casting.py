"""Spec section: Casting & Validation for nested values (checkpoint 4)."""
import json

from conftest import (array_t, cell, col, map_t, run_tool, struct_t,
                      write_csv, write_json, write_jsonl,
                      write_nested_schema)


# --------------------------------------------------------------------------
# Phrase: "Nested values cast recursively to declared types"
# Context: Casting & Validation.
# --------------------------------------------------------------------------
def test_struct_fields_cast_to_declared_types(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json", ("id", "int"),
        ("u", struct_t(("n", "string"), ("age", "int"), ("f", "float"),
                       ("b", "bool"))))
    src = write_jsonl(tmp_path / "a.jsonl", [
        {"id": 1, "u": {"n": 5, "age": "36", "f": "2", "b": "1"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"n":"5","age":36,"f":2.0,"b":true}'


def test_array_elements_cast_to_declared_type(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": ["1", 2, "3"]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == "[1,2,3]"


def test_map_values_cast_to_declared_type(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("m", map_t("float")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"a": "1.5"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '{"a":1.5}'


# Phrase: "Primitive casting rules, temporal normalization, null handling
#          apply recursively inside nested values"
def test_temporal_normalisation_inside_nested(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json", ("id", "int"),
        ("u", struct_t(("d", "date"), ("ts", "timestamp"))))
    src = write_jsonl(tmp_path / "a.jsonl", [
        {"id": 1, "u": {"d": "2024-01-02",
                        "ts": "2024-01-02T05:06:07+02:00"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == \
        '{"d":"2024-01-02","ts":"2024-01-02T03:06:07Z"}'


def test_null_inside_nested_stays_null(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [1, None, 3]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == "[1,null,3]"


# --------------------------------------------------------------------------
# Phrase: "On cast failure within nested structures: coerce-null: set
#          field/element to JSON null"
# Context: Casting & Validation.
# --------------------------------------------------------------------------
def test_coerce_null_nulls_the_failing_struct_field(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"), ("b", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "u": {"a": "oops", "b": 2}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "coerce-null", src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":null,"b":2}'


def test_coerce_null_nulls_the_failing_array_element(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [1, "x", 3]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == "[1,null,3]"


def test_coerce_null_nulls_the_failing_map_value(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("m", map_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"a": "z"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '{"a":null}'


def test_coerce_null_on_a_structurally_wrong_subvalue(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", array_t("int")))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": "nope"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":null}'


# --------------------------------------------------------------------------
# Phrase: "keep-string: set to original unparsed JSON string or stringified
#          form"
# Context: Casting & Validation (T65).
# --------------------------------------------------------------------------
def test_keep_string_keeps_the_failing_scalar(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"), ("b", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "u": {"a": "oops", "b": 2}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "keep-string", src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":"oops","b":2}'


def test_keep_string_stringifies_a_container(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": [1, 2]}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "keep-string", src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":"[1,2]"}'


def test_keep_string_inside_an_array(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [1, "x"]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "keep-string", src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == '[1,"x"]'


# --------------------------------------------------------------------------
# Phrase: "fail: emit ERR 4 cannot cast "<val>" to <type> in field "<path>"
#          (file=... line=...)"
# Context: Casting & Validation.
# --------------------------------------------------------------------------
def test_fail_inside_struct_reports_err_4(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("user", struct_t(("age", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "user": {"age": "old"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 4
    assert res.stderr.startswith("ERR 4 cannot cast ")
    assert '"old"' in res.stderr
    assert " to int " in res.stderr
    assert 'field "user.age"' in res.stderr
    assert "file=" in res.stderr and "line=" in res.stderr


def test_fail_inside_array_names_the_index_in_the_path(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json", ("id", "int"),
        ("items", array_t(struct_t(("qty", "int")))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "items": [{"qty": 1}, {"qty": "x"}]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 4
    assert 'field "items.1.qty"' in res.stderr


def test_fail_inside_map_names_the_key_in_the_path(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("attrs", map_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "attrs": {"c": "x"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 4
    assert 'field "attrs[\"c\"]"' in res.stderr


def test_fail_names_the_input_file_and_line(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "events.jsonl",
                      [{"id": 1, "u": {"a": 1}},
                       {"id": 2, "u": {"a": "bad"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 4
    assert "events.jsonl" in res.stderr
    assert "line=2" in res.stderr


def test_fail_on_a_flat_column_uses_the_same_shape(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"))
    src = write_csv(tmp_path / "a.csv", ["id", "zz"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 4
    assert res.stderr.startswith("ERR 4 cannot cast ")
    assert 'field "id"' in res.stderr


def test_fail_emits_a_single_stderr_line(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("id", "int"),
                                 ("u", struct_t(("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": "b"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 4
    assert res.stderr.count("\n") == 1


# --------------------------------------------------------------------------
# Phrase: "For json type: accept any JSON value without casting; normalize
#          only"
# --------------------------------------------------------------------------
def test_json_column_never_fails(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "v": {"deep": [{"x": None}, 2, "s"]}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "v") == '{"deep":[{"x":null},2,"s"]}'


def test_json_column_null_is_the_csv_null_literal(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": None}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == [""]
