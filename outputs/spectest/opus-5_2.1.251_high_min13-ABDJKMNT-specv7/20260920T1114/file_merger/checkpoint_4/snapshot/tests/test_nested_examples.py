"""Spec section: Examples — the two documented nested-types command lines."""

import json

import pyarrow as pa

from conftest import read, rows_of, tree
from nested_helpers import mapping, struct, write_schema


NESTED_SCHEMA = [
    {"name": "user", "type": struct(("id", "int"), ("name", "string"))},
    {"name": "event_time", "type": "timestamp"},
    {"name": "attrs", "type": mapping("string")},
]


# Phrase: "Nested schema; key on nested leaf; partition by map value"
# Context: Examples. JSON Lines and Parquet inputs merge under one nested schema.
def test_key_on_nested_leaf_with_map_partition(
    workdir, jsonl_file, parquet_file, run_tool
):
    write_schema(jsonl_file, NESTED_SCHEMA, name="schema_nested.json")
    jsonl_file(
        "inputs/events.jsonl",
        [
            {
                "user": {"id": 2, "name": "b"},
                "event_time": "2024-07-01T12:00:00Z",
                "attrs": {"country": "DE"},
            },
            {
                "user": {"id": 1, "name": "a"},
                "event_time": "2024-07-01T09:00:00+02:00",
                "attrs": {"country": "US"},
            },
        ],
    )
    schema = pa.schema(
        [
            ("user", pa.struct([("id", pa.int64()), ("name", pa.string())])),
            ("event_time", pa.string()),
            ("attrs", pa.map_(pa.string(), pa.string())),
        ]
    )
    parquet_file(
        "inputs/users.parquet",
        {
            "user": [{"id": 1, "name": "a"}],
            "event_time": ["2024-07-02T00:00:00Z"],
            "attrs": [[("country", "US")]],
        },
        schema=schema,
    )
    result = run_tool(
        "--output", "out/", "--key", "user.id,event_time",
        "--partition-by", 'attrs["country"]', "--schema", "schema_nested.json",
        "--on-type-error", "coerce-null",
        "inputs/events.jsonl", "inputs/users.parquet",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        'attrs["country"]=DE/part-00000.csv',
        'attrs["country"]=US/part-00000.csv',
    ]
    us = read(workdir / "out" / 'attrs["country"]=US' / "part-00000.csv")
    assert rows_of(us) == [
        ['{"id":1,"name":"a"}', "2024-07-01T07:00:00Z", '{"country":"US"}'],
        ['{"id":1,"name":"a"}', "2024-07-02T00:00:00Z", '{"country":"US"}'],
    ]


# Phrase: "Accept arbitrary JSON in column while sorting by primitive field"
# Context: Examples. The json column passes through while id orders the rows.
def test_arbitrary_json_column_with_a_primitive_key(workdir, tsv_file, run_tool):
    write_schema(
        tsv_file,
        [{"name": "id", "type": "int"}, {"name": "payload", "type": "json"}],
        name="schema_with_json.json",
    )
    tsv_file("data/a.tsv", 'id\tpayload\n2\t{"b": 1, "a": [1, 2]}\n')
    tsv_file("data/b.tsv", "id\tpayload\n1\t[{}, 3]\n")
    result = run_tool(
        "--output", "merged.csv", "--key", "id",
        "--schema", "schema_with_json.json", "data/a.tsv", "data/b.tsv",
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(read(workdir / "merged.csv")) == [
        ["1", "[{},3]"],
        ["2", '{"a":[1,2],"b":1}'],
    ]


# Phrase: 'where schema_with_json.json contains "type":"json" for flexible column'
# Context: Examples. A json column round-trips values of differing shapes.
def test_json_column_holds_mixed_shapes(workdir, jsonl_file, run_tool):
    jsonl_file(
        "schema.json",
        json.dumps(
            {"columns": [{"name": "id", "type": "int"}, {"name": "p", "type": "json"}]}
        ),
    )
    jsonl_file(
        "a.jsonl",
        [{"id": 1, "p": {"a": 1}}, {"id": 2, "p": [1]}, {"id": 3}],
    )
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1", '{"a":1}'], ["2", "[1]"], ["3", ""]]
