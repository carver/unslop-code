"""Spec section: Type Aliases."""
import json

import pytest

from conftest import body


def schema_file(work, name, columns):
    return work.write(
        name, json.dumps({"columns": [{"name": n, "type": t} for n, t in columns]})
    )


def alias_file(work, name, aliases):
    return work.write(name, json.dumps({"aliases": aliases}))


# Phrase: "Built-in aliases (always present): integer→int, long→int, double→float,
#          number→float, boolean→bool, datetime→timestamp, timestamptz→timestamp,
#          text→string, varchar→string"
# Context: Type Aliases.
@pytest.mark.parametrize(
    "alias,value,expected",
    [
        ("integer", "0007", "7"),
        ("long", "0007", "7"),
        ("double", "2.50", "2.5"),
        ("number", "2.50", "2.5"),
        ("boolean", "1", "true"),
        ("datetime", "2024-01-02T03:04:05+02:00", "2024-01-02T01:04:05Z"),
        ("timestamptz", "2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ("text", "0007", "0007"),
        ("varchar", "0007", "0007"),
    ],
)
def test_builtin_primitive_aliases(run, work, alias, value, expected):
    schema_file(work, "s.json", [("id", "int"), ("v", alias)])
    work.csv("a.csv", ["id", "v"], [["1", value]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", expected]]


# Phrase: "Case-insensitive aliases accepted anywhere type is expected"
# Context: Type Aliases.
def test_aliases_are_case_insensitive(run, work):
    schema_file(work, "s.json", [("id", "INTEGER"), ("v", "Text")])
    work.csv("a.csv", ["id", "v"], [["1", "x"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "x"]]


def test_core_type_names_are_case_insensitive_too(run, work):
    schema_file(work, "s.json", [("id", "INT"), ("v", "STRING")])
    work.csv("a.csv", ["id", "v"], [["1", "x"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "x"]]


# Phrase: "list<T>→array<T>"
# Context: Type Aliases; the alias is written as a generic type string.
def test_list_alias_is_array(run, work):
    schema_file(work, "s.json", [("id", "int"), ("xs", "list<int>")])
    work.jsonl("a.jsonl", [{"id": 1, "xs": [2, 1]}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "[2,1]"]]


def test_array_type_string_spelling(run, work):
    schema_file(work, "s.json", [("id", "int"), ("xs", "array<string>")])
    work.jsonl("a.jsonl", [{"id": 1, "xs": ["b", "a"]}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '["b","a"]']]


def test_map_type_string_spelling(run, work):
    schema_file(work, "s.json", [("id", "int"), ("m", "map<string,int>")])
    work.jsonl("a.jsonl", [{"id": 1, "m": {"b": 2, "a": 1}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"a":1,"b":2}']]


# Phrase: "json→struct (accept any JSON ...)"
# Phrase: "Special alias `json`: when field declared as "type":"json", accept any
#          JSON value (object/array/primitive) and emit as JSON text"
# Context: Type Aliases.
@pytest.mark.parametrize(
    "value,expected",
    [
        ({"b": 1, "a": 2}, '{"a":2,"b":1}'),
        ([1, "x", None], '[1,"x",null]'),
        ("text", '"text"'),
        (12, "12"),
        (True, "true"),
    ],
)
def test_json_type_accepts_any_json_value(run, work, value, expected):
    schema_file(work, "s.json", [("id", "int"), ("v", "json")])
    work.jsonl("a.jsonl", [{"id": 1, "v": value}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", expected]]


# Phrase: "For `json` type: accept any JSON value without casting; normalize only"
# Context: Casting & Validation; a date-looking string stays a string, no cast.
def test_json_type_does_not_cast_values(run, work):
    schema_file(work, "s.json", [("id", "int"), ("v", "json")])
    work.jsonl(
        "a.jsonl", [{"id": 1, "v": {"t": "2024-01-02T03:04:05+02:00", "n": 1.5}}]
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"n":1.5,"t":"2024-01-02T03:04:05+02:00"}']]


# Phrase: "Optional alias file via --type-alias-file <ALIASES_JSON>"
# Context: Type Aliases.
def test_alias_file_entries(run, work):
    alias_file(
        work,
        "al.json",
        {"smallint": "int", "decimal": "float", "uuid": "string", "myts": "timestamp"},
    )
    schema_file(
        work,
        "s.json",
        [("id", "smallint"), ("d", "decimal"), ("u", "uuid"), ("t", "myts")],
    )
    work.csv(
        "a.csv",
        ["id", "d", "u", "t"],
        [["1", "2.50", "abc", "2024-01-02 03:04:05"]],
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("al.json"), work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "2.5", "abc", "2024-01-02T03:04:05Z"]]


# Phrase: "Aliases apply after lowercasing names"
# Context: Type Aliases; the alias file key matches whatever case the schema uses.
def test_alias_file_lookup_is_case_insensitive(run, work):
    alias_file(work, "al.json", {"SmallInt": "int"})
    schema_file(work, "s.json", [("id", "SMALLINT")])
    work.csv("a.csv", ["id"], [["3"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("al.json"), work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["3"]]


# Phrase: "May refer to built-ins or other aliases (resolve transitively ...)"
# Context: Type Aliases.
def test_aliases_resolve_transitively(run, work):
    alias_file(work, "al.json", {"a": "b", "b": "bigint", "bigint": "long"})
    schema_file(work, "s.json", [("id", "a")])
    work.csv("a.csv", ["id"], [["0042"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("al.json"), work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["42"]]


def test_alias_may_target_a_nested_type(run, work):
    alias_file(work, "al.json", {"tags": "list<text>"})
    schema_file(work, "s.json", [("id", "int"), ("t", "tags")])
    work.jsonl("a.jsonl", [{"id": 1, "t": ["b", "a"]}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("al.json"), work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '["b","a"]']]


# Phrase: "detect cycles proactively → error 2"
# Context: Type Aliases; the cycle is reported even though nothing uses it.
def test_alias_cycle_exits_2(run, work):
    alias_file(work, "al.json", {"a": "b", "b": "a"})
    schema_file(work, "s.json", [("id", "int")])
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("al.json"), work.path("a.csv"),
    )
    assert r.returncode == 2
    assert r.stdout == ""


def test_self_referential_alias_exits_2(run, work):
    alias_file(work, "al.json", {"loop": "loop"})
    schema_file(work, "s.json", [("id", "int")])
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("al.json"), work.path("a.csv"),
    )
    assert r.returncode == 2
    assert r.stdout == ""


# Phrase: "unknown types error deterministically"
# Context: Determinism Checklist; an alias pointing at nothing known.
def test_alias_to_unknown_type_exits_3(run, work):
    alias_file(work, "al.json", {"weird": "blob"})
    schema_file(work, "s.json", [("id", "weird")])
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("al.json"), work.path("a.csv"),
    )
    assert r.returncode == 3
    assert r.stdout == ""


# Phrase: "--type-alias-file <ALIASES_JSON>"
# Context: Usage Additions; a missing alias file is an I/O failure.
def test_missing_alias_file_exits_1(run, work):
    schema_file(work, "s.json", [("id", "int")])
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("nope.json"), work.path("a.csv"),
    )
    assert r.returncode == 1
    assert r.stdout == ""


# Phrase: "Case-insensitive aliases accepted anywhere type is expected"
# Context: Type Aliases; "anywhere" includes inside nested declarations.
def test_aliases_inside_nested_declarations(run, work):
    alias_file(work, "al.json", {"smallint": "integer"})
    struct = {
        "struct": {
            "fields": [
                {"name": "a", "type": "SmallInt"},
                {"name": "b", "type": {"array": {"element": "Boolean"}}},
            ]
        }
    }
    schema_file(work, "s.json", [("id", "int"), ("v", struct)])
    work.jsonl("a.jsonl", [{"id": 1, "v": {"a": "5", "b": [1, "false"]}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--type-alias-file", work.path("al.json"), work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"a":5,"b":[true,false]}']]
