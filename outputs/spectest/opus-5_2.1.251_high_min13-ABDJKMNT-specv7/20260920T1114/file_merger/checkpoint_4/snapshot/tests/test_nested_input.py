"""Spec section: Input Handling for Nested — JSONL, Parquet and delimited cells."""

import pyarrow as pa

from conftest import column, rows_of
from nested_helpers import INT, array, mapping, struct, write_schema


def flat_and_nested(make_file):
    """Schema with one flat and one struct column, used by several cases."""
    return write_schema(
        make_file,
        [INT, {"name": "user", "type": struct(("name", "string"), ("age", "int"))}],
    )


# Phrase: "JSONL: Accept nested objects/arrays only when schema declares column as nested"
# Context: Input Handling for Nested.
def test_jsonl_nested_object_matches_a_struct_column(jsonl_file, run_tool):
    flat_and_nested(jsonl_file)
    jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada", "age": "36"}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "user") == ['{"name":"ada","age":36}']


# Phrase: "If schema declares flat type but input has object/array, handle per --on-type-error"
# Context: Input Handling for Nested. coerce-null empties the cell.
def test_object_in_a_flat_column_coerces_to_null(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "v", "type": "int"}])
    jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == [""]


# Phrase: "If schema declares flat type but input has object/array, handle per --on-type-error"
# Context: Input Handling for Nested. keep-string keeps the JSON text.
def test_array_in_a_flat_column_keeps_its_json_text(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "v", "type": "int"}])
    jsonl_file("a.jsonl", [{"id": 1, "v": [1, 2]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "keep-string", "a.jsonl",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "v") == ["[1,2]"]


# Phrase: "If schema declares flat type but input has object/array, handle per --on-type-error"
# Context: Input Handling for Nested. fail stops the run with exit 4.
def test_object_in_a_flat_column_can_fail(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "v", "type": "int"}])
    jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.jsonl",
    )
    assert result.returncode == 4
    assert "ERR 4 cannot cast" in result.stderr


# Phrase: "Parquet: Accept nested structs/lists/maps only when schema declares compatible nested types"
# Context: Input Handling for Nested.
def test_parquet_struct_list_and_map_columns(csv_file, parquet_file, run_tool):
    write_schema(
        csv_file,
        [
            INT,
            {"name": "s", "type": struct(("a", "int"), ("b", "string"))},
            {"name": "xs", "type": array("int")},
            {"name": "m", "type": mapping("string")},
        ],
    )
    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("s", pa.struct([("a", pa.int64()), ("b", pa.string())])),
            ("xs", pa.list_(pa.int64())),
            ("m", pa.map_(pa.string(), pa.string())),
        ]
    )
    parquet_file(
        "a.parquet",
        {
            "id": [1],
            "s": [{"a": 2, "b": "x"}],
            "xs": [[3, 4]],
            "m": [[("z", "1"), ("a", "2")]],
        },
        schema=schema,
    )
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.parquet",
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [
        ["1", '{"a":2,"b":"x"}', "[3,4]", '{"a":"2","z":"1"}']
    ]


# Phrase: "Without schema, nested triggers error 6"
# Context: Input Handling for Nested (Parquet).
def test_nested_parquet_without_schema_is_error_6(parquet_file, run_tool):
    schema = pa.schema([("id", pa.int64()), ("xs", pa.list_(pa.int64()))])
    parquet_file("a.parquet", {"id": [1], "xs": [[1]]}, schema=schema)
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert result.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in result.stderr


# Phrase: "CSV/TSV: Cell must contain single JSON literal when target type is nested or json"
# Context: Input Handling for Nested.
def test_csv_cell_holds_one_json_literal(csv_file, run_tool):
    flat_and_nested(csv_file)
    csv_file("a.csv", 'id,user\n1,"{""name"": ""ada"", ""age"": 36}"\n')
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "user") == ['{"name":"ada","age":36}']


# Phrase: "CSV/TSV: Cell must contain single JSON literal"
# Context: Input Handling for Nested. TSV cells work the same way.
def test_tsv_cell_holds_one_json_literal(tsv_file, run_tool):
    write_schema(tsv_file, [INT, {"name": "xs", "type": array("int")}])
    tsv_file("a.tsv", "id\txs\n1\t[1, 2]\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.tsv",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "xs") == ["[1,2]"]


# Phrase: "Empty cell -> null"
# Context: Input Handling for Nested (CSV/TSV).
def test_empty_cell_is_null_for_a_nested_column(csv_file, run_tool):
    flat_and_nested(csv_file)
    csv_file("a.csv", "id,user\n1,\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "user") == [""]


# Phrase: "Invalid JSON -> handled per --on-type-error/error 5"
# Context: Input Handling for Nested. coerce-null nulls the cell.
def test_invalid_json_cell_coerces_to_null(csv_file, run_tool):
    flat_and_nested(csv_file)
    csv_file("a.csv", "id,user\n1,{oops\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "user") == [""]


# Phrase: "Invalid JSON -> handled per --on-type-error/error 5"
# Context: Input Handling for Nested. keep-string keeps the raw cell text.
def test_invalid_json_cell_can_be_kept(csv_file, run_tool):
    flat_and_nested(csv_file)
    csv_file("a.csv", "id,user\n1,{oops\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "keep-string", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "user") == ["{oops"]


# Phrase: "Invalid JSON -> handled per --on-type-error/error 5"
# Context: Input Handling for Nested. Ambiguity T53: fail exits 4.
def test_invalid_json_cell_under_fail(csv_file, run_tool):
    flat_and_nested(csv_file)
    csv_file("a.csv", "id,user\n1,{oops\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 4
    assert "ERR 4 cannot cast" in result.stderr


# Phrase: "CSV/TSV: Cell must contain single JSON literal when target type is nested or json"
# Context: Input Handling for Nested. Trailing content is not a single literal.
def test_two_json_literals_in_one_cell_are_invalid(csv_file, run_tool):
    write_schema(csv_file, [INT, {"name": "xs", "type": array("int")}])
    csv_file("a.csv", 'id,xs\n1,"[1] [2]"\n')
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 4
    assert result.stderr


# Phrase: "JSONL: Accept nested objects/arrays only when schema declares column as nested or json"
# Context: Input Handling for Nested. A nested column the schema drops is not an error.
def test_nested_column_outside_the_schema_is_dropped(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT])
    jsonl_file("a.jsonl", [{"id": 1, "extra": {"a": 1}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1"]]
