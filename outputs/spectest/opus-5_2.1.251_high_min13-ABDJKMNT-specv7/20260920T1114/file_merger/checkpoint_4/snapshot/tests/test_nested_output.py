"""Spec section: Normalization & Output Encoding — canonical JSON in CSV cells."""

import datetime

import pyarrow as pa

from conftest import column, parse_csv, rows_of
from nested_helpers import INT, array, mapping, struct, write_schema


# Phrase: "If entire column value is null -> emit CSV null literal"
# Context: Normalization & Output Encoding.
def test_missing_nested_value_uses_the_null_literal(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "s", "type": struct(("a", "int"))}])
    jsonl_file("a.jsonl", [{"id": 1}, {"id": 2, "s": None}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--csv-null-literal", "NULL", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "s") == ["NULL", "NULL"]


# Phrase: "CSV null literal applies only when entire cell is null"
# Context: Determinism Checklist. A null field inside the value stays JSON null.
def test_null_inside_a_value_is_json_null(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "s", "type": struct(("a", "int"))}])
    jsonl_file("a.jsonl", [{"id": 1, "s": {"a": None}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--csv-null-literal", "NULL", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "s") == ['{"a":null}']


# Phrase: "Minified (no spaces)"
# Context: Normalization & Output Encoding.
def test_output_json_is_minified(csv_file, run_tool):
    write_schema(csv_file, [INT, {"name": "xs", "type": array("int")}])
    csv_file("a.csv", 'id,xs\n1,"[ 1 , 2 ]"\n')
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ["[1,2]"]


# Phrase: "Struct fields in schema-declared order"
# Context: Normalization & Output Encoding.
def test_struct_field_order_follows_the_schema(jsonl_file, run_tool):
    write_schema(
        jsonl_file,
        [INT, {"name": "s", "type": struct(("c", "int"), ("a", "int"), ("b", "int"))}],
    )
    jsonl_file("a.jsonl", [{"id": 1, "s": {"a": 1, "b": 2, "c": 3}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "s") == ['{"c":3,"a":1,"b":2}']


# Phrase: "All struct fields included (even when null) with explicit null values"
# Context: Normalization & Output Encoding.
def test_absent_struct_fields_are_emitted_as_null(jsonl_file, run_tool):
    write_schema(
        jsonl_file, [INT, {"name": "s", "type": struct(("a", "int"), ("b", "string"))}]
    )
    jsonl_file("a.jsonl", [{"id": 1, "s": {"b": "x"}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "s") == ['{"a":null,"b":"x"}']


# Phrase: "Map keys sorted lexicographically"
# Context: Normalization & Output Encoding.
def test_map_keys_are_sorted(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "m", "type": mapping("int")}])
    jsonl_file("a.jsonl", [{"id": 1, "m": {"b": 1, "A": 2, "a": 3, "0": 4}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "m") == ['{"0":4,"A":2,"a":3,"b":1}']


# Phrase: "Arrays preserve original element order after casting"
# Context: Normalization & Output Encoding.
def test_array_order_is_preserved(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("int")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": [3, 1, 2]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ["[3,1,2]"]


# Phrase: "Minified (no spaces), UTF-8, RFC 8259 JSON escaping"
# Context: Normalization & Output Encoding. Quotes, backslashes and controls escape.
def test_json_escaping_follows_rfc_8259(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("string")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": ['a"b', "c\\d", "e\nf", "\u0001"]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ['["a\\"b","c\\\\d","e\\nf","\\u0001"]']


# Phrase: "Minified (no spaces), UTF-8"
# Context: Normalization & Output Encoding. Non-ASCII text stays UTF-8, unescaped.
def test_non_ascii_text_stays_utf8(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "xs", "type": array("string")}])
    jsonl_file("a.jsonl", [{"id": 1, "xs": ["café", "日本"]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ['["café","日本"]']


# Phrase: "This JSON is the CSV cell content for nested columns"
# Context: Normalization & Output Encoding. The cell is quoted by the CSV dialect.
def test_json_cell_is_csv_quoted(jsonl_file, run_tool):
    write_schema(
        jsonl_file, [INT, {"name": "s", "type": struct(("a", "int"), ("b", "int"))}]
    )
    jsonl_file("a.jsonl", [{"id": 1, "s": {"a": 1, "b": 2}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[1] == '1,"{""a"":1,""b"":2}"'
    assert rows_of(result.stdout) == [["1", '{"a":1,"b":2}']]


# Phrase: "Timestamps inside nested values normalized to UTC Z; date stays YYYY-MM-DD"
# Context: Normalization & Output Encoding. Parquet's typed temporals normalise too.
def test_parquet_temporals_normalise_inside_nested(csv_file, parquet_file, run_tool):
    write_schema(
        csv_file,
        [INT, {"name": "s", "type": struct(("t", "timestamp"), ("d", "date"))}],
    )
    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("s", pa.struct([("t", pa.timestamp("s")), ("d", pa.date32())])),
        ]
    )
    parquet_file(
        "a.parquet",
        {
            "id": [1],
            "s": [
                {
                    "t": datetime.datetime(2024, 7, 1, 3, 0, 0),
                    "d": datetime.date(2024, 7, 1),
                }
            ],
        },
        schema=schema,
    )
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.parquet",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "s") == [
        '{"t":"2024-07-01T03:00:00Z","d":"2024-07-01"}'
    ]


# Phrase: "serialize nested value as canonical JSON"
# Context: Normalization & Output Encoding. An empty object keeps its declared fields.
def test_empty_object_still_lists_declared_fields(csv_file, run_tool):
    write_schema(csv_file, [INT, {"name": "s", "type": struct(("a", "int"))}])
    csv_file("a.csv", "id,s\n1,{}\n")
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert result.returncode == 0, result.stderr
    assert parse_csv(result.stdout)[1][1] == '{"a":null}'
