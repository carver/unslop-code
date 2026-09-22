"""Type aliases: the built-in table, --type-alias-file, and their resolution rules."""

from conftest import array, cell, rows_of, struct


def _aliased(run, make_jsonl, make_schema, declared, value, *extra):
    """Run one row through a column declared as ``declared`` and return its cell."""
    make_jsonl("a.jsonl", [{"id": 1, "v": value}])
    make_schema("s.json", [("id", "int"), ("v", declared)])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", *extra, "a.jsonl")
    return cell(rows_of(proc.stdout), "v")


# Spec: "`integer`->`int`, `long`->`int`, `double`->`float`, `number`->`float`,
# `boolean`->`bool`"
def test_builtin_numeric_and_bool_aliases(run, make_jsonl, make_schema):
    assert _aliased(run, make_jsonl, make_schema, "integer", "7") == "7"
    assert _aliased(run, make_jsonl, make_schema, "long", "7") == "7"
    assert _aliased(run, make_jsonl, make_schema, "double", "1.50") == "1.5"
    assert _aliased(run, make_jsonl, make_schema, "number", "1.50") == "1.5"
    assert _aliased(run, make_jsonl, make_schema, "boolean", "1") == "true"


# Spec: "`datetime`->`timestamp`, `timestamptz`->`timestamp`, `text`->`string`,
# `varchar`->`string`"
def test_builtin_temporal_and_text_aliases(run, make_jsonl, make_schema):
    assert _aliased(run, make_jsonl, make_schema, "datetime", "2024-07-01T12:00:00+02:00") == "2024-07-01T10:00:00Z"
    assert _aliased(run, make_jsonl, make_schema, "timestamptz", "2024-07-01 00:00") == "2024-07-01T00:00:00Z"
    assert _aliased(run, make_jsonl, make_schema, "text", 12) == "12"
    assert _aliased(run, make_jsonl, make_schema, "varchar", "x") == "x"


# Spec: "Case-insensitive aliases accepted anywhere type is expected"
def test_aliases_and_type_names_are_case_insensitive(run, make_jsonl, make_schema):
    assert _aliased(run, make_jsonl, make_schema, "INT", "7") == "7"
    assert _aliased(run, make_jsonl, make_schema, "Integer", "7") == "7"
    assert _aliased(run, make_jsonl, make_schema, "TimeStampTZ", "2024-07-01 00:00") == "2024-07-01T00:00:00Z"


# Spec: "Case-insensitive aliases accepted anywhere type is expected"
# Context: "anywhere" includes the element type of an array and a struct field.
def test_aliases_are_accepted_inside_nested_declarations(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "ns": ["1", "2"], "user": {"age": "30"}}])
    make_schema("s.json", [("id", "int"), ("ns", array("LONG")), ("user", struct(("age", "integer")))])
    rows = rows_of(run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl").stdout)
    assert cell(rows, "ns") == "[1,2]"
    assert cell(rows, "user") == '{"age":30}'


# Spec: "`list<T>`->`array<T>`"
def test_list_is_an_alias_for_array(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "ns": [1, 2]}])
    make_schema("s.json", [("id", "int"), ("ns", "list<int>")])
    assert cell(rows_of(run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl").stdout), "ns") == "[1,2]"


# Spec: "`json`->`struct` (accept any JSON, see below)" and "when field declared
# as `"type":"json"`, accept any JSON value (object/array/primitive)"
def test_json_type_accepts_any_json_value(run, make_jsonl, make_schema):
    assert _aliased(run, make_jsonl, make_schema, "json", {"b": 1, "a": [2, "x"]}) == '{"a":[2,"x"],"b":1}'
    assert _aliased(run, make_jsonl, make_schema, "json", [1, "a", None]) == '[1,"a",null]'
    assert _aliased(run, make_jsonl, make_schema, "json", "plain") == '"plain"'
    assert _aliased(run, make_jsonl, make_schema, "json", 5) == "5"
    assert _aliased(run, make_jsonl, make_schema, "json", True) == "true"


# Spec: "Optional alias file via `--type-alias-file <ALIASES_JSON>`" with the
# spec's own example aliases.
def test_alias_file_entries_are_accepted(make_jsonl, make_schema, make_json, run):
    make_jsonl("a.jsonl", [{"id": 1, "n": "7", "d": "1.50", "u": "abc", "t": "2024-07-01 00:00"}])
    make_schema(
        "s.json",
        [("id", "int"), ("n", "smallint"), ("d", "decimal"), ("u", "uuid"), ("t", "myts")],
    )
    make_json("al.json", {"aliases": {"smallint": "int", "decimal": "float", "uuid": "string", "myts": "timestamp"}})
    rows = rows_of(
        run(
            "--output", "-", "--key", "id", "--schema", "s.json",
            "--type-alias-file", "al.json", "a.jsonl",
        ).stdout
    )
    assert [cell(rows, name) for name in ("n", "d", "u", "t")] == ["7", "1.5", "abc", "2024-07-01T00:00:00Z"]


# Spec: "Aliases apply after lowercasing names"
def test_alias_names_match_case_insensitively(make_jsonl, make_schema, make_json, run):
    make_jsonl("a.jsonl", [{"id": 1, "n": "7"}])
    make_schema("s.json", [("id", "int"), ("n", "SmallInt")])
    make_json("al.json", {"aliases": {"SMALLINT": "INT"}})
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--type-alias-file", "al.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "n") == "7"


# Spec: "May refer to built-ins or other aliases (resolve transitively ...)"
def test_aliases_resolve_transitively(make_jsonl, make_schema, make_json, run):
    make_jsonl("a.jsonl", [{"id": 1, "n": "7"}])
    make_schema("s.json", [("id", "int"), ("n", "tiny")])
    make_json("al.json", {"aliases": {"tiny": "smallint", "smallint": "integer"}})
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--type-alias-file", "al.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "n") == "7"


# Spec: "detect cycles proactively -> error 2"
def test_alias_cycles_exit_two(make_jsonl, make_schema, make_json, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    make_schema("s.json", [("id", "int")])
    make_json("al.json", {"aliases": {"a": "b", "b": "a"}})
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--type-alias-file", "al.json", "a.jsonl", expect_ok=False,
    )
    assert proc.returncode == 2


# Spec: "detect cycles proactively -> error 2"
# Context: proactively means before any input is read, so a cycle the schema
# never mentions is still an error.
def test_alias_cycle_is_detected_even_when_unused(make_jsonl, make_schema, make_json, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    make_schema("s.json", [("id", "int")])
    make_json("al.json", {"aliases": {"loop": "loop"}})
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json",
        "--type-alias-file", "al.json", "a.jsonl", expect_ok=False,
    )
    assert proc.returncode == 2


# Spec: "May refer to built-ins or other aliases"
# Context: see AMBIGUITIES T50 - a primitive's own name always wins, so an alias
# cannot redefine `int`.
def test_an_alias_cannot_redefine_a_primitive(make_jsonl, make_schema, make_json, run):
    make_jsonl("a.jsonl", [{"id": 1, "n": "7"}])
    make_schema("s.json", [("id", "int"), ("n", "int")])
    make_json("al.json", {"aliases": {"int": "string"}})
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--type-alias-file", "al.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "n") == "7"


# Spec: "Aliases apply after lowercasing names" - an alias may name a nested type.
# Context: see AMBIGUITIES T51.
def test_an_alias_may_name_a_generic_type(make_jsonl, make_schema, make_json, run):
    make_jsonl("a.jsonl", [{"id": 1, "ns": [1, 2]}])
    make_schema("s.json", [("id", "int"), ("ns", "ints")])
    make_json("al.json", {"aliases": {"ints": "list<integer>"}})
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--type-alias-file", "al.json", "a.jsonl")
    assert cell(rows_of(proc.stdout), "ns") == "[1,2]"
