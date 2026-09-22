"""End-to-end tests for nested schema types, field paths and type aliases."""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merge_files import main

STRUCT_SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {
            "name": "user",
            "type": {
                "struct": {
                    "fields": [
                        {"name": "id", "type": "integer"},
                        {"name": "name", "type": "text"},
                        {"name": "age", "type": "int"},
                        {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}},
                    ]
                }
            },
        },
        {
            "name": "items",
            "type": {
                "list": {
                    "element": {
                        "struct": {
                            "fields": [
                                {"name": "sku", "type": "string"},
                                {"name": "qty", "type": "int"},
                            ]
                        }
                    }
                }
            },
        },
        {"name": "attrs", "type": {"map": {"key": "string", "value": "string"}}},
        {"name": "event_time", "type": "datetime"},
    ]
}


def write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def write_json(path: Path, document: object) -> str:
    return write(path, json.dumps(document))


def write_jsonl(path: Path, records: list[dict]) -> str:
    return write(path, "".join(json.dumps(record) + "\n" for record in records))


def run(tmp_path: Path, *args: str) -> list[list[str]]:
    """Run the CLI into a file and return the parsed output rows."""
    output = tmp_path / "out.csv"
    assert main(["--output", str(output), *args]) == 0
    return list(csv.reader(output.read_text(encoding="utf-8").splitlines()))


@pytest.fixture
def schema(tmp_path) -> str:
    return write_json(tmp_path / "schema.json", STRUCT_SCHEMA)


def test_nested_values_become_canonical_json(tmp_path, schema):
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [
            {
                "id": 1,
                "user": {"id": 10, "name": "bea", "prefs": {"theme": "dark", "beta": "on"}},
                "items": [{"sku": "b", "qty": 2}, {"sku": "a", "qty": 1}],
                "attrs": {"country": "FR"},
                "event_time": "2024-03-02T10:00:00+02:00",
            }
        ],
    )
    rows = run(tmp_path, "--key", "id", "--schema", schema, source)
    assert rows[1] == [
        "1",
        '{"id":10,"name":"bea","age":null,"prefs":{"beta":"on","theme":"dark"}}',
        '[{"sku":"b","qty":2},{"sku":"a","qty":1}]',
        '{"country":"FR"}',
        "2024-03-02T08:00:00Z",
    ]


def test_a_wholly_null_nested_column_is_the_null_literal(tmp_path, schema):
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "items": None, "attrs": {}}])
    rows = run(tmp_path, "--key", "id", "--csv-null-literal", "NULL", "--schema", schema, source)
    assert rows[1] == ["1", "NULL", "NULL", "{}", "NULL"]


def test_temporal_values_nested_inside_a_struct_are_normalised(tmp_path):
    definition = write_json(
        tmp_path / "schema.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {
                    "name": "span",
                    "type": {
                        "struct": {
                            "fields": [
                                {"name": "day", "type": "date"},
                                {"name": "at", "type": "timestamptz"},
                            ]
                        }
                    },
                },
            ]
        },
    )
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [{"id": 1, "span": {"day": "2024-05-06", "at": "2024-05-06 23:30:00+03:00"}}],
    )
    rows = run(tmp_path, "--key", "id", "--schema", definition, source)
    assert rows[1][1] == '{"day":"2024-05-06","at":"2024-05-06T20:30:00Z"}'


def test_keys_may_point_at_a_nested_leaf(tmp_path, schema):
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [
            {"id": 1, "user": {"id": 30}, "items": [{"sku": "a", "qty": 5}]},
            {"id": 2, "user": {"id": 10}, "items": [{"sku": "b", "qty": 1}]},
            {"id": 3, "user": {"id": 20}, "items": []},
        ],
    )
    rows = run(tmp_path, "--key", "user.id", "--schema", schema, source)
    assert [row[0] for row in rows[1:]] == ["2", "3", "1"]


def test_an_array_index_out_of_range_reads_as_null(tmp_path, schema):
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [
            {"id": 1, "items": [{"sku": "a", "qty": 5}]},
            {"id": 2, "items": []},
            {"id": 3, "items": [{"sku": "c", "qty": 2}]},
        ],
    )
    rows = run(tmp_path, "--key", "items.0.qty", "--schema", schema, source)
    assert [row[0] for row in rows[1:]] == ["2", "3", "1"]


def test_a_map_lookup_can_drive_the_partitioning(tmp_path, schema):
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [{"id": 1, "attrs": {"country": "US"}}, {"id": 2, "attrs": {}}],
    )
    output = tmp_path / "out"
    assert (
        main(
            [
                "--output", str(output),
                "--key", "id",
                "--partition-by", 'attrs["country"]',
                "--schema", schema,
                source,
            ]
        )
        == 0
    )
    assert sorted(path.name for path in output.iterdir()) == [
        'attrs["country"]=US',
        'attrs["country"]=_null',
    ]


def test_a_non_primitive_key_is_an_error(tmp_path, schema, capsys):
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    assert main(["--output", "-", "--key", "user", "--schema", schema, source]) == 3
    assert 'key column "user" does not resolve to a primitive' in capsys.readouterr().err


@pytest.mark.parametrize("path", ["user.nope", "items.-1.qty", "attrs.country", "user.prefs"])
def test_paths_that_do_not_reach_a_primitive_are_errors(tmp_path, schema, path):
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    assert main(["--output", "-", "--key", path, "--schema", schema, source]) == 3


def test_a_malformed_path_is_a_usage_error(tmp_path, schema, capsys):
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    assert main(["--output", "-", "--key", 'attrs["x', "--schema", schema, source]) == 2
    assert "is not a field path" in capsys.readouterr().err


def test_nested_input_without_a_schema_is_rejected(tmp_path, capsys):
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "user": {"id": 2}}])
    assert main(["--output", "-", "--key", "id", source]) == 6
    assert "nested structure requires provided --schema" in capsys.readouterr().err


def test_a_json_cell_without_a_schema_stays_a_string(tmp_path):
    source = write(tmp_path / "a.csv", 'id,payload\n1,"{""a"": 1}"\n')
    rows = run(tmp_path, "--key", "id", source)
    assert rows[1][1] == '{"a": 1}'


def test_delimited_cells_hold_one_json_literal(tmp_path):
    definition = write_json(
        tmp_path / "schema.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "tags", "type": {"array": {"element": "string"}}},
            ]
        },
    )
    source = write(tmp_path / "a.tsv", "id\ttags\n1\t[1,2]\n2\t\n")
    rows = run(tmp_path, "--key", "id", "--schema", definition, source)
    assert [row[1] for row in rows[1:]] == ['["1","2"]', ""]


@pytest.mark.parametrize(
    "policy, expected", [("coerce-null", ""), ("keep-string", '"not json"')]
)
def test_an_invalid_json_cell_follows_the_type_error_policy(tmp_path, policy, expected):
    """A nested cell always holds JSON, so a kept string is a JSON string."""
    definition = write_json(
        tmp_path / "schema.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "tags", "type": {"array": {"element": "string"}}},
            ]
        },
    )
    source = write(tmp_path / "a.tsv", "id\ttags\n1\tnot json\n")
    rows = run(tmp_path, "--key", "id", "--schema", definition, "--on-type-error", policy, source)
    assert rows[1][1] == expected


def test_a_cast_failure_inside_a_nested_value_names_its_path(tmp_path, schema, capsys):
    source = write_jsonl(
        tmp_path / "a.jsonl", [{"id": 1, "items": [{"sku": "s", "qty": "lots"}]}]
    )
    status = main(
        ["--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", source]
    )
    assert status == 4
    assert 'cannot cast "lots" to int in field "items.0.qty"' in capsys.readouterr().err


@pytest.mark.parametrize(
    "policy, expected", [("coerce-null", ""), ("keep-string", '{"a":1}')]
)
def test_nested_input_in_a_flat_column_follows_the_type_error_policy(
    tmp_path, policy, expected
):
    definition = write_json(
        tmp_path / "schema.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "note", "type": "string"}]},
    )
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "note": {"a": 1}}])
    rows = run(tmp_path, "--key", "id", "--schema", definition, "--on-type-error", policy, source)
    assert rows[1][1] == expected


def test_a_json_column_accepts_any_value_and_sorts_by_a_primitive(tmp_path):
    definition = write_json(
        tmp_path / "schema.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "payload", "type": "json"}]},
    )
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [
            {"id": 2, "payload": {"b": 1, "a": [2, {"z": 1, "y": 2}]}},
            {"id": 1, "payload": "hello"},
            {"id": 3, "payload": 42},
        ],
    )
    rows = run(tmp_path, "--key", "id", "--schema", definition, source)
    assert [row[1] for row in rows[1:]] == ['"hello"', '{"a":[2,{"y":2,"z":1}],"b":1}', "42"]


def test_builtin_and_file_aliases_name_the_same_types(tmp_path):
    definition = write_json(
        tmp_path / "schema.json",
        {
            "columns": [
                {"name": "id", "type": "UUID"},
                {"name": "n", "type": "smallint"},
                {"name": "amount", "type": "Decimal"},
                {"name": "ts", "type": "myts"},
            ]
        },
    )
    aliases = write_json(
        tmp_path / "aliases.json",
        {"aliases": {"smallint": "integer", "decimal": "double", "uuid": "text", "myts": "datetime"}},
    )
    source = write(tmp_path / "a.csv", "id,n,amount,ts\nabc,3,1.5,2024-01-01T00:00:00+01:00\n")
    rows = run(
        tmp_path, "--key", "id", "--schema", definition, "--type-alias-file", aliases, source
    )
    assert rows[1] == ["abc", "3", "1.5", "2023-12-31T23:00:00Z"]


def test_an_alias_cycle_is_a_usage_error(tmp_path, capsys):
    definition = write_json(tmp_path / "schema.json", {"columns": [{"name": "id", "type": "a"}]})
    aliases = write_json(tmp_path / "aliases.json", {"aliases": {"a": "b", "b": "a"}})
    source = write(tmp_path / "a.csv", "id\n1\n")
    status = main(
        [
            "--output", "-",
            "--key", "id",
            "--schema", definition,
            "--type-alias-file", aliases,
            source,
        ]
    )
    assert status == 2
    assert "alias cycle: a -> b -> a" in capsys.readouterr().err


def test_an_unknown_type_is_reported_with_its_spelling(tmp_path, capsys):
    definition = write_json(tmp_path / "schema.json", {"columns": [{"name": "id", "type": "blob"}]})
    source = write(tmp_path / "a.csv", "id\n1\n")
    assert main(["--output", "-", "--key", "id", "--schema", definition, source]) == 1
    assert "unknown type 'blob'" in capsys.readouterr().err


def test_duplicate_struct_fields_are_rejected(tmp_path, capsys):
    definition = write_json(
        tmp_path / "schema.json",
        {
            "columns": [
                {
                    "name": "user",
                    "type": {
                        "struct": {
                            "fields": [
                                {"name": "id", "type": "int"},
                                {"name": "id", "type": "string"},
                            ]
                        }
                    },
                }
            ]
        },
    )
    source = write(tmp_path / "a.csv", "user\n\n")
    assert main(["--output", "-", "--key", "user", "--schema", definition, source]) == 1
    assert "duplicate struct field(s) id" in capsys.readouterr().err
