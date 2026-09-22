"""Spec section: Type Aliases (checkpoint 4)."""
import json

from conftest import (alias_file, array_t, cell, col, map_t, run_tool,
                      struct_t, write_csv, write_file, write_json,
                      write_jsonl, write_nested_schema)


# --------------------------------------------------------------------------
# Phrase: "Built-in aliases (always present): integer->int, long->int,
#          double->float, number->float, boolean->bool"
# Context: Type Aliases; no --type-alias-file needed.
# --------------------------------------------------------------------------
def test_builtin_numeric_and_bool_aliases(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("a", "integer"), ("b", "long"),
                                 ("c", "double"), ("d", "number"),
                                 ("e", "boolean"))
    src = write_csv(tmp_path / "a.csv", ["a,b,c,d,e", "1,2,3,4,true"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["1", "2", "3.0", "4.0", "true"]


# Phrase: "datetime->timestamp, timestamptz->timestamp, text->string,
#          varchar->string"
def test_builtin_temporal_and_text_aliases(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("a", "datetime"), ("b", "timestamptz"),
                                 ("c", "text"), ("d", "varchar"))
    src = write_csv(tmp_path / "a.csv",
                    ["a,b,c,d",
                     "2024-01-02 03:04:05,2024-01-02T03:04:05+02:00,x,y"])
    res = run_tool("--output", "-", "--key", "c", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["2024-01-02T03:04:05Z",
                             "2024-01-02T01:04:05Z", "x", "y"]


# Phrase: "Case-insensitive aliases accepted anywhere type is expected"
# Context: the alias name and the canonical name both fold case.
def test_alias_lookup_is_case_insensitive(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("a", "INTEGER"), ("b", "Boolean"),
                                 ("c", "STRING"))
    src = write_csv(tmp_path / "a.csv", ["a,b,c", "1,true,z"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["1", "true", "z"]


# Phrase: "Case-insensitive aliases accepted anywhere type is expected"
# Context: inside struct fields, array elements and map values too.
def test_aliases_apply_inside_nested_types(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json",
        ("id", "integer"),
        ("u", struct_t(("n", "Text"), ("k", "LONG"))),
        ("t", array_t("double")),
        ("m", map_t("boolean")))
    src = write_jsonl(tmp_path / "a.jsonl", [
        {"id": 1, "u": {"n": "x", "k": "7"}, "t": ["1"], "m": {"z": "true"}},
    ])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    rows = res.rows()
    assert cell(rows, "u") == '{"n":"x","k":7}'
    assert cell(rows, "t") == '[1.0]'
    assert cell(rows, "m") == '{"z":true}'


# --------------------------------------------------------------------------
# Phrase: "list<T> -> array<T>"
# Context: Built-in aliases; the parameterised alias implies textual generics.
# --------------------------------------------------------------------------
def test_list_generic_is_an_array(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", "list<int>"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [1, 2]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == "[1,2]"


def test_array_generic_spelling(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", "ARRAY<Integer>"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [1]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == "[1]"


def test_map_generic_spelling(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("m", "map<string,list<int>>"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"a": [1]}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '{"a":[1]}'


def test_list_object_form_is_an_array(tmp_path):
    schema = write_json(
        tmp_path / "s.json",
        {"columns": [{"name": "id", "type": "int"},
                     {"name": "t", "type": {"list": {"element": "int"}}}]})
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": [3]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == "[3]"


# --------------------------------------------------------------------------
# Phrase: "json -> struct (accept any JSON, see below)"
# Phrase: "Special alias json: when field declared as "type":"json", accept
#          any JSON value (object/array/primitive) and emit as JSON text"
# --------------------------------------------------------------------------
def test_json_type_accepts_object_array_and_primitive(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = write_jsonl(tmp_path / "a.jsonl", [
        {"id": 1, "v": {"b": 1, "a": [1, "x"]}},
        {"id": 2, "v": [1, 2, 3]},
        {"id": 3, "v": "plain"},
        {"id": 4, "v": 7},
        {"id": 5, "v": True},
    ])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ['{"a":[1,"x"],"b":1}', "[1,2,3]",
                                    '"plain"', "7", "true"]


# Phrase: "For json type: accept any JSON value without casting"
# Context: values that would never cast to a primitive still survive.
def test_json_type_does_not_cast(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "json"))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "v": {"n": 1.5, "s": "0001", "b": False}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "v") == '{"b":false,"n":1.5,"s":"0001"}'


# Phrase: "json -> struct"
# Context: a bare `struct` spelling means the same accept-anything type (T53).
def test_bare_struct_alias_behaves_like_json(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("v", "struct"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "v") == '{"a":1}'


# --------------------------------------------------------------------------
# Phrase: "Optional alias file via --type-alias-file <ALIASES_JSON>"
# Context: the documented alias document.
# --------------------------------------------------------------------------
def test_documented_alias_file(tmp_path):
    aliases = alias_file(tmp_path / "al.json",
                         {"smallint": "int", "decimal": "float",
                          "uuid": "string", "myts": "timestamp"})
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("a", "smallint"), ("b", "decimal"),
                                 ("c", "uuid"), ("d", "myts"))
    src = write_csv(tmp_path / "a.csv",
                    ["a,b,c,d", "3,2.5,abc,2024-05-06T07:08:09Z"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["3", "2.5", "abc", "2024-05-06T07:08:09Z"]


# Phrase: "Aliases apply after lowercasing names"
# Context: an alias declared in mixed case is matched case-insensitively.
def test_alias_names_are_lowercased(tmp_path):
    aliases = alias_file(tmp_path / "al.json", {"SmallInt": "INT"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "SMALLINT"))
    src = write_csv(tmp_path / "a.csv", ["a", "4"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["4"]


# Phrase: "May refer to built-ins or other aliases (resolve transitively ...)"
def test_alias_chain_resolves_transitively(tmp_path):
    aliases = alias_file(tmp_path / "al.json",
                         {"a1": "a2", "a2": "a3", "a3": "integer"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "a1"))
    src = write_csv(tmp_path / "a.csv", ["a", "12"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["12"]


def test_alias_may_name_a_nested_generic(tmp_path):
    aliases = alias_file(tmp_path / "al.json", {"tags": "list<text>"})
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", "tags"))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": ["a", "b"]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == '["a","b"]'


# Phrase: "detect cycles proactively -> error 2"
def test_direct_alias_cycle_is_error_2(tmp_path):
    aliases = alias_file(tmp_path / "al.json", {"x": "y", "y": "x"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "int"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 2
    assert res.stderr.strip() != ""


def test_self_alias_cycle_is_error_2(tmp_path):
    aliases = alias_file(tmp_path / "al.json", {"x": "x"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "int"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 2


def test_longer_alias_cycle_is_error_2(tmp_path):
    aliases = alias_file(tmp_path / "al.json",
                         {"p": "q", "q": "r", "r": "p"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "int"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 2


# Phrase: "detect cycles proactively"
# Context: proactive means even an alias the schema never mentions (T61).
def test_unused_cycle_still_detected(tmp_path):
    aliases = alias_file(tmp_path / "al.json",
                         {"used": "int", "x": "y", "y": "x"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "used"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 2


# Phrase: "unknown types error deterministically"
# Context: Determinism Checklist; an alias to nothing known fails on use.
def test_alias_to_unknown_type_is_a_schema_error(tmp_path):
    aliases = alias_file(tmp_path / "al.json", {"weird": "widget"})
    schema = write_nested_schema(tmp_path / "s.json", ("a", "weird"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", aliases, src)
    assert res.returncode == 3


def test_unknown_type_without_aliases_is_a_schema_error(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json", ("a", "widget"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 3


# Phrase: "Optional alias file via --type-alias-file <ALIASES_JSON>"
# Context: a malformed or unreadable alias document is an argument error.
def test_malformed_alias_file_is_an_error(tmp_path):
    bad = write_file(tmp_path / "al.json", "{not json")
    schema = write_nested_schema(tmp_path / "s.json", ("a", "int"))
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema,
                   "--type-alias-file", bad, src)
    assert res.returncode != 0
    assert res.stderr.strip() != ""


def test_alias_file_may_override_nothing_when_absent(tmp_path):
    # Without --type-alias-file the built-ins are still present.
    schema = write_nested_schema(tmp_path / "s.json", ("a", "integer"))
    src = write_csv(tmp_path / "a.csv", ["a", "9"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["9"]
