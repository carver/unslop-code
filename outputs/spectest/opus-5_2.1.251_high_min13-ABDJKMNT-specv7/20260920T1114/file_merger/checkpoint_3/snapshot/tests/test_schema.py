"""Spec section: Schema Resolution & Column Order — explicit --schema handling."""

import json

from conftest import header_of, rows_of


SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {"name": "ts", "type": "timestamp"},
        {"name": "amount", "type": "float"},
        {"name": "note", "type": "string"},
        {"name": "is_active", "type": "bool"},
    ]
}


def write_schema(csv_file, columns, name="schema.json"):
    """Materialise a schema JSON file for the tool to read."""
    return csv_file(name, json.dumps({"columns": columns}))


# Phrase: "If --schema is provided: JSON file with exact output schema and column order"
# Context: Schema Resolution. The documented example schema round-trips.
def test_example_schema_defines_header_and_order(csv_file, run_tool):
    csv_file(
        "a.csv",
        "note,id,amount,is_active,ts\nhi,1,2.5,1,2024-07-01T12:00:00Z\n",
    )
    csv_file("schema.json", json.dumps(SCHEMA))
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "ts", "amount", "note", "is_active"]
    assert rows_of(result.stdout) == [["1", "2024-07-01T12:00:00Z", "2.5", "hi", "true"]]


# Phrase: "Valid types: string, int, float, bool, date, timestamp"
# Context: Schema Resolution. Each declared type is accepted.
def test_every_valid_type_is_accepted(csv_file, run_tool):
    columns = [
        {"name": "s", "type": "string"},
        {"name": "i", "type": "int"},
        {"name": "f", "type": "float"},
        {"name": "b", "type": "bool"},
        {"name": "d", "type": "date"},
        {"name": "t", "type": "timestamp"},
    ]
    write_schema(csv_file, columns)
    csv_file("a.csv", "s,i,f,b,d,t\nx,1,1.5,true,2024-07-01,2024-07-01T00:00:00Z\n")
    result = run_tool(
        "--output", "-", "--key", "i", "--schema", "schema.json",
        "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [
        ["x", "1", "1.5", "true", "2024-07-01", "2024-07-01T00:00:00Z"]
    ]


# Phrase: "Valid types: string, int, float, bool, date, timestamp"
# Context: Schema Resolution. An unlisted type name is rejected.
def test_unknown_schema_type_is_an_error(csv_file, run_tool):
    write_schema(csv_file, [{"name": "id", "type": "decimal"}])
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert result.returncode != 0
    assert result.stderr


# Phrase: "Extra input columns not in schema are ignored"
# Context: Schema Resolution.
def test_extra_input_columns_are_dropped(csv_file, run_tool):
    write_schema(csv_file, [{"name": "id", "type": "int"}])
    csv_file("a.csv", "id,junk\n1,drop me\n")
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert header_of(result.stdout) == ["id"]
    assert rows_of(result.stdout) == [["1"]]


# Phrase: "Missing input columns filled with null literal"
# Context: Schema Resolution. A schema column absent from every input still appears.
def test_schema_column_absent_from_inputs_is_null(csv_file, run_tool):
    write_schema(
        csv_file,
        [{"name": "id", "type": "int"}, {"name": "note", "type": "string"}],
    )
    csv_file("a.csv", "id\n1\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--csv-null-literal", "NA", "a.csv",
    )
    assert rows_of(result.stdout) == [["1", "NA"]]


# Phrase: "Cast every input cell into target type"
# Context: Schema Resolution. The schema type wins over what the data looks like.
def test_schema_type_overrides_apparent_type(csv_file, run_tool):
    write_schema(csv_file, [{"name": "id", "type": "string"}])
    csv_file("a.csv", "id\n10\n9\n")
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert rows_of(result.stdout) == [["10"], ["9"]]


# Phrase: "If --schema is provided: JSON file with exact output schema and column order"
# Context: Schema Resolution. Inference flags are irrelevant when a schema is given.
def test_schema_beats_inference(csv_file, run_tool):
    write_schema(
        csv_file,
        [{"name": "b", "type": "string"}, {"name": "a", "type": "int"}],
    )
    csv_file("a.csv", "a,b\n1,x\n")
    result = run_tool(
        "--output", "-", "--key", "a", "--schema", "schema.json",
        "--infer", "loose", "a.csv",
    )
    assert header_of(result.stdout) == ["b", "a"]


# Phrase: "If --schema is provided: JSON file"
# Context: Schema Resolution. A missing or malformed schema file is an error.
def test_unreadable_schema_file_is_an_error(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "id", "--schema", "nope.json", "a.csv")
    assert result.returncode != 0
    assert result.stderr


def test_malformed_schema_json_is_an_error(csv_file, run_tool):
    csv_file("schema.json", "{not json")
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert result.returncode != 0
    assert result.stderr
