"""End-to-end tests for nested schema types, field paths and type aliases."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from helpers import merged_rows, run_cli

NESTED_SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {"name": "event_time", "type": "timestamp"},
        {
            "name": "user",
            "type": {
                "struct": {
                    "fields": [
                        {"name": "id", "type": "int"},
                        {"name": "name", "type": "string"},
                        {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}},
                    ]
                }
            },
        },
        {
            "name": "items",
            "type": {
                "array": {
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
    ]
}

EVENTS = [
    {
        "id": 2,
        "event_time": "2024-05-01T10:00:00+02:00",
        "user": {"id": 7, "name": "ada", "prefs": {"theme": "dark", "algo": "b"}},
        "items": [{"sku": "x1", "qty": "3"}, {"sku": "x2", "qty": 4}],
        "attrs": {"country": "US", "tier": "gold"},
    },
    {
        "id": 1,
        "event_time": "2024-05-01T09:00:00Z",
        "user": {"id": 3, "name": "grace"},
        "items": [],
        "attrs": {"country": "FR"},
    },
    {
        "id": 3,
        "event_time": "2024-05-02T00:00:00Z",
        "user": None,
        "items": [{"sku": "z", "qty": "oops"}],
        "attrs": {},
    },
]


def write_json(path: Path, document: dict) -> str:
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def write_jsonl(path: Path, documents: list[dict]) -> str:
    path.write_text("".join(json.dumps(one) + "\n" for one in documents), encoding="utf-8")
    return str(path)


@pytest.fixture
def events(tmp_path: Path) -> tuple[str, str]:
    """The nested schema file, and a JSON Lines file matching it."""
    return write_json(tmp_path / "schema.json", NESTED_SCHEMA), write_jsonl(
        tmp_path / "events.jsonl", EVENTS
    )


def column(rows: list[list[str]], name: str) -> list[str]:
    return [row[rows[0].index(name)] for row in rows[1:]]


def test_nested_columns_are_written_as_canonical_json(events):
    schema, source = events
    rows = merged_rows("--key", "id", "--schema", schema, source)

    assert column(rows, "user") == [
        '{"id":3,"name":"grace","prefs":null}',
        '{"id":7,"name":"ada","prefs":{"algo":"b","theme":"dark"}}',
        "",
    ]
    assert column(rows, "items") == [
        "[]",
        '[{"sku":"x1","qty":3},{"sku":"x2","qty":4}]',
        '[{"sku":"z","qty":null}]',
    ]
    assert column(rows, "attrs") == ['{"country":"FR"}', '{"country":"US","tier":"gold"}', "{}"]


def test_a_key_reaches_struct_fields_array_elements_and_map_entries(events):
    schema, source = events
    by_user = merged_rows("--key", "user.id,event_time", "--schema", schema, source)
    assert column(by_user, "id") == ["3", "1", "2"]

    by_sku = merged_rows("--key", 'items.0.sku,attrs["country"]', "--desc", "--schema", schema, source)
    assert column(by_sku, "id") == ["3", "2", "1"]


def test_a_missing_array_element_or_map_entry_sorts_as_null(events):
    schema, source = events
    rows = merged_rows("--key", "items.1.qty,id", "--schema", schema, source)
    assert column(rows, "id") == ["1", "3", "2"]


def test_timestamps_inside_nested_values_are_normalised_to_utc(tmp_path):
    schema = write_json(
        tmp_path / "schema.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "seen", "type": "array<timestamp>"}]},
    )
    source = write_jsonl(
        tmp_path / "a.jsonl", [{"id": 1, "seen": ["2024-05-01T10:00:00+02:00", "2024-05-01"]}]
    )
    rows = merged_rows("--key", "id", "--schema", schema, source)
    assert column(rows, "seen") == ['["2024-05-01T08:00:00Z",null]']


def test_partitioning_by_a_map_entry_names_the_whole_path(tmp_path, events):
    schema, source = events
    target = tmp_path / "out"
    result = run_cli(
        "--output", str(target), "--key", "id", "--partition-by", 'attrs["country"]',
        "--schema", schema, source,
    )
    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in target.iterdir()) == [
        "attrs%5B%22country%22%5D=FR",
        "attrs%5B%22country%22%5D=US",
        "attrs%5B%22country%22%5D=_null",
    ]


def test_nested_parquet_matches_the_declared_types(tmp_path, events):
    schema, source = events
    user = pa.struct(
        [("id", pa.int32()), ("name", pa.string()), ("prefs", pa.map_(pa.string(), pa.string()))]
    )
    table = pa.table(
        {
            "id": pa.array([10], pa.int64()),
            "event_time": pa.array(["2024-05-03T05:00:00Z"]),
            "user": pa.array([{"id": 1, "name": "bob", "prefs": [("z", "9"), ("a", "1")]}], user),
            "items": pa.array(
                [[{"sku": "p", "qty": 2}]],
                pa.list_(pa.struct([("sku", pa.string()), ("qty", pa.int64())])),
            ),
            "attrs": pa.array([[("country", "DE")]], pa.map_(pa.string(), pa.string())),
        }
    )
    pq.write_table(table, tmp_path / "users.parquet")

    rows = merged_rows("--key", "user.id", "--schema", schema, source, str(tmp_path / "users.parquet"))
    assert column(rows, "id") == ["3", "10", "1", "2"]
    assert column(rows, "user")[1] == '{"id":1,"name":"bob","prefs":{"a":"1","z":"9"}}'
    assert column(rows, "attrs")[1] == '{"country":"DE"}'


def test_a_text_cell_holds_one_json_literal(tmp_path):
    schema = write_json(
        tmp_path / "schema.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "tags", "type": "array<int>"}]},
    )
    source = tmp_path / "a.tsv"
    source.write_text("id\ttags\n1\t[1,2]\n2\t\n3\tnope\n", encoding="utf-8")

    rows = merged_rows("--key", "id", "--schema", schema, str(source))
    assert column(rows, "tags") == ["[1,2]", "", ""]

    kept = merged_rows("--key", "id", "--schema", schema, "--on-type-error", "keep-string", str(source))
    assert column(kept, "tags") == ["[1,2]", "", '"nope"']


def test_a_cast_failure_inside_a_nested_value_names_its_field(events):
    schema, source = events
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", source)
    assert result.returncode == 1
    assert "cannot cast 'oops' to int for field 'items.0.qty'" in result.stderr


def test_a_json_column_takes_any_value_and_sorts_by_a_primitive(tmp_path):
    schema = write_json(
        tmp_path / "schema.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "blob", "type": "json"}]},
    )
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [{"id": 2, "blob": {"b": 1, "a": [1, {"z": None}]}}, {"id": 1, "blob": "plain"}],
    )
    rows = merged_rows("--key", "id", "--schema", schema, source)
    assert column(rows, "blob") == ['"plain"', '{"a":[1,{"z":null}],"b":1}']


def test_aliases_are_case_insensitive_and_transitive(tmp_path):
    aliases = write_json(
        tmp_path / "aliases.json",
        {"aliases": {"smallint": "int", "myts": "MyStamp", "mystamp": "timestamp", "ids": "list<SmallInt>"}},
    )
    schema = write_json(
        tmp_path / "schema.json",
        {
            "columns": [
                {"name": "id", "type": "SmallInt"},
                {"name": "seen", "type": "myts"},
                {"name": "ids", "type": "IDS"},
                {"name": "score", "type": "Double"},
            ]
        },
    )
    source = write_jsonl(
        tmp_path / "a.jsonl", [{"id": "5", "seen": "2024-01-02 03:04:05", "ids": ["1", 2], "score": 3}]
    )
    rows = merged_rows("--key", "id", "--schema", schema, "--type-alias-file", aliases, source)
    assert rows[1] == ["5", "2024-01-02T03:04:05Z", "[1,2]", "3.0"]


@pytest.mark.parametrize(
    "key, message, code",
    [
        ("user", "does not resolve to a primitive", 3),
        ("user.nope", "has no field 'nope'", 3),
        ("items.x.sku", "is not an array index", 3),
        ("nope", "not in the resolved schema", 3),
    ],
)
def test_a_path_that_is_not_a_primitive_exits_three(events, key, message, code):
    schema, source = events
    result = run_cli("--output", "-", "--key", key, "--schema", schema, source)
    assert result.returncode == code, result.stderr
    assert message in result.stderr


def test_an_alias_cycle_exits_two(tmp_path):
    aliases = write_json(tmp_path / "aliases.json", {"aliases": {"a": "b", "b": "a"}})
    schema = write_json(tmp_path / "schema.json", {"columns": [{"name": "id", "type": "A"}]})
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--type-alias-file", aliases, source
    )
    assert result.returncode == 2
    assert "defined in terms of itself" in result.stderr


def test_an_unknown_type_exits_three(tmp_path):
    schema = write_json(tmp_path / "schema.json", {"columns": [{"name": "id", "type": "widget"}]})
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, source)
    assert result.returncode == 3
    assert "unknown type 'widget'" in result.stderr


def test_nested_input_without_a_schema_exits_six(tmp_path, events):
    _, source = events
    result = run_cli("--output", "-", "--key", "id", source)
    assert result.returncode == 6
    assert "nested structure requires provided --schema" in result.stderr


def test_a_nested_value_in_a_flat_column_follows_the_type_error_policy(tmp_path, events):
    _, source = events
    schema = write_json(
        tmp_path / "flat.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "user", "type": "string"}]},
    )
    coerced = merged_rows("--key", "id", "--schema", schema, source)
    assert column(coerced, "user") == ["", "", ""]

    kept = merged_rows("--key", "id", "--schema", schema, "--on-type-error", "keep-string", source)
    assert column(kept, "user")[0] == '{"id":3,"name":"grace"}'
