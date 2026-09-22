"""Type aliases: the built-in table, the alias file, lowercasing, transitivity, cycles."""

import pytest


def flat_schema(type_name):
    return {"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": type_name}]}


# Spec: "Primitive types unchanged: string, int, float, bool, date, timestamp"
def test_primitive_types_still_accepted(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,2024-03-04\n")
    schema = json_file("s.json", flat_schema("date"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows == [["id", "v"], ["1", "2024-03-04"]]


# Spec: "Built-in aliases (always present): integer→int, long→int"
@pytest.mark.parametrize("alias", ["integer", "long"])
def test_builtin_integer_aliases(run_cli, csv_file, json_file, alias):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema(alias))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", "7"]


# Spec: "double→float, number→float"
@pytest.mark.parametrize("alias", ["double", "number"])
def test_builtin_float_aliases(run_cli, csv_file, json_file, alias):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema(alias))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", "7.0"]


# Spec: "boolean→bool"
def test_builtin_boolean_alias(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,true\n")
    schema = json_file("s.json", flat_schema("boolean"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] in ("True", "true")


# Spec: "datetime→timestamp, timestamptz→timestamp"
@pytest.mark.parametrize("alias", ["datetime", "timestamptz"])
def test_builtin_timestamp_aliases(run_cli, csv_file, json_file, alias):
    data = csv_file("a.csv", "id,v\n1,2024-03-04 05:06:07\n")
    schema = json_file("s.json", flat_schema(alias))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", "2024-03-04T05:06:07Z"]


# Spec: "text→string, varchar→string"
@pytest.mark.parametrize("alias", ["text", "varchar"])
def test_builtin_string_aliases(run_cli, csv_file, json_file, alias):
    data = csv_file("a.csv", "id,v\n1,0007\n")
    schema = json_file("s.json", flat_schema(alias))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", "0007"]


# Spec: "Case-insensitive aliases accepted anywhere type is expected"
@pytest.mark.parametrize("spelling", ["INTEGER", "Integer", "iNtEgEr", "INT"])
def test_alias_names_are_case_insensitive(run_cli, csv_file, json_file, spelling):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema(spelling))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", "7"]


# Spec: "list<T>→array<T>"
def test_list_alias_is_an_array(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1, 2, 3]}])
    schema = json_file("s.json", flat_schema("list<int>"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", "[1,2,3]"]


# Spec: "list<T>→array<T>" — the alias is case-insensitive like every other name
def test_list_alias_nests(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [[1], [2, 3]]}])
    schema = json_file("s.json", flat_schema("LIST<list<INT>>"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", "[[1],[2,3]]"]


# Spec: "json→struct (accept any JSON, see below)"
@pytest.mark.parametrize("value", [{"b": 1}, [1, "x"], "text", 12, None])
def test_json_alias_accepts_any_json_value(run_cli, jsonl_file, json_file, value):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": value}])
    schema = json_file("s.json", flat_schema("json"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.returncode == 0, result.stderr


# Spec: "Special alias json: ... accept any JSON value ... and emit as JSON text"
def test_json_column_emits_json_text(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"b": [1, {"c": True}]}}])
    schema = json_file("s.json", flat_schema("json"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", '{"b":[1,{"c":true}]}']


# Spec: "Optional alias file via --type-alias-file <ALIASES_JSON>"
def test_alias_file_entries_resolve(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema("smallint"))
    aliases = json_file("al.json", {"aliases": {"smallint": "int", "decimal": "float"}})
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--type-alias-file", aliases, data
    )
    assert result.rows[1] == ["1", "7"]


# Spec: alias file example maps "uuid": "string" and "myts": "timestamp"
def test_alias_file_maps_to_each_primitive_family(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,u,t\n1,0012,2024-03-04T05:06:07+02:00\n")
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "u", "type": "uuid"},
                {"name": "t", "type": "myts"},
            ]
        },
    )
    aliases = json_file("al.json", {"aliases": {"uuid": "string", "myts": "timestamp"}})
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--type-alias-file", aliases, data
    )
    assert result.rows[1] == ["1", "0012", "2024-03-04T03:06:07Z"]


# Spec: "Aliases apply after lowercasing names"
def test_alias_file_keys_and_uses_are_lowercased(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema("SmallInt"))
    aliases = json_file("al.json", {"aliases": {"SMALLINT": "INTEGER"}})
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--type-alias-file", aliases, data
    )
    assert result.rows[1] == ["1", "7"]


# Spec: "May refer to built-ins or other aliases (resolve transitively ...)"
def test_aliases_resolve_transitively(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema("tiny"))
    aliases = json_file("al.json", {"aliases": {"tiny": "smallint", "smallint": "integer"}})
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--type-alias-file", aliases, data
    )
    assert result.rows[1] == ["1", "7"]


# Spec: "resolve transitively; detect cycles → error 2"
def test_alias_cycle_is_error_2(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema("a"))
    aliases = json_file("al.json", {"aliases": {"a": "b", "b": "a"}})
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--type-alias-file", aliases, data
    )
    assert result.returncode == 2, result.stderr


# Spec: "detect cycles → error 2" — a one-step self reference is a cycle too
def test_self_referential_alias_is_error_2(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema("loop"))
    aliases = json_file("al.json", {"aliases": {"loop": "loop"}})
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--type-alias-file", aliases, data
    )
    assert result.returncode == 2, result.stderr


# Spec: "unknown types error deterministically" (AMBIGUITIES T51: exit 1)
def test_unknown_type_is_rejected(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,7\n")
    schema = json_file("s.json", flat_schema("nosuchtype"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.returncode != 0
    assert "nosuchtype" in result.stderr


# Spec: "Case-insensitive aliases accepted anywhere type is expected" — inside a struct
def test_aliases_apply_inside_nested_declarations(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"n": 3, "when": "2024-03-04T05:06:07Z"}}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {
                    "name": "v",
                    "type": {
                        "struct": {
                            "fields": [
                                {"name": "n", "type": "LONG"},
                                {"name": "when", "type": "datetime"},
                            ]
                        }
                    },
                },
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", '{"n":3,"when":"2024-03-04T05:06:07Z"}']


# Spec: aliases may name generic types, so an alias file entry can carry one
def test_alias_file_entry_may_name_a_generic_type(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1, 2]}])
    schema = json_file("s.json", flat_schema("intvec"))
    aliases = json_file("al.json", {"aliases": {"intvec": "list<smallint>", "smallint": "int"}})
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--type-alias-file", aliases, data
    )
    assert result.rows[1] == ["1", "[1,2]"]


# Spec: "Special alias json: ... accept any JSON value (object/array/primitive) and emit as JSON text"
@pytest.mark.parametrize(
    "value,cell", [("free text", '"free text"'), (12, "12"), (True, "true"), (1.5, "1.5")]
)
def test_json_scalars_keep_their_json_spelling(run_cli, jsonl_file, json_file, value, cell):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": value}])
    schema = json_file("s.json", flat_schema("json"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", cell]


# Spec: "If entire column value is null → emit CSV null literal" — a json column too
def test_json_null_uses_the_null_literal(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": None}])
    schema = json_file("s.json", flat_schema("json"))
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--csv-null-literal", "NULL", data
    )
    assert result.rows[1] == ["1", "NULL"]
