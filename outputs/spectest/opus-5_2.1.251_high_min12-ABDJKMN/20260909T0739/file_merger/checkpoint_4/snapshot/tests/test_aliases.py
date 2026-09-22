"""Checkpoint 5: type aliases (built-in and from --type-alias-file)."""
import pytest

from conftest import (alias_file, array_of, cell, map_of, merge, merge_paths,
                      nested_schema, struct_of, write, write_jsonl)


# --- Spec: built-in aliases "integer->int, long->int, double->float,
#            number->float, boolean->bool" ------------------------------------
@pytest.mark.parametrize("alias,text,expected", [
    ("integer", "7", "7"),
    ("long", "7", "7"),
    ("double", "2.5", "2.5"),
    ("number", "2.5", "2.5"),
    ("boolean", "true", "true"),
])
def test_builtin_numeric_and_bool_aliases(tmp_path, alias, text, expected):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", alias)])
    files = {"a.csv": f"id,v\n1,{text}\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "v") == expected


# --- Spec: built-in aliases "datetime->timestamp, timestamptz->timestamp" ----
@pytest.mark.parametrize("alias", ["datetime", "timestamptz"])
def test_builtin_timestamp_aliases_normalize_to_utc(tmp_path, alias):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", alias)])
    files = {"a.csv": "id,v\n1,2024-03-01T12:00:00+02:00\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "v") == "2024-03-01T10:00:00Z"


# --- Spec: built-in aliases "text->string, varchar->string" -----------------
@pytest.mark.parametrize("alias", ["text", "varchar"])
def test_builtin_string_aliases(tmp_path, alias):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", alias)])
    files = {"a.csv": "id,v\n1,00123\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "v") == "00123"


# --- Spec: built-in alias "list<T> -> array<T>" ----------------------------
def test_list_generic_alias(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("xs", "list<int>")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [1, 2]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[1,2]"


def test_list_alias_inside_object_form(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("m", map_of("list<int>"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {"a": [1]}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "m") == '{"a":[1]}'


# --- Spec: "Case-insensitive aliases accepted anywhere type is expected" ----
@pytest.mark.parametrize("declared", ["INT", "Integer", "InT", "LONG"])
def test_type_names_are_case_insensitive(tmp_path, declared):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", declared)])
    files = {"a.csv": "id,v\n1,7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "v") == "7"


def test_case_insensitive_inside_nested_type(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("n", "TEXT"), ("a", "Integer"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"n": "x", "a": 4}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"n":"x","a":4}'


def test_case_insensitive_generic_alias(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("xs", "List<Double>")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [1]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[1.0]"


# --- Spec: "Optional alias file via --type-alias-file <ALIASES_JSON>" ------
def test_alias_file_from_the_spec(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {
        "smallint": "int", "decimal": "float", "uuid": "string", "myts": "timestamp",
    })
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "smallint"), ("amt", "decimal"), ("u", "uuid"), ("t", "myts"),
    ])
    files = {"a.csv": "id,amt,u,t\n1,2.50,ab-cd,2024-05-06T00:00:00Z\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    assert r.ok, r
    assert r.rows()[1] == ["1", "2.5", "ab-cd", "2024-05-06T00:00:00Z"]


# --- Spec: "Aliases apply after lowercasing names" ------------------------
def test_alias_lookup_is_case_insensitive(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {"smallint": "int"})
    schema = nested_schema(tmp_path, "s.json", [("id", "SmallInt")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    assert r.ok, r
    assert cell(r, 0, "id") == "7"


def test_alias_key_is_lowercased_too(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {"SmallInt": "int"})
    schema = nested_schema(tmp_path, "s.json", [("id", "smallint")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    assert r.ok, r


# --- Spec: "May refer to built-ins or other aliases (resolve transitively)" --
def test_alias_chain_resolves_transitively(tmp_path):
    aliases = alias_file(tmp_path, "al.json",
                         {"a": "b", "b": "c", "c": "integer"})
    schema = nested_schema(tmp_path, "s.json", [("id", "a")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    assert r.ok, r
    assert cell(r, 0, "id") == "7"


def test_alias_can_name_a_nested_type(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {"tags": "list<uuid>", "uuid": "string"})
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("xs", "tags")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": ["a", "b"]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--type-alias-file", str(aliases))
    assert r.ok, r
    assert cell(r, 0, "xs") == '["a","b"]'


# --- Spec: "detect cycles -> error 2" -------------------------------------
def test_alias_cycle_is_error_2(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {"a": "b", "b": "a"})
    schema = nested_schema(tmp_path, "s.json", [("id", "a")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    assert r.returncode == 2, r
    assert r.stderr.strip()


def test_self_referential_alias_is_error_2(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {"a": "a"})
    schema = nested_schema(tmp_path, "s.json", [("id", "int")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    # AMBIGUITIES T55: cycles are detected eagerly, even when unused.
    assert r.returncode == 2, r


# --- Spec: alias file problems (AMBIGUITIES T54) --------------------------
def test_missing_alias_file_is_error_2(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(tmp_path / "nope.json"))
    assert r.returncode == 2, r


def test_malformed_alias_file_is_error_2(tmp_path):
    bad = write(tmp_path, "al.json", "{not json")
    schema = nested_schema(tmp_path, "s.json", [("id", "int")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(bad))
    assert r.returncode == 2, r


# --- Spec: "Built-in aliases (always present)" ----------------------------
def test_builtins_survive_a_custom_alias_file(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {"smallint": "int"})
    schema = nested_schema(tmp_path, "s.json", [("id", "integer")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    assert r.ok, r


# --- Spec: an alias target that is not a known type errors ----------------
def test_alias_to_unknown_type_is_a_schema_error(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {"weird": "widget"})
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "weird")])
    files = {"a.csv": "id,v\n1,x\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    assert r.returncode == 3, r


# --- Spec: "json->struct (accept any JSON)" -------------------------------
def test_json_alias_and_struct_string_behave_alike(tmp_path):
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": {"b": 1, "a": [1, "x"]}}])
    out = []
    for declared in ("json", "struct", "JSON"):
        schema = nested_schema(tmp_path, f"s-{declared}.json",
                               [("id", "int"), ("v", declared)])
        r = merge_paths([src], "--key", "id", "--schema", str(schema))
        assert r.ok, (declared, r)
        out.append(cell(r, 0, "v"))
    assert out[0] == out[1] == out[2]


# --- Spec: "--type-alias-file" is optional --------------------------------
def test_alias_file_is_optional(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "integer")])
    files = {"a.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r


# --- Spec: a user alias may override how a name resolves ------------------
def test_user_alias_may_shadow_a_builtin_alias(tmp_path):
    aliases = alias_file(tmp_path, "al.json", {"number": "string"})
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "number")])
    files = {"a.csv": "id,v\n1,007\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--type-alias-file", str(aliases))
    assert r.ok, r
    assert cell(r, 0, "v") == "007"
