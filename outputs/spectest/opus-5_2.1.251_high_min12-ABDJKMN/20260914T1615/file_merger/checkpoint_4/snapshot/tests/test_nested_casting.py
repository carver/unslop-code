"""Spec section: Nested Types Support — "Casting & Validation"."""

from conftest import (array_t, body, col, map_t, run, run_ok, struct_t, write,
                      write_jsonl, write_nested_schema)


# --- Spec: "Nested values cast recursively to declared types" ---
# Context: Casting & Validation; text leaves parse into their declared types.
def test_nested_values_cast_recursively(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("u", struct_t(("n", "int"), ("f", "float"), ("b", "bool"),
                       ("d", "date"), ("t", "timestamp"), ("s", "string"))),
    ])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {
        "n": "12", "f": "1.5", "b": "true", "d": "2024-02-03",
        "t": "2024-02-03 01:00:00+01:00", "s": 9}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == [
        '{"n":12,"f":1.5,"b":true,"d":"2024-02-03",'
        '"t":"2024-02-03T00:00:00Z","s":"9"}']


# --- Spec: "`coerce-null`: set field/element to JSON `null`" ---
# Context: Casting & Validation; only the failing field is nulled (T83).
def test_coerce_null_nulls_only_the_failing_field(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"), ("b", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": "xx", "b": 2}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "coerce-null", a)
    assert col(res.stdout, "u") == ['{"a":null,"b":2}']


# --- Spec: "`coerce-null`: set field/element to JSON `null`" ---
# Context: Casting & Validation; array elements too.
def test_coerce_null_on_array_elements(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [1, "no", 3]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "xs") == ["[1,null,3]"]


# --- Spec: "`keep-string`: set to original unparsed JSON string or
#           stringified form" ---
# Context: Casting & Validation; a failing leaf keeps its text (T73).
def test_keep_string_inside_nested(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"), ("b", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": "xx", "b": 2}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "keep-string", a)
    assert col(res.stdout, "u") == ['{"a":"xx","b":2}']


# --- Spec: "keep-string: set to original unparsed JSON string or stringified
#           form" ---
# Context: Casting & Validation; a nested value in a primitive slot (T73).
def test_keep_string_stringifies_a_nested_value(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": {"k": 1}}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "keep-string", a)
    assert col(res.stdout, "u") == ['{"a":"{\\"k\\":1}"}']


# --- Spec: "`fail`: emit `ERR 4 cannot cast "<val>" to <type> in field
#           "<path>" (file=... line=...)`" ---
# Context: Casting & Validation; the path of an array element (T62).
def test_fail_reports_the_array_element_path(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [1, "no"]}])
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--on-type-error", "fail", a)
    assert res.returncode == 4
    assert 'in field "xs.1"' in res.stderr


# --- Spec: "`fail`: emit `ERR 4 ... in field "<path>" ...`" ---
# Context: Casting & Validation; the path of a map value.
def test_fail_reports_the_map_key_path(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("m", map_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "m": {"k": "bad"}}])
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--on-type-error", "fail", a)
    assert res.returncode == 4
    assert 'm["k"]' in res.stderr


# --- Spec: "All struct fields included (even when null) with explicit `null`
#           values" ---
# Context: Normalization & Output Encoding; a missing field is explicit null.
def test_missing_struct_field_is_explicit_null(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"), ("b", "string")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == ['{"a":1,"b":null}']


# --- Spec: "**struct**: ordered list of named fields" ---
# Context: Casting & Validation; input keys the struct does not declare (T74).
def test_undeclared_struct_keys_are_dropped(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1, "zz": 9}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == ['{"a":1}']


# --- Spec: "Primitive casting rules, temporal normalization, null handling
#           apply recursively inside nested values" ---
# Context: Casting & Validation; explicit JSON null stays null everywhere.
def test_explicit_nulls_inside_nested_values(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("u", struct_t(("a", "int"))), ("xs", array_t("int")),
        ("m", map_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "u": {"a": None}, "xs": [1, None], "m": {"k": None}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == ['{"a":null}']
    assert col(res.stdout, "xs") == ["[1,null]"]
    assert col(res.stdout, "m") == ['{"k":null}']


# --- Spec: "Primitive casting rules ... apply recursively inside nested
#           values" ---
# Context: Casting & Validation; an empty string is a null only for text input.
def test_empty_string_inside_nested_json_is_a_cast_failure(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": ""}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == ['{"a":null}']


# --- Spec: "On cast failure within nested structures ... `coerce-null`" ---
# Context: Casting & Validation; a non-object where a struct is declared (T74).
def test_non_object_for_a_struct_nulls_the_whole_node(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": 5}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--csv-null-literal", "NA", a)
    assert body(res.stdout) == ["1,NA"]


# --- Spec: "On cast failure within nested structures ... `fail`" ---
# Context: Casting & Validation; the first failure aborts the whole run.
def test_fail_aborts_with_exit_4(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("date"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": ["2024-01-01"]},
                                     {"id": 2, "xs": ["nope"]}])
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--on-type-error", "fail", a)
    assert res.returncode == 4


# --- Spec: "For `json` type: accept any JSON value without casting" ---
# Context: Casting & Validation; --on-type-error never fires for json.
def test_json_type_never_fails_casting(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"), ("v", "json")])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": {"a": "not-a-number"}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s,
                 "--on-type-error", "fail", a)
    assert col(res.stdout, "v") == ['{"a":"not-a-number"}']


# --- Spec: "Nested values cast recursively to declared types" ---
# Context: Casting & Validation; nesting several levels deep.
def test_recursive_cast_three_levels_deep(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("a", array_t(struct_t(("m", map_t(array_t("int"))))))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "a": [{"m": {"z": ["1", 2], "y": []}}]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "a") == ['[{"m":{"y":[],"z":[1,2]}}]']
