"""Spec section: Nested Types Support — "Type Aliases"."""

from conftest import (array_t, body, col, header, map_t, run, run_ok,
                      struct_t, write, write_aliases, write_json, write_jsonl,
                      write_nested_schema)


# --- Spec: "Built-in aliases (always present): integer->int, long->int,
#           double->float, number->float, boolean->bool" ---
# Context: Type Aliases; used wherever a type is expected.
def test_builtin_numeric_and_bool_aliases(ws):
    s = write_nested_schema(ws / "s.json", [
        ("a", "integer"), ("b", "long"), ("c", "double"),
        ("d", "number"), ("e", "boolean")])
    x = write(ws / "x.csv", "a,b,c,d,e\n1,2,3,4,true\n")
    res = run_ok("--output", "-", "--key", "a", "--schema", s, x)
    assert body(res.stdout) == ["1,2,3.0,4.0,true"]


# --- Spec: "datetime->timestamp, timestamptz->timestamp, text->string,
#           varchar->string" ---
# Context: Type Aliases; temporal and string aliases.
def test_builtin_temporal_and_string_aliases(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "integer"), ("a", "datetime"), ("b", "timestamptz"),
        ("c", "text"), ("d", "varchar")])
    x = write(ws / "x.csv",
              "id,a,b,c,d\n1,2024-01-01T00:00:00Z,2024-01-01 05:00:00+05:00,7,8\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s, x)
    assert body(res.stdout) == [
        "1,2024-01-01T00:00:00Z,2024-01-01T00:00:00Z,7,8"]


# --- Spec: "Case-insensitive aliases accepted anywhere type is expected" ---
# Context: Type Aliases; also applies to the canonical primitive names.
def test_alias_and_type_names_are_case_insensitive(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "INT"), ("a", "Integer"), ("b", "DOUBLE"), ("c", "Text")])
    x = write(ws / "x.csv", "id,a,b,c\n1,2,3,4\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s, x)
    assert body(res.stdout) == ["1,2,3.0,4"]


# --- Spec: "Case-insensitive aliases accepted anywhere type is expected" ---
# Context: Type Aliases; inside struct fields, array elements and map values.
def test_aliases_inside_nested_positions(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("u", struct_t(("n", "Long"), ("t", "DateTime"))),
        ("xs", array_t("double")),
        ("m", map_t("boolean")),
    ])
    a = write_jsonl(ws / "a.jsonl", [{
        "id": 1, "u": {"n": "5", "t": "2024-01-01T00:00:00+01:00"},
        "xs": [1, 2], "m": {"k": "true"}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == ['{"n":5,"t":"2023-12-31T23:00:00Z"}']
    assert col(res.stdout, "xs") == ["[1.0,2.0]"]
    assert col(res.stdout, "m") == ['{"k":true}']


# --- Spec: "`list<T>`->`array<T>`" ---
# Context: Type Aliases; built-in generic rewrite.
def test_list_alias_rewrites_to_array(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("xs", "list<int>")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [1, "2"]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "xs") == ["[1,2]"]


# --- Spec: "`list<T>`->`array<T>`" ---
# Context: Type Aliases; the object spelling of the same constructor.
def test_list_object_form_is_an_array(ws):
    s = write_json(ws / "s.json", {"columns": [
        {"name": "id", "type": "int"},
        {"name": "xs", "type": {"list": {"element": "int"}}}]})
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [3, 4]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "xs") == ["[3,4]"]


# --- Spec: "Case-insensitive aliases accepted anywhere type is expected" ---
# Context: Type Aliases; the string form of the generic types (T63).
def test_string_form_generic_types(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("xs", "array<int>"), ("m", "map<string,float>"),
        ("deep", "list<map<string,int>>")])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "xs": [1], "m": {"a": 2}, "deep": [{"k": 3}]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "xs") == ["[1]"]
    assert col(res.stdout, "m") == ['{"a":2.0}']
    assert col(res.stdout, "deep") == ['[{"k":3}]']


# --- Spec: "Optional alias file via `--type-alias-file <ALIASES_JSON>`:
#           {"aliases": {"smallint": "int", "decimal": "float",
#            "uuid": "string", "myts": "timestamp"}}" ---
# Context: Type Aliases; the spec's own alias file, verbatim.
def test_alias_file_from_the_spec_example(ws):
    al = write_aliases(ws / "al.json", {"smallint": "int", "decimal": "float",
                                        "uuid": "string", "myts": "timestamp"})
    s = write_nested_schema(ws / "s.json", [
        ("id", "smallint"), ("amt", "decimal"), ("u", "uuid"), ("t", "myts")])
    x = write(ws / "x.csv", "id,amt,u,t\n1,2.5,abc,2024-01-01 00:00:00Z\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--type-alias-file", al, x)
    assert body(res.stdout) == ["1,2.5,abc,2024-01-01T00:00:00Z"]


# --- Spec: "Aliases apply after lowercasing names" ---
# Context: Type Aliases; a mixed-case use of a lower-case alias entry.
def test_alias_file_lookup_is_after_lowercasing(ws):
    al = write_aliases(ws / "al.json", {"smallint": "int"})
    s = write_nested_schema(ws / "s.json", [("id", "SmallInt")])
    x = write(ws / "x.csv", "id\n7\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--type-alias-file", al, x)
    assert body(res.stdout) == ["7"]


# --- Spec: "May refer to built-ins or other aliases (resolve transitively)" ---
# Context: Type Aliases; a chain ending at a built-in alias.
def test_alias_chains_resolve_transitively(ws):
    al = write_aliases(ws / "al.json", {"a": "b", "b": "c", "c": "integer"})
    s = write_nested_schema(ws / "s.json", [("id", "a")])
    x = write(ws / "x.csv", "id\n9\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--type-alias-file", al, x)
    assert body(res.stdout) == ["9"]


# --- Spec: "detect cycles -> error 2" ---
# Context: Type Aliases; a two-step cycle.
def test_alias_cycle_is_error_2(ws):
    al = write_aliases(ws / "al.json", {"a": "b", "b": "a"})
    s = write_nested_schema(ws / "s.json", [("id", "a")])
    x = write(ws / "x.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--type-alias-file", al, x)
    assert res.returncode == 2
    assert res.stderr != ""


# --- Spec: "detect cycles -> error 2" ---
# Context: Type Aliases; a self-referential alias.
def test_self_referential_alias_is_error_2(ws):
    al = write_aliases(ws / "al.json", {"loop": "loop"})
    s = write_nested_schema(ws / "s.json", [("id", "int")])
    x = write(ws / "x.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--type-alias-file", al, x)
    assert res.returncode == 2


# --- Spec: "May refer to built-ins or other aliases" ---
# Context: Type Aliases; an alias whose target is a generic type (T63).
def test_alias_target_may_be_a_generic_type(ws):
    al = write_aliases(ws / "al.json", {"ints": "list<smallint>",
                                        "smallint": "int"})
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("xs", "ints")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": ["4", 5]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--type-alias-file", al, a)
    assert col(res.stdout, "xs") == ["[4,5]"]


# --- Spec: "Special alias `json`: when field declared as `"type":"json"`,
#           accept any JSON value (object/array/primitive) and emit as JSON
#           text" ---
# Context: Type Aliases; one column, four different JSON shapes.
def test_json_type_accepts_any_json_value(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("v", "json")])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "v": {"a": [1, 2]}},
        {"id": 2, "v": [1, "two", True]},
        {"id": 3, "v": "plain"},
        {"id": 4, "v": 7},
    ])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == ['{"a":[1,2]}', '[1,"two",true]',
                                    '"plain"', "7"]


# --- Spec: "For `json` type: accept any JSON value without casting" ---
# Context: Casting & Validation; nothing is coerced, strings stay strings.
def test_json_type_does_not_cast_values(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("v", "json")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": {"n": "0012",
                                                     "t": "2024-01-01 05:00:00+05:00"}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "v") == [
        '{"n":"0012","t":"2024-01-01 05:00:00+05:00"}']


# --- Spec: "`json`->`struct` (accept any JSON, see below)" ---
# Context: Type Aliases; json is a nested kind, so it cannot be a key (T80).
def test_json_column_is_not_a_primitive_for_keys(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("v", "json")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": 3}])
    res = run("--output", "-", "--key", "v", "--schema", s, a)
    assert res.returncode == 3
    assert "ERR 3" in res.stderr


# --- Spec: "unknown types error deterministically" ---
# Context: Determinism Checklist; an alias file that never defines the name.
def test_unknown_type_name_errors(ws):
    s = write_nested_schema(ws / "s.json", [("id", "nosuchtype")])
    x = write(ws / "x.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--schema", s, x)
    assert res.returncode != 0
    assert res.stderr != ""


# --- Spec: "Optional alias file" ---
# Context: Type Aliases; a user entry may shadow a built-in alias (T69).
def test_user_alias_overrides_a_builtin_alias(ws):
    al = write_aliases(ws / "al.json", {"number": "string"})
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("v", "number")])
    x = write(ws / "x.csv", "id,v\n1,007\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--type-alias-file", al, x)
    assert body(res.stdout) == ["1,007"]
