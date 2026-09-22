"""Spec section: Type Aliases — built-ins, --type-alias-file, case and cycles."""

from conftest import column, rows_of
from nested_helpers import INT, array, write_aliases, write_schema


BUILT_INS = {
    "integer": ("7", "7"),
    "long": ("7", "7"),
    "double": ("2.5", "2.5"),
    "number": ("2.5", "2.5"),
    "boolean": ("1", "true"),
    "datetime": ("2024-07-01T00:00:00+01:00", "2024-06-30T23:00:00Z"),
    "timestamptz": ("2024-07-01T00:00:00+01:00", "2024-06-30T23:00:00Z"),
    "text": ("hi", "hi"),
    "varchar": ("hi", "hi"),
}


def run_typed(csv_file, run_tool, declared, cell, *extra):
    """Cast one cell through a column declared with `declared`."""
    write_schema(csv_file, [INT, {"name": "v", "type": declared}])
    csv_file("a.csv", f"id,v\n1,{cell}\n")
    return run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", *extra, "a.csv",
    )


# Phrase: "Built-in aliases (always present)"
# Context: Type Aliases. Each documented alias names its primitive.
def test_every_built_in_alias_resolves(csv_file, run_tool):
    for alias, (cell, expected) in BUILT_INS.items():
        result = run_typed(csv_file, run_tool, alias, cell)
        assert result.returncode == 0, (alias, result.stderr)
        assert column(result.stdout, "v") == [expected], alias


# Phrase: "Case-insensitive aliases accepted anywhere type is expected"
# Context: Type Aliases. Both alias and primitive names ignore case, nested too.
def test_type_names_are_case_insensitive(jsonl_file, run_tool):
    write_schema(
        jsonl_file,
        [
            {"name": "id", "type": "Integer"},
            {"name": "xs", "type": {"ARRAY": {"element": "LONG"}}},
            {"name": "t", "type": "List<DateTime>"},
        ],
    )
    jsonl_file("a.jsonl", [{"id": 1, "xs": [2], "t": ["2024-07-01T00:00:00Z"]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1", "[2]", '["2024-07-01T00:00:00Z"]']]


# Phrase: "list<T> -> array<T>"
# Context: Built-in aliases. The parameterised alias keeps its element type.
def test_list_alias_is_an_array(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": "list<int>"}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": ["1", 2]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ["[1,2]"]


# Phrase: "json -> struct (accept any JSON, see below)"
# Context: Built-in aliases. Objects, arrays and primitives all pass through.
def test_json_alias_accepts_any_json(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "p", "type": "json"}])
    jsonl_file(
        "a.jsonl",
        [
            {"id": 1, "p": {"b": 1, "a": [1, "x", None]}},
            {"id": 2, "p": [1, 2]},
            {"id": 3, "p": "text"},
            {"id": 4, "p": 5},
            {"id": 5, "p": True},
        ],
    )
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "p") == [
        '{"a":[1,"x",null],"b":1}',
        "[1,2]",
        '"text"',
        "5",
        "true",
    ]


# Phrase: "Optional alias file via --type-alias-file <ALIASES_JSON>"
# Context: Type Aliases. The documented alias file drives four columns.
def test_alias_file_from_the_spec(csv_file, run_tool):
    write_aliases(
        csv_file,
        {"smallint": "int", "decimal": "float", "uuid": "string", "myts": "timestamp"},
    )
    write_schema(
        csv_file,
        [
            {"name": "id", "type": "smallint"},
            {"name": "amount", "type": "decimal"},
            {"name": "key", "type": "uuid"},
            {"name": "seen", "type": "myts"},
        ],
    )
    csv_file("a.csv", "id,amount,key,seen\n1,2.50,ab,2024-07-01 00:00:00\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--type-alias-file", "aliases.json", "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1", "2.5", "ab", "2024-07-01T00:00:00Z"]]


# Phrase: "Aliases apply after lowercasing names"
# Context: Type Aliases. A mixed-case reference finds a lower-case alias.
def test_alias_lookup_lowercases_the_name(csv_file, run_tool):
    write_aliases(csv_file, {"smallint": "int"})
    result = run_typed(
        csv_file, run_tool, "SmallInt", "7", "--type-alias-file", "aliases.json"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == ["7"]


# Phrase: "May refer to built-ins or other aliases (resolve transitively)"
# Context: Type Aliases. A chain of three hops ends at a primitive.
def test_aliases_resolve_transitively(csv_file, run_tool):
    write_aliases(csv_file, {"a": "b", "b": "smallint", "smallint": "integer"})
    result = run_typed(csv_file, run_tool, "a", "7", "--type-alias-file", "aliases.json")
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == ["7"]


# Phrase: "May refer to built-ins or other aliases"
# Context: Type Aliases. An alias may name a parameterised nested type.
def test_alias_may_name_a_nested_type(jsonl_file, run_tool):
    write_aliases(jsonl_file, {"ints": "list<integer>"})
    write_schema(jsonl_file, [INT, {"name": "xs", "type": "ints"}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": [1, 2]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--type-alias-file", "aliases.json", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ["[1,2]"]


# Phrase: "detect cycles proactively -> error 2"
# Context: Type Aliases. The cycle is reported even though no column uses it.
def test_alias_cycle_is_error_2(csv_file, run_tool):
    write_aliases(csv_file, {"a": "b", "b": "a"})
    write_schema(csv_file, [INT])
    csv_file("a.csv", "id\n1\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--type-alias-file", "aliases.json", "a.csv",
    )
    assert result.returncode == 2
    assert result.stderr


# Phrase: "detect cycles proactively -> error 2"
# Context: Type Aliases. An alias that names itself is a cycle of length one.
def test_self_referential_alias_is_error_2(csv_file, run_tool):
    write_aliases(csv_file, {"loop": "loop"})
    write_schema(csv_file, [INT])
    csv_file("a.csv", "id\n1\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--type-alias-file", "aliases.json", "a.csv",
    )
    assert result.returncode == 2
    assert result.stderr


# Phrase: "Optional alias file via --type-alias-file <ALIASES_JSON>"
# Context: Type Aliases. Ambiguity T48: an unusable alias file is error 2.
def test_unreadable_alias_file_is_error_2(csv_file, run_tool):
    write_schema(csv_file, [INT])
    csv_file("a.csv", "id\n1\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--type-alias-file", "missing.json", "a.csv",
    )
    assert result.returncode == 2
    assert result.stderr


# Phrase: "Aliases ... may refer to built-ins"
# Context: Type Aliases. Ambiguity T49: a file alias overrides the built-in name.
def test_file_alias_overrides_a_built_in(csv_file, run_tool):
    write_aliases(csv_file, {"number": "int"})
    result = run_typed(
        csv_file, run_tool, "number", "7", "--type-alias-file", "aliases.json"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == ["7"]


# Phrase: "Case-insensitive aliases accepted anywhere type is expected"
# Context: Type Aliases. Aliases also work inside a nested declaration.
def test_aliases_work_inside_nested_declarations(jsonl_file, run_tool):
    write_aliases(jsonl_file, {"smallint": "int"})
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("smallint")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": ["3"]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--type-alias-file", "aliases.json", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ["[3]"]
