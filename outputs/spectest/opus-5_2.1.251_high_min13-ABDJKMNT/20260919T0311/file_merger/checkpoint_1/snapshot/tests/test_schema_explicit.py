"""Spec section: Schema Resolution & Column Order (the `--schema` branch)."""
import json

from conftest import column, table


# Phrase: "If `--schema` is provided: JSON file with exact output schema and column order"
# Context: the documented schema document shape.
def test_schema_document_from_the_spec(run, csv_file, tmp_path):
    (tmp_path / "schema.json").write_text(
        json.dumps(
            {
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "ts", "type": "timestamp"},
                    {"name": "amount", "type": "float"},
                    {"name": "note", "type": "string"},
                    {"name": "is_active", "type": "bool"},
                ]
            }
        ),
        encoding="utf-8",
    )
    csv_file("a.csv", "id,ts,amount,note,is_active\n1,2024-07-01T12:00:00Z,1.5,hi,1\n")
    res = run("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert res.returncode == 0, res.stderr
    assert table(res.stdout) == [
        ["id", "ts", "amount", "note", "is_active"],
        ["1", "2024-07-01T12:00:00Z", "1.5", "hi", "true"],
    ]


# Phrase: "Valid types: `string`, `int`, `float`, `bool`, `date`, `timestamp`"
# Context: each named type is accepted by the schema loader.
def test_all_valid_types_are_accepted(run, csv_file, schema_file):
    schema = schema_file(
        [
            ("s", "string"),
            ("i", "int"),
            ("f", "float"),
            ("b", "bool"),
            ("d", "date"),
            ("t", "timestamp"),
        ]
    )
    csv_file("a.csv", "s,i,f,b,d,t\nx,1,2.5,true,2024-07-01,2024-07-01T00:00:00Z\n")
    res = run("--output", "-", "--key", "i", "--schema", schema, "a.csv")
    assert res.returncode == 0, res.stderr
    assert table(res.stdout)[1] == [
        "x", "1", "2.5", "true", "2024-07-01", "2024-07-01T00:00:00Z",
    ]


# Phrase: "Valid types: string, int, float, bool, date, timestamp"
# Context: a type outside that set is an error.
def test_unknown_schema_type_is_an_error(run, csv_file, schema_file):
    csv_file("a.csv", "id\n1\n")
    schema = schema_file([("id", "integer")])
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.csv")
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# Phrase: "Extra input columns not in schema are ignored"
# Context: input columns outside the schema never reach the output.
def test_extra_input_columns_are_ignored(run, csv_file, schema_file):
    csv_file("a.csv", "id,junk\n1,drop me\n")
    schema = schema_file([("id", "int")])
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.csv")
    assert table(res.stdout) == [["id"], ["1"]]


# Phrase: "Missing input columns filled with null literal"
# Context: schema columns absent from an input header are null for its rows.
def test_missing_schema_columns_are_null(run, csv_file, schema_file):
    csv_file("a.csv", "id\n1\n")
    schema = schema_file([("id", "int"), ("note", "string")])
    res = run(
        "--output", "-", "--key", "id", "--schema", schema,
        "--csv-null-literal", "<NA>", "a.csv",
    )
    assert table(res.stdout) == [["id", "note"], ["1", "<NA>"]]


# Phrase: "Cast every input cell into target type"
# Context: the schema type wins over what inference would have chosen.
def test_schema_type_overrides_inference(run, csv_file, schema_file):
    csv_file("a.csv", "id\n0007\n")
    schema = schema_file([("id", "string")])
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.csv")
    assert column(res.stdout, "id") == ["0007"]


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: key checked against an explicit schema.
def test_key_absent_from_schema_is_an_error(run, csv_file, schema_file):
    csv_file("a.csv", "id,other\n1,x\n")
    schema = schema_file([("id", "int")])
    res = run("--output", "-", "--key", "other", "--schema", schema, "a.csv")
    assert res.returncode != 0
    assert "other" in res.stderr


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: T19 — also checked against an inferred schema.
def test_key_absent_from_inferred_schema_is_an_error(run, csv_file):
    csv_file("a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "nope", "a.csv")
    assert res.returncode != 0
    assert "nope" in res.stderr


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: every column of a composite key is checked.
def test_second_key_column_absent_is_an_error(run, csv_file):
    csv_file("a.csv", "id,ts\n1,x\n")
    assert run("--output", "-", "--key", "id,missing", "a.csv").returncode != 0


# Phrase: "--schema <SCHEMA_JSON>"
# Context: T10 — the argument may also be an inline JSON document.
def test_schema_may_be_given_inline(run, csv_file):
    csv_file("a.csv", "id\n1\n")
    res = run(
        "--output", "-", "--key", "id",
        "--schema", '{"columns": [{"name": "id", "type": "int"}]}', "a.csv",
    )
    assert res.returncode == 0, res.stderr
    assert table(res.stdout) == [["id"], ["1"]]


# Phrase: "If --schema is provided ... If --schema not provided: infer"
# Context: T18 — --infer is inert alongside --schema rather than an error.
def test_schema_takes_precedence_over_infer(run, csv_file, schema_file):
    csv_file("a.csv", "id\n1\n")
    schema = schema_file([("id", "string")])
    res = run(
        "--output", "-", "--key", "id", "--schema", schema, "--infer", "loose", "a.csv"
    )
    assert res.returncode == 0, res.stderr


# Phrase: "JSON file with exact output schema"
# Context: an unreadable or malformed schema file is an error, not a fallback.
def test_broken_schema_file_is_an_error(run, csv_file, tmp_path):
    csv_file("a.csv", "id\n1\n")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert run("--output", "-", "--key", "id", "--schema", "bad.json", "a.csv").returncode != 0
    assert run("--output", "-", "--key", "id", "--schema", "absent.json", "a.csv").returncode != 0
